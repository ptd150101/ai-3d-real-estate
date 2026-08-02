from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    LedgerAccount,
    LedgerEntry,
    PaymentIntent,
    PaymentTransaction,
    PaymentWebhookEvent,
    Property,
    ReconciliationRun,
    RefundRequest,
    ReservationOrder,
    User,
)
from .payment_providers import (
    InvalidProviderSignature,
    ProviderConfigurationError,
    ProviderEvent,
    ProviderRequestError,
    get_payment_provider,
    sign_local as _sign_local,
    stripe_signature as _stripe_signature,
    vnpay_signature as _vnpay_signature,
)

ORDER_STATE_RANK = {
    "draft": 0,
    "awaiting_payment": 1,
    "paid": 2,
    "confirmed": 3,
    "completed": 4,
    "refund_pending": 5,
    "partially_refunded": 6,
    "refunded": 7,
    "disputed": 8,
    "cancelled": 9,
    "expired": 9,
    "failed": 9,
}
SUCCESS_STATUSES = {"paid", "succeeded", "00"}
FAILURE_STATUSES = {"failed", "cancelled", "canceled"}


def _provider_secret(provider: str) -> str:
    settings = get_settings()
    if provider == "stripe":
        return settings.stripe_webhook_secret
    if provider == "vnpay":
        return settings.vnpay_hash_secret or settings.vnpay_webhook_secret
    return settings.payment_webhook_secret or settings.secret_key


def sign_local(payload: dict[str, Any], provider: str = "local") -> str:
    """Backwards-compatible helper used by deterministic tests."""
    return _sign_local(payload, _provider_secret(provider))


def verify_local(payload: dict[str, Any], signature: str, provider: str = "local") -> bool:
    from .payment_providers import verify_local as verify

    return verify(payload, signature, _provider_secret(provider))


def vnpay_signature(params: dict[str, Any], secret: str | None = None) -> str:
    return _vnpay_signature(params, secret or _provider_secret("vnpay"))


def stripe_signature(payload: str | bytes, timestamp: int, secret: str | None = None) -> str:
    return _stripe_signature(payload, timestamp, secret or _provider_secret("stripe"))


def _ensure_account(db: Session, org_id: str, code: str, name: str, account_type: str) -> LedgerAccount:
    item = db.scalar(
        select(LedgerAccount)
        .where(LedgerAccount.organization_id == org_id, LedgerAccount.code == code)
        .with_for_update()
    )
    if not item:
        item = LedgerAccount(
            organization_id=org_id,
            code=code,
            name=name,
            account_type=account_type,
            currency="VND",
        )
        try:
            with db.begin_nested():
                db.add(item)
                db.flush()
        except IntegrityError:
            item = db.scalar(
                select(LedgerAccount).where(
                    LedgerAccount.organization_id == org_id,
                    LedgerAccount.code == code,
                )
            )
            if not item:
                raise
    return item


def _post_entries(
    db: Session,
    tx: PaymentTransaction,
    org_id: str,
    order_id: str,
    debit_code: str,
    credit_code: str,
) -> None:
    existing = list(db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)))
    if existing:
        if len(existing) != 2:
            raise HTTPException(status_code=409, detail="Ledger transaction is incomplete")
        return
    cash = _ensure_account(db, org_id, "cash", "Tiền tại nhà cung cấp", "asset")
    liability = _ensure_account(
        db,
        org_id,
        "reservation_liability",
        "Nghĩa vụ tiền đặt chỗ",
        "liability",
    )
    accounts = {"cash": cash, "reservation_liability": liability}
    for direction, code in (("debit", debit_code), ("credit", credit_code)):
        raw = f"{tx.id}:{direction}:{code}:{tx.amount}:{order_id}:VND"
        db.add(
            LedgerEntry(
                organization_id=org_id,
                transaction_id=tx.id,
                account_id=accounts[code].id,
                direction=direction,
                amount=tx.amount,
                currency="VND",
                reference_type="reservation_order",
                reference_id=order_id,
                immutable_hash=hashlib.sha256(raw.encode()).hexdigest(),
            )
        )


def _existing_reservation(db: Session, idempotency_key: str) -> tuple[ReservationOrder, PaymentIntent] | None:
    existing = db.scalar(
        select(ReservationOrder).where(ReservationOrder.idempotency_key == idempotency_key)
    )
    if not existing:
        return None
    intent = db.scalar(select(PaymentIntent).where(PaymentIntent.order_id == existing.id))
    if not intent:
        raise HTTPException(status_code=409, detail="Idempotent reservation is missing payment intent")
    return existing, intent


def create_reservation(
    db: Session,
    *,
    organization_id: str,
    buyer: User,
    property_id: str,
    amount: int,
    provider: str,
    idempotency_key: str,
    client_ip: str | None = None,
) -> tuple[ReservationOrder, PaymentIntent]:
    existing = _existing_reservation(db, idempotency_key)
    if existing:
        return existing
    prop = db.scalar(select(Property).where(Property.id == property_id).with_for_update())
    if not prop or prop.status != "published":
        raise HTTPException(status_code=404, detail="Property unavailable")
    if prop.organization_id and prop.organization_id != organization_id:
        raise HTTPException(status_code=403, detail="Cross-tenant reservation denied")
    if amount <= 0 or amount > max(prop.price, 1):
        raise HTTPException(status_code=422, detail="Invalid reservation amount")
    order = ReservationOrder(
        organization_id=organization_id,
        property_id=property_id,
        buyer_user_id=buyer.id,
        status="awaiting_payment",
        amount=amount,
        currency="VND",
        idempotency_key=idempotency_key,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        metadata_json={
            "disclosure": "Phí giữ chỗ; điều kiện hoàn tiền do đơn vị môi giới công bố."
        },
    )
    db.add(order)
    try:
        db.flush()
        intent = PaymentIntent(
            order_id=order.id,
            provider=provider,
            status="creating",
            amount=amount,
            idempotency_key=f"intent:{idempotency_key}",
            provider_payload_json={},
        )
        db.add(intent)
        db.flush()
        adapter = get_payment_provider(provider)
        checkout = adapter.create_checkout(
            order_id=order.id,
            amount=amount,
            currency=order.currency,
            idempotency_key=intent.idempotency_key,
            description=f"Nestora reservation {order.id}",
            customer_email=buyer.email,
            client_ip=client_ip,
        )
        intent.provider_intent_id = checkout.provider_intent_id
        intent.checkout_url = checkout.checkout_url
        intent.status = checkout.status
        intent.provider_payload_json = checkout.payload
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _existing_reservation(db, idempotency_key)
        if existing:
            return existing
        raise HTTPException(status_code=409, detail="Reservation idempotency conflict")
    except ProviderConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.refresh(order)
    db.refresh(intent)
    return order, intent


def _find_intent(db: Session, event: ProviderEvent, raw_payload: dict[str, Any]) -> PaymentIntent | None:
    candidates: list[Any] = []
    explicit_intent_id = raw_payload.get("intent_id")
    if explicit_intent_id:
        candidates.append(PaymentIntent.id == explicit_intent_id)
    if event.provider_intent_id:
        candidates.append(PaymentIntent.provider_intent_id == event.provider_intent_id)
    if event.order_id:
        candidates.append(PaymentIntent.order_id == event.order_id)
    if not candidates:
        return None
    return db.scalar(select(PaymentIntent).where(or_(*candidates)).with_for_update())


def _validate_event_amount(intent: PaymentIntent, order: ReservationOrder, event: ProviderEvent) -> None:
    if event.amount is not None and event.amount != intent.amount:
        raise HTTPException(status_code=409, detail="Webhook amount does not match payment intent")
    if event.currency and event.currency.upper() != order.currency.upper():
        raise HTTPException(status_code=409, detail="Webhook currency does not match payment intent")


def process_webhook(
    db: Session,
    *,
    provider: str,
    payload: dict[str, Any],
    signature: str,
    raw_body: bytes | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    try:
        adapter = get_payment_provider(provider)
        event = adapter.parse_webhook(
            raw_body=raw_body or json.dumps(payload, separators=(",", ":")).encode(),
            payload=payload,
            signature=signature,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidProviderSignature as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider_event_id = event.event_id or event_id
    if not provider_event_id:
        raise HTTPException(status_code=422, detail="Provider webhook event id is required")
    existing = db.scalar(
        select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == provider,
            PaymentWebhookEvent.event_id == provider_event_id,
        )
    )
    if existing:
        return {"duplicate": True, "status": existing.status}
    webhook = PaymentWebhookEvent(
        provider=provider,
        event_id=provider_event_id,
        signature_valid=True,
        status="processing",
        payload_json=event.payload,
    )
    db.add(webhook)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"duplicate": True, "status": "processed"}
    intent = _find_intent(db, event, payload)
    if not intent:
        webhook.status = "ignored"
        db.commit()
        return {"status": "ignored"}
    order = db.scalar(
        select(ReservationOrder).where(ReservationOrder.id == intent.order_id).with_for_update()
    )
    if not order:
        webhook.status = "ignored"
        db.commit()
        return {"status": "ignored"}
    _validate_event_amount(intent, order, event)
    status = event.status.lower()
    if status in SUCCESS_STATUSES:
        if provider == "stripe" and event.provider_intent_id:
            intent.provider_intent_id = event.provider_intent_id
        if ORDER_STATE_RANK.get(order.status, 0) < ORDER_STATE_RANK["paid"]:
            intent.status = "paid"
            order.status = "paid"
            order.confirmed_at = datetime.now(timezone.utc)
            tx = PaymentTransaction(
                intent_id=intent.id,
                transaction_type="payment",
                status="succeeded",
                amount=intent.amount,
                provider_event_id=provider_event_id,
                raw_json=event.payload,
            )
            db.add(tx)
            db.flush()
            _post_entries(
                db,
                tx,
                order.organization_id,
                order.id,
                "cash",
                "reservation_liability",
            )
    elif status in FAILURE_STATUSES and ORDER_STATE_RANK.get(order.status, 0) < ORDER_STATE_RANK["paid"]:
        intent.status = "failed"
        order.status = "failed"
    webhook.status = "processed"
    db.commit()
    return {"status": order.status, "order_id": order.id, "event_type": event.event_type}


def _refundable_totals(db: Session, order_id: str) -> tuple[int, int]:
    paid = int(
        db.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0))
            .join(PaymentIntent, PaymentTransaction.intent_id == PaymentIntent.id)
            .where(
                PaymentIntent.order_id == order_id,
                PaymentTransaction.transaction_type == "payment",
                PaymentTransaction.status == "succeeded",
            )
        )
        or 0
    )
    refunded = int(
        db.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0))
            .join(PaymentIntent, PaymentTransaction.intent_id == PaymentIntent.id)
            .where(
                PaymentIntent.order_id == order_id,
                PaymentTransaction.transaction_type == "refund",
                PaymentTransaction.status == "succeeded",
            )
        )
        or 0
    )
    return paid, refunded


def request_refund(
    db: Session,
    order: ReservationOrder,
    user: User,
    amount: int,
    reason: str,
) -> RefundRequest:
    order = db.scalar(select(ReservationOrder).where(ReservationOrder.id == order.id).with_for_update())
    if not order or order.status not in {"paid", "confirmed", "partially_refunded"}:
        raise HTTPException(status_code=409, detail="Order is not refundable")
    paid, refunded = _refundable_totals(db, order.id)
    pending = int(
        db.scalar(
            select(func.coalesce(func.sum(RefundRequest.amount), 0)).where(
                RefundRequest.order_id == order.id,
                RefundRequest.status.in_(["pending", "processing"]),
            )
        )
        or 0
    )
    if amount <= 0 or amount > paid - refunded - pending:
        raise HTTPException(status_code=422, detail="Refund exceeds refundable balance")
    item = RefundRequest(
        order_id=order.id,
        amount=amount,
        reason=reason,
        status="pending",
        requested_by_user_id=user.id,
    )
    order.status = "refund_pending"
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def approve_refund(db: Session, refund: RefundRequest, approver: User) -> RefundRequest:
    refund = db.scalar(select(RefundRequest).where(RefundRequest.id == refund.id).with_for_update())
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    if refund.status != "pending":
        return refund
    order = db.scalar(
        select(ReservationOrder).where(ReservationOrder.id == refund.order_id).with_for_update()
    )
    intent = db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.order_id == order.id, PaymentIntent.status == "paid")
        .order_by(PaymentIntent.created_at.desc())
        .with_for_update()
    )
    if not intent or not intent.provider_intent_id:
        raise HTTPException(status_code=409, detail="Paid provider intent is unavailable")
    paid, refunded = _refundable_totals(db, order.id)
    if refund.amount > paid - refunded:
        raise HTTPException(status_code=409, detail="Refund exceeds remaining paid balance")
    refund.status = "processing"
    refund.approved_by_user_id = approver.id
    db.flush()
    try:
        adapter = get_payment_provider(intent.provider)
        provider_refund = adapter.refund(
            provider_intent_id=intent.provider_intent_id,
            amount=refund.amount,
            currency=order.currency,
            idempotency_key=f"refund:{refund.id}",
            reason=refund.reason,
            metadata={
                "refund_id": refund.id,
                "order_id": order.id,
                "approved_by": approver.id,
                "partial": refund.amount < paid - refunded,
                "provider_transaction_no": intent.provider_payload_json.get("vnp_TransactionNo"),
            },
        )
    except ProviderConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    succeeded = provider_refund.status in {"succeeded", "paid", "completed"}
    tx = PaymentTransaction(
        intent_id=intent.id,
        transaction_type="refund",
        status="succeeded" if succeeded else "processing",
        amount=refund.amount,
        provider_event_id=f"refund:{intent.provider}:{provider_refund.provider_refund_id}",
        raw_json={
            "refund_id": refund.id,
            "provider_refund_id": provider_refund.provider_refund_id,
            "provider_status": provider_refund.status,
            "provider_payload": provider_refund.payload,
        },
    )
    db.add(tx)
    db.flush()
    if succeeded:
        _post_entries(
            db,
            tx,
            order.organization_id,
            order.id,
            "reservation_liability",
            "cash",
        )
        refund.status = "completed"
        total_refunded = refunded + refund.amount
        order.status = "refunded" if total_refunded >= paid else "partially_refunded"
    else:
        order.status = "refund_pending"
    db.commit()
    db.refresh(refund)
    return refund


def ledger_balanced(db: Session, transaction_id: str) -> bool:
    rows = list(db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)))
    return (
        sum(item.amount for item in rows if item.direction == "debit")
        == sum(item.amount for item in rows if item.direction == "credit")
        and len(rows) == 2
    )


def reconcile_provider(db: Session, *, organization_id: str, provider: str = "all") -> ReconciliationRun:
    stmt = (
        select(PaymentIntent)
        .join(ReservationOrder, PaymentIntent.order_id == ReservationOrder.id)
        .where(ReservationOrder.organization_id == organization_id)
    )
    if provider != "all":
        stmt = stmt.where(PaymentIntent.provider == provider)
    intents = list(db.scalars(stmt))
    mismatches: list[dict[str, Any]] = []
    matched = 0
    for intent in intents:
        if not intent.provider_intent_id or intent.provider == "local":
            local_tx = db.scalar(
                select(PaymentTransaction).where(
                    PaymentTransaction.intent_id == intent.id,
                    PaymentTransaction.transaction_type == "payment",
                    PaymentTransaction.status == "succeeded",
                )
            )
            if (intent.status == "paid") == bool(local_tx):
                matched += 1
            else:
                mismatches.append({"intent_id": intent.id, "reason": "local transaction mismatch"})
            continue
        try:
            state = get_payment_provider(intent.provider).fetch_payment(
                intent.provider_intent_id,
                order_id=intent.order_id,
            )
        except (ProviderConfigurationError, ProviderRequestError) as exc:
            mismatches.append({"intent_id": intent.id, "reason": str(exc)})
            continue
        expected_paid = intent.status == "paid"
        provider_paid = state.status == "paid"
        amount_matches = state.amount in (None, intent.amount)
        currency_matches = state.currency in (None, "", "VND")
        if expected_paid == provider_paid and amount_matches and currency_matches:
            matched += 1
        else:
            mismatches.append(
                {
                    "intent_id": intent.id,
                    "local_status": intent.status,
                    "provider_status": state.status,
                    "local_amount": intent.amount,
                    "provider_amount": state.amount,
                    "provider_currency": state.currency,
                }
            )
    run = ReconciliationRun(
        organization_id=organization_id,
        provider=provider,
        status="completed" if not mismatches else "attention_required",
        matched_count=matched,
        mismatch_count=len(mismatches),
        report_json={"mismatches": mismatches},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def expire_orders(db: Session) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for order in db.scalars(
        select(ReservationOrder)
        .where(ReservationOrder.status == "awaiting_payment")
        .with_for_update(skip_locked=True)
    ):
        expires = order.expires_at if order.expires_at.tzinfo else order.expires_at.replace(tzinfo=timezone.utc)
        if expires <= now:
            order.status = "expired"
            count += 1
    db.commit()
    return count
