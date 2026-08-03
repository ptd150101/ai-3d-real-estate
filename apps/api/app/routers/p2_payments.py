from __future__ import annotations

import hashlib
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import LedgerEntry, Property, RefundRequest, ReservationOrder, User
from ..p2_dependencies import get_org_context
from ..p2_schemas import RefundCreate, ReservationCreate
from ..services.p2_payments import (
    approve_refund,
    create_reservation,
    ledger_balanced,
    process_webhook,
    reconcile_provider,
    request_refund,
)
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router = APIRouter(tags=["p2-payments"])


def order_dict(item: ReservationOrder) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "property_id": item.property_id,
        "buyer_user_id": item.buyer_user_id,
        "status": item.status,
        "amount": item.amount,
        "currency": item.currency,
        "expires_at": item.expires_at,
        "confirmed_at": item.confirmed_at,
        "metadata": item.metadata_json,
    }


@router.post("/reservations", status_code=201)
def reserve(
    payload: ReservationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    prop = db.get(Property, payload.property_id)
    if not prop or not prop.organization_id:
        raise HTTPException(status_code=404, detail="Property tenant unavailable")
    require_feature(db, prop.organization_id, "payments")
    order, intent = create_reservation(
        db,
        organization_id=prop.organization_id,
        buyer=user,
        property_id=payload.property_id,
        amount=payload.amount,
        provider=payload.provider,
        idempotency_key=payload.idempotency_key,
        client_ip=request.client.host if request.client else None,
    )
    return {
        "order": order_dict(order),
        "payment_intent": {
            "id": intent.id,
            "provider": intent.provider,
            "status": intent.status,
            "checkout_url": intent.checkout_url,
            "amount": intent.amount,
        },
    }


@router.get("/reservations/me")
def my_reservations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return [
        order_dict(item)
        for item in db.scalars(
            select(ReservationOrder)
            .where(ReservationOrder.buyer_user_id == user.id)
            .order_by(ReservationOrder.created_at.desc())
        )
    ]


async def _webhook_payload(request: Request) -> tuple[bytes, dict[str, Any]]:
    raw = await request.body()
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type or not content_type:
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON webhook body") from exc
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        payload = dict(form)
    else:
        payload = dict(request.query_params)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be an object")
    return raw, payload


@router.post("/payments/webhooks/{provider}")
async def webhook(
    provider: str,
    request: Request,
    x_signature: str = Header(default="", alias="X-Signature"),
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    raw, payload = await _webhook_payload(request)
    signature = stripe_signature if provider.lower() == "stripe" else x_signature
    if provider.lower() == "vnpay" and not signature:
        signature = str(payload.get("vnp_SecureHash") or "")
    return process_webhook(
        db,
        provider=provider.lower(),
        event_id=str(payload.get("event_id") or "") or None,
        payload=payload,
        signature=signature,
        raw_body=raw,
    )


@router.post("/reservations/{order_id}/refunds", status_code=201)
def create_refund(
    order_id: str,
    payload: RefundCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(ReservationOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.buyer_user_id != user.id and user.role not in {"admin", "agent"}:
        raise HTTPException(status_code=403, detail="Not allowed")
    item = request_refund(db, order, user, payload.amount, payload.reason)
    return {"id": item.id, "status": item.status, "amount": item.amount, "reason": item.reason}


@router.post("/refunds/{refund_id}/approve")
def approve(
    refund_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "finance.write")
    item = db.get(RefundRequest, refund_id)
    if not item:
        raise HTTPException(status_code=404, detail="Refund not found")
    order = db.get(ReservationOrder, item.order_id)
    if not order or order.organization_id != ctx.organization.id:
        raise HTTPException(status_code=403, detail="Cross-tenant refund denied")
    item = approve_refund(db, item, ctx.user)
    db.refresh(order)
    return {"id": item.id, "status": item.status, "order_status": order.status}


@router.get("/finance/ledger")
def ledger(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "finance.read")
    rows = [
        {
            "id": item.id,
            "transaction_id": item.transaction_id,
            "direction": item.direction,
            "amount": item.amount,
            "currency": item.currency,
            "reference_type": item.reference_type,
            "reference_id": item.reference_id,
            "immutable_hash": item.immutable_hash,
        }
        for item in db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.organization_id == ctx.organization.id)
            .order_by(LedgerEntry.created_at.desc())
        )
    ]
    transaction_ids = {item["transaction_id"] for item in rows}
    return {
        "entries": rows,
        "balanced": all(ledger_balanced(db, transaction_id) for transaction_id in transaction_ids),
    }


@router.post("/finance/reconcile")
def reconcile(
    provider: str = "all",
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "finance.write")
    run = reconcile_provider(db, organization_id=ctx.organization.id, provider=provider.lower())
    return {
        "id": run.id,
        "status": run.status,
        "matched": run.matched_count,
        "mismatches": run.mismatch_count,
        "report": run.report_json,
    }


@router.get("/reservations/{order_id}/receipt")
def receipt(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(ReservationOrder, order_id)
    if not order or (order.buyer_user_id != user.id and user.role not in {"admin", "agent"}):
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in {"paid", "confirmed", "partially_refunded", "refunded", "completed"}:
        raise HTTPException(status_code=409, detail="Payment receipt unavailable")
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer)
    document.drawString(60, 800, "NESTORA PAYMENT RECEIPT")
    document.drawString(60, 770, f"Order: {order.id}")
    document.drawString(60, 750, f"Amount: {order.amount} {order.currency}")
    document.drawString(60, 730, f"Status: {order.status}")
    document.drawString(
        60,
        710,
        "Integrity: " + hashlib.sha256((order.id + str(order.amount) + order.status).encode()).hexdigest(),
    )
    document.save()
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receipt-{order.id}.pdf"'},
    )
