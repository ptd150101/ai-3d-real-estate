from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo
import base64

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    NotificationDelivery,
    NotificationEvent,
    NotificationPreference,
    NotificationTemplate,
    NotificationUnsubscribe,
    User,
)
from .jobs_p1 import enqueue_job

DEFAULT_TEMPLATES: dict[str, tuple[str, str]] = {
    "saved_search.match": ("Có bất động sản mới phù hợp", "{count} bất động sản mới phù hợp với bộ lọc “{search_name}”."),
    "appointment.created": ("Đã nhận lịch xem nhà", "Lịch xem {property_title} lúc {scheduled_at} đang chờ xác nhận."),
    "appointment.confirmed": ("Lịch xem đã được xác nhận", "Lịch xem {property_title} lúc {scheduled_at} đã được xác nhận."),
    "appointment.rescheduled": ("Lịch xem đã thay đổi", "Thời gian mới: {scheduled_at}."),
    "appointment.cancelled": ("Lịch xem đã hủy", "Lịch xem {property_title} đã được hủy."),
    "appointment.reminder": ("Nhắc lịch xem nhà", "Bạn có lịch xem {property_title} lúc {scheduled_at}."),
    "chat.message_received": ("Bạn có tin nhắn mới", "{sender_name}: {preview}"),
    "legal_document.shared": ("Tài liệu pháp lý được chia sẻ", "Bạn được cấp quyền xem tài liệu {document_title}."),
    "lead.assigned": ("Lead mới được phân công", "Lead {lead_name} đã được phân công cho bạn."),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)




def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def next_allowed_time(preference: NotificationPreference, now: datetime | None = None) -> datetime:
    now = now or utcnow()
    if not preference.quiet_hours_start or not preference.quiet_hours_end:
        return now
    local = now.astimezone(ZoneInfo(preference.timezone))
    start, end = preference.quiet_hours_start, preference.quiet_hours_end
    current = local.timetz().replace(tzinfo=None)
    if start < end:
        in_quiet = start <= current < end
        end_date = local.date()
    else:
        in_quiet = current >= start or current < end
        end_date = local.date() + (timedelta(days=1) if current >= start else timedelta())
    if not in_quiet:
        return now
    local_end = datetime.combine(end_date, end, tzinfo=ZoneInfo(preference.timezone))
    return local_end.astimezone(timezone.utc)


def create_unsubscribe_token(user_id: str, channel: str, event_type: str | None = None, days: int = 30) -> str:
    payload = {"uid": user_id, "channel": channel, "event": event_type, "exp": int((utcnow() + timedelta(days=days)).timestamp())}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(get_settings().secret_key.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"


def consume_unsubscribe_token(db: Session, token: str) -> NotificationUnsubscribe:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(get_settings().secret_key.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), signature):
            raise ValueError("Invalid unsubscribe token")
        payload = json.loads(_unb64(encoded))
        if int(payload.get("exp", 0)) < int(utcnow().timestamp()):
            raise ValueError("Unsubscribe token expired")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        existing = db.scalar(select(NotificationUnsubscribe).where(NotificationUnsubscribe.token_hash == token_hash))
        if existing:
            return existing
        item = NotificationUnsubscribe(user_id=payload["uid"], channel=payload["channel"], event_type=payload.get("event"), token_hash=token_hash)
        db.add(item); db.flush(); return item
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid unsubscribe token") from exc


def preference_for(db: Session, user_id: str) -> NotificationPreference:
    item = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if item:
        return item
    item = NotificationPreference(user_id=user_id)
    db.add(item)
    db.flush()
    return item


def category_enabled(preference: NotificationPreference, event_type: str) -> bool:
    category = event_type.split(".", 1)[0]
    return preference.categories_json.get(event_type, preference.categories_json.get(category, True))


def is_unsubscribed(db: Session, user_id: str, channel: str, event_type: str) -> bool:
    return bool(db.scalar(select(NotificationUnsubscribe.id).where(
        NotificationUnsubscribe.user_id == user_id,
        NotificationUnsubscribe.channel == channel,
        (NotificationUnsubscribe.event_type == event_type) | (NotificationUnsubscribe.event_type.is_(None)),
    )))


def render_template(db: Session, event_type: str, channel: str, payload: dict[str, Any]) -> tuple[str | None, str]:
    custom = db.scalar(select(NotificationTemplate).where(
        NotificationTemplate.event_type == event_type,
        NotificationTemplate.channel == channel,
        NotificationTemplate.locale == "vi",
        NotificationTemplate.enabled.is_(True),
    ))
    default_subject, default_body = DEFAULT_TEMPLATES.get(event_type, ("Thông báo từ Nestora", "Bạn có cập nhật mới trên Nestora."))
    subject_template = custom.subject_template if custom else default_subject
    body_template = custom.body_template if custom else default_body
    safe = {key: str(value) for key, value in payload.items()}
    try:
        subject = subject_template.format_map(safe) if subject_template else None
    except (KeyError, ValueError):
        subject = default_subject
    try:
        body = body_template.format_map(safe)
    except (KeyError, ValueError):
        body = default_body
    return subject, body


def emit_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str | None,
    recipients: list[str],
    payload: dict[str, Any],
    idempotency_key: str,
    actor_user_id: str | None = None,
) -> NotificationEvent:
    existing = db.scalar(select(NotificationEvent).where(NotificationEvent.idempotency_key == idempotency_key))
    if existing:
        return existing
    event = NotificationEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor_user_id=actor_user_id,
        payload_json=payload,
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    for user_id in dict.fromkeys(recipients):
        user = db.get(User, user_id)
        if not user or not user.is_active:
            continue
        preference = preference_for(db, user_id)
        if not category_enabled(preference, event_type):
            continue
        channels: list[tuple[str, bool, str | None]] = [
            ("in_app", preference.in_app_enabled, user.email),
            ("email", preference.email_enabled, user.email),
            ("zalo", preference.zalo_enabled, user.phone),
        ]
        for channel, enabled, recipient in channels:
            if not enabled or (channel != "in_app" and not recipient) or is_unsubscribed(db, user_id, channel, event_type):
                continue
            subject, body = render_template(db, event_type, channel, payload)
            delivery_key = f"{event.id}:{user_id}:{channel}"
            scheduled_at = next_allowed_time(preference) if channel != "in_app" else utcnow()
            delivery = NotificationDelivery(
                event_id=event.id,
                user_id=user_id,
                channel=channel,
                provider="database" if channel == "in_app" else "pending",
                recipient=recipient,
                subject=subject,
                body=body,
                status="delivered" if channel == "in_app" else "queued",
                delivered_at=utcnow() if channel == "in_app" else None,
                run_after=scheduled_at,
                idempotency_key=delivery_key,
            )
            db.add(delivery)
            db.flush()
            if channel != "in_app":
                enqueue_job(db, "notification_delivery", {"delivery_id": delivery.id}, idempotency_key=f"notify:{delivery.id}", run_after=scheduled_at)
    event.status = "dispatched"
    return event


def _send_email(delivery: NotificationDelivery) -> str:
    settings = get_settings()
    if not getattr(settings, "smtp_host", None):
        return f"local-email-{delivery.id}"
    message = EmailMessage()
    message["Subject"] = delivery.subject or "Nestora"
    message["From"] = settings.smtp_from
    message["To"] = delivery.recipient
    unsubscribe_url = f"{settings.site_url.rstrip('/')}/api/backend/notifications/unsubscribe?token={create_unsubscribe_token(delivery.user_id, 'email')}"
    message.set_content(delivery.body + f"\n\nNgừng nhận email: {unsubscribe_url}")
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        if settings.smtp_starttls:
            client.starttls(context=context)
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)
    return message["Message-ID"] or f"smtp-{uuid.uuid4()}"


def _send_zalo(delivery: NotificationDelivery) -> str:
    settings = get_settings()
    if not getattr(settings, "zalo_endpoint", None) or not getattr(settings, "zalo_token", None):
        return f"local-zalo-{delivery.id}"
    response = httpx.post(
        settings.zalo_endpoint,
        headers={"Authorization": f"Bearer {settings.zalo_token}"},
        json={"recipient": delivery.recipient, "message": delivery.body},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    return str(data.get("message_id") or data.get("id") or uuid.uuid4())


def deliver(db: Session, delivery_id: str) -> dict[str, Any]:
    delivery = db.get(NotificationDelivery, delivery_id)
    if not delivery:
        return {"status": "missing"}
    if delivery.status in {"sent", "delivered"}:
        return {"status": delivery.status, "provider_message_id": delivery.provider_message_id}
    delivery.attempts += 1
    try:
        if delivery.channel == "email":
            provider_id = _send_email(delivery)
            delivery.provider = "smtp" if get_settings().smtp_host else "local"
        elif delivery.channel == "zalo":
            provider_id = _send_zalo(delivery)
            delivery.provider = "zalo" if get_settings().zalo_endpoint else "local"
        else:
            provider_id = f"db-{delivery.id}"
            delivery.provider = "database"
        delivery.provider_message_id = provider_id
        delivery.status = "sent"
        delivery.sent_at = utcnow()
        delivery.last_error = None
        db.commit()
        return {"status": "sent", "provider_message_id": provider_id}
    except Exception as exc:
        delivery.last_error = str(exc)
        delivery.status = "failed" if delivery.attempts >= delivery.max_attempts else "queued"
        delivery.failed_at = utcnow() if delivery.status == "failed" else None
        db.commit()
        raise


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    settings = get_settings()
    secret = getattr(settings, "notification_webhook_secret", "")
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def update_delivery_from_webhook(db: Session, provider_message_id: str, status: str, error: str | None = None) -> NotificationDelivery | None:
    item = db.scalar(select(NotificationDelivery).where(NotificationDelivery.provider_message_id == provider_message_id))
    if not item:
        return None
    item.status = status
    if status == "delivered":
        item.delivered_at = utcnow()
    elif status == "failed":
        item.failed_at = utcnow()
        item.last_error = error
    db.commit()
    return item
