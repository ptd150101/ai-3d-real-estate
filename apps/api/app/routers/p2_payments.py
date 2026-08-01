from __future__ import annotations

import hashlib, io, json
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import LedgerEntry, PaymentIntent, PaymentTransaction, Property, ReconciliationRun, RefundRequest, ReservationOrder, User
from ..p2_dependencies import get_org_context
from ..p2_schemas import PaymentWebhookPayload, RefundCreate, ReservationCreate
from ..services.p2_payments import approve_refund, create_reservation, ledger_balanced, process_webhook, request_refund
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router=APIRouter(tags=["p2-payments"])

def order_dict(x): return {"id":x.id,"organization_id":x.organization_id,"property_id":x.property_id,"buyer_user_id":x.buyer_user_id,"status":x.status,"amount":x.amount,"currency":x.currency,"expires_at":x.expires_at,"confirmed_at":x.confirmed_at,"metadata":x.metadata_json}

@router.post("/reservations",status_code=201)
def reserve(payload:ReservationCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    prop=db.get(Property,payload.property_id)
    if not prop or not prop.organization_id: raise HTTPException(status_code=404,detail="Property tenant unavailable")
    require_feature(db,prop.organization_id,"payments"); order,intent=create_reservation(db,organization_id=prop.organization_id,buyer=user,property_id=payload.property_id,amount=payload.amount,provider=payload.provider,idempotency_key=payload.idempotency_key)
    return {"order":order_dict(order),"payment_intent":{"id":intent.id,"provider":intent.provider,"status":intent.status,"checkout_url":intent.checkout_url,"amount":intent.amount}}

@router.get("/reservations/me")
def my_reservations(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return [order_dict(x) for x in db.scalars(select(ReservationOrder).where(ReservationOrder.buyer_user_id==user.id).order_by(ReservationOrder.created_at.desc()))]

@router.post("/payments/webhooks/{provider}")
def webhook(provider:str,payload:PaymentWebhookPayload,x_signature:str=Header(default="",alias="X-Signature"),db:Session=Depends(get_db)):
    data=payload.model_dump(exclude={"event_id","metadata"}); data.update(payload.metadata); return process_webhook(db,provider=provider,event_id=payload.event_id,payload=data,signature=x_signature)

@router.post("/reservations/{order_id}/refunds",status_code=201)
def create_refund(order_id:str,payload:RefundCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    order=db.get(ReservationOrder,order_id)
    if not order: raise HTTPException(status_code=404,detail="Order not found")
    if order.buyer_user_id!=user.id and user.role not in {"admin","agent"}: raise HTTPException(status_code=403,detail="Not allowed")
    item=request_refund(db,order,user,payload.amount,payload.reason); return {"id":item.id,"status":item.status,"amount":item.amount,"reason":item.reason}

@router.post("/refunds/{refund_id}/approve")
def approve(refund_id:str,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"finance.write"); item=db.get(RefundRequest,refund_id)
    if not item: raise HTTPException(status_code=404,detail="Refund not found")
    order=db.get(ReservationOrder,item.order_id)
    if order.organization_id!=ctx.organization.id: raise HTTPException(status_code=403,detail="Cross-tenant refund denied")
    item=approve_refund(db,item,ctx.user); return {"id":item.id,"status":item.status,"order_status":order.status}

@router.get("/finance/ledger")
def ledger(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"finance.read"); rows=[]
    for x in db.scalars(select(LedgerEntry).where(LedgerEntry.organization_id==ctx.organization.id).order_by(LedgerEntry.created_at.desc())):
        rows.append({"id":x.id,"transaction_id":x.transaction_id,"direction":x.direction,"amount":x.amount,"currency":x.currency,"reference_type":x.reference_type,"reference_id":x.reference_id,"immutable_hash":x.immutable_hash})
    tx_ids={x["transaction_id"] for x in rows}; return {"entries":rows,"balanced":all(ledger_balanced(db,tx) for tx in tx_ids)}

@router.post("/finance/reconcile")
def reconcile(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"finance.write"); intents=list(db.scalars(select(PaymentIntent).join(ReservationOrder,PaymentIntent.order_id==ReservationOrder.id).where(ReservationOrder.organization_id==ctx.organization.id)))
    mismatches=[x.id for x in intents if x.status=="paid" and not db.scalar(select(PaymentTransaction).where(PaymentTransaction.intent_id==x.id,PaymentTransaction.transaction_type=="payment"))]
    run=ReconciliationRun(organization_id=ctx.organization.id,provider="all",status="completed",matched_count=len(intents)-len(mismatches),mismatch_count=len(mismatches),report_json={"mismatch_intent_ids":mismatches}); db.add(run); db.commit(); return {"id":run.id,"matched":run.matched_count,"mismatches":run.mismatch_count,"report":run.report_json}

@router.get("/reservations/{order_id}/receipt")
def receipt(order_id:str,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    order=db.get(ReservationOrder,order_id)
    if not order or (order.buyer_user_id!=user.id and user.role not in {"admin","agent"}): raise HTTPException(status_code=404,detail="Order not found")
    if order.status not in {"paid","confirmed","partially_refunded","refunded","completed"}: raise HTTPException(status_code=409,detail="Payment receipt unavailable")
    buf=io.BytesIO(); c=canvas.Canvas(buf); c.drawString(60,800,"NESTORA PAYMENT RECEIPT"); c.drawString(60,770,f"Order: {order.id}"); c.drawString(60,750,f"Amount: {order.amount} {order.currency}"); c.drawString(60,730,f"Status: {order.status}"); c.drawString(60,710,f"Integrity: {hashlib.sha256((order.id+str(order.amount)+order.status).encode()).hexdigest()}"); c.save(); return Response(buf.getvalue(),media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="receipt-{order.id}.pdf"'})
