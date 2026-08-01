from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote_plus

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    LedgerAccount, LedgerEntry, PaymentIntent, PaymentTransaction, PaymentWebhookEvent,
    Property, RefundRequest, ReservationOrder, User,
)

ORDER_STATE_RANK={"draft":0,"awaiting_payment":1,"paid":2,"confirmed":3,"completed":4,"refund_pending":5,"partially_refunded":6,"refunded":7,"disputed":8,"cancelled":9,"expired":9,"failed":9}


def _secret(provider: str) -> str:
    settings=get_settings()
    return getattr(settings,f"{provider}_webhook_secret",None) or settings.payment_webhook_secret or settings.secret_key


def sign_local(payload: dict, provider: str="local") -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return hmac.new(_secret(provider).encode(),raw,hashlib.sha256).hexdigest()


def verify_local(payload: dict, signature: str, provider: str="local") -> bool:
    return hmac.compare_digest(sign_local(payload,provider),signature)


def vnpay_signature(params: dict[str,str], secret: str | None=None) -> str:
    clean={k:str(v) for k,v in params.items() if k not in {"vnp_SecureHash","vnp_SecureHashType"} and v not in (None,"")}
    canonical=urlencode(sorted(clean.items()),quote_via=quote_plus)
    return hmac.new((secret or _secret("vnpay")).encode(),canonical.encode(),hashlib.sha512).hexdigest()


def stripe_signature(payload: str, timestamp: int, secret: str | None=None) -> str:
    return hmac.new((secret or _secret("stripe")).encode(),f"{timestamp}.{payload}".encode(),hashlib.sha256).hexdigest()


def _ensure_account(db: Session, org_id: str, code: str, name: str, account_type: str) -> LedgerAccount:
    item=db.scalar(select(LedgerAccount).where(LedgerAccount.organization_id==org_id,LedgerAccount.code==code))
    if not item: item=LedgerAccount(organization_id=org_id,code=code,name=name,account_type=account_type,currency="VND"); db.add(item); db.flush()
    return item


def _post_entries(db: Session, tx: PaymentTransaction, org_id: str, order_id: str, debit_code: str, credit_code: str) -> None:
    cash=_ensure_account(db,org_id,"cash","Tiền tại nhà cung cấp","asset")
    liability=_ensure_account(db,org_id,"reservation_liability","Nghĩa vụ tiền đặt chỗ","liability")
    accounts={"cash":cash,"reservation_liability":liability}
    for direction,code in (("debit",debit_code),("credit",credit_code)):
        raw=f"{tx.id}:{direction}:{code}:{tx.amount}:{order_id}"
        db.add(LedgerEntry(organization_id=org_id,transaction_id=tx.id,account_id=accounts[code].id,direction=direction,amount=tx.amount,currency="VND",reference_type="reservation_order",reference_id=order_id,immutable_hash=hashlib.sha256(raw.encode()).hexdigest()))


def create_reservation(db: Session, *, organization_id: str, buyer: User, property_id: str, amount: int, provider: str, idempotency_key: str) -> tuple[ReservationOrder,PaymentIntent]:
    existing=db.scalar(select(ReservationOrder).where(ReservationOrder.idempotency_key==idempotency_key))
    if existing:
        intent=db.scalar(select(PaymentIntent).where(PaymentIntent.order_id==existing.id)); return existing,intent
    prop=db.get(Property,property_id)
    if not prop or prop.status!="published": raise HTTPException(status_code=404,detail="Property unavailable")
    if prop.organization_id and prop.organization_id!=organization_id: raise HTTPException(status_code=403,detail="Cross-tenant reservation denied")
    if amount<=0 or amount>max(prop.price,1): raise HTTPException(status_code=422,detail="Invalid reservation amount")
    order=ReservationOrder(organization_id=organization_id,property_id=property_id,buyer_user_id=buyer.id,status="awaiting_payment",amount=amount,currency="VND",idempotency_key=idempotency_key,expires_at=datetime.now(timezone.utc)+timedelta(minutes=30),metadata_json={"disclosure":"Phí giữ chỗ; điều kiện hoàn tiền do đơn vị môi giới công bố."})
    db.add(order); db.flush()
    provider_id=f"{provider}_{secrets.token_hex(8)}"
    if provider=="vnpay":
        params={"vnp_Version":"2.1.0","vnp_Command":"pay","vnp_TmnCode":"SANDBOX","vnp_Amount":str(amount*100),"vnp_TxnRef":order.id,"vnp_OrderInfo":f"Nestora reservation {order.id}","vnp_ReturnUrl":f"{get_settings().site_url}/payments/return"}
        params["vnp_SecureHash"]=vnpay_signature(params); checkout=f"https://sandbox.vnpayment.vn/paymentv2/vpcpay.html?{urlencode(params)}"
    elif provider=="stripe": checkout=f"{get_settings().site_url}/payments/sandbox/stripe/{provider_id}"
    else: checkout=f"{get_settings().site_url}/payments/sandbox/local/{provider_id}"
    intent=PaymentIntent(order_id=order.id,provider=provider,provider_intent_id=provider_id,status="created",amount=amount,checkout_url=checkout,idempotency_key=f"intent:{idempotency_key}",provider_payload_json={})
    db.add(intent); db.commit(); db.refresh(order); db.refresh(intent); return order,intent


def process_webhook(db: Session, *, provider: str, event_id: str, payload: dict, signature: str) -> dict:
    existing=db.scalar(select(PaymentWebhookEvent).where(PaymentWebhookEvent.provider==provider,PaymentWebhookEvent.event_id==event_id))
    if existing: return {"duplicate":True,"status":existing.status}
    valid = vnpay_signature({k:str(v) for k,v in payload.items()})==signature if provider=="vnpay" else verify_local(payload,signature,provider)
    event=PaymentWebhookEvent(provider=provider,event_id=event_id,signature_valid=valid,status="rejected" if not valid else "processing",payload_json=payload)
    db.add(event); db.flush()
    if not valid: db.commit(); raise HTTPException(status_code=400,detail="Invalid webhook signature")
    intent=db.scalar(select(PaymentIntent).where((PaymentIntent.id==payload.get("intent_id")) | (PaymentIntent.provider_intent_id==payload.get("provider_intent_id"))))
    if not intent: event.status="ignored"; db.commit(); return {"status":"ignored"}
    order=db.get(ReservationOrder,intent.order_id)
    status=str(payload.get("status","paid"))
    if status in {"paid","succeeded","00"}:
        if ORDER_STATE_RANK.get(order.status,0) < ORDER_STATE_RANK["paid"]:
            intent.status="paid"; order.status="paid"; order.confirmed_at=datetime.now(timezone.utc)
            tx=PaymentTransaction(intent_id=intent.id,transaction_type="payment",status="succeeded",amount=intent.amount,provider_event_id=event_id,raw_json=payload)
            db.add(tx); db.flush(); _post_entries(db,tx,order.organization_id,order.id,"cash","reservation_liability")
    elif status in {"failed","cancelled"} and ORDER_STATE_RANK.get(order.status,0)<ORDER_STATE_RANK["paid"]:
        intent.status="failed"; order.status="failed"
    event.status="processed"; db.commit(); return {"status":order.status,"order_id":order.id}


def request_refund(db: Session, order: ReservationOrder, user: User, amount: int, reason: str) -> RefundRequest:
    if order.status not in {"paid","confirmed","partially_refunded"}: raise HTTPException(status_code=409,detail="Order is not refundable")
    paid=int(db.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount),0)).join(PaymentIntent,PaymentTransaction.intent_id==PaymentIntent.id).where(PaymentIntent.order_id==order.id,PaymentTransaction.transaction_type=="payment",PaymentTransaction.status=="succeeded")) or 0)
    refunded=int(db.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount),0)).join(PaymentIntent,PaymentTransaction.intent_id==PaymentIntent.id).where(PaymentIntent.order_id==order.id,PaymentTransaction.transaction_type=="refund",PaymentTransaction.status=="succeeded")) or 0)
    if amount<=0 or amount>paid-refunded: raise HTTPException(status_code=422,detail="Refund exceeds refundable balance")
    item=RefundRequest(order_id=order.id,amount=amount,reason=reason,status="pending",requested_by_user_id=user.id); order.status="refund_pending"; db.add(item); db.commit(); db.refresh(item); return item


def approve_refund(db: Session, refund: RefundRequest, approver: User) -> RefundRequest:
    if refund.status!="pending": return refund
    order=db.get(ReservationOrder,refund.order_id); intent=db.scalar(select(PaymentIntent).where(PaymentIntent.order_id==order.id).order_by(PaymentIntent.created_at.desc()))
    tx=PaymentTransaction(intent_id=intent.id,transaction_type="refund",status="succeeded",amount=refund.amount,provider_event_id=f"refund:{refund.id}",raw_json={"refund_id":refund.id})
    db.add(tx); db.flush(); _post_entries(db,tx,order.organization_id,order.id,"reservation_liability","cash")
    refund.status="completed"; refund.approved_by_user_id=approver.id
    total_refunded=int(db.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount),0)).where(PaymentTransaction.intent_id==intent.id,PaymentTransaction.transaction_type=="refund",PaymentTransaction.status=="succeeded")) or 0)
    order.status="refunded" if total_refunded>=order.amount else "partially_refunded"
    db.commit(); db.refresh(refund); return refund


def ledger_balanced(db: Session, transaction_id: str) -> bool:
    rows=list(db.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id==transaction_id)))
    return sum(x.amount for x in rows if x.direction=="debit")==sum(x.amount for x in rows if x.direction=="credit") and bool(rows)


def expire_orders(db: Session) -> int:
    now=datetime.now(timezone.utc); count=0
    for order in db.scalars(select(ReservationOrder).where(ReservationOrder.status=="awaiting_payment")):
        expires=order.expires_at if order.expires_at.tzinfo else order.expires_at.replace(tzinfo=timezone.utc)
        if expires<=now: order.status="expired"; count+=1
    db.commit(); return count
