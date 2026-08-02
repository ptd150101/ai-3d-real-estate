from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Favorite, MobileDevice, MobileMutation, MobileRefreshToken, Property, User
from ..security import create_access_token, verify_password
from .push_notifications import PushDeliveryError, PushMessage, send_expo_push


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_refresh_token(db: Session, user: User, device_id: str) -> tuple[str, MobileRefreshToken]:
    raw = secrets.token_urlsafe(48)
    item = MobileRefreshToken(
        user_id=user.id,
        device_id=device_id,
        token_hash=_hash(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().mobile_refresh_days),
    )
    db.add(item)
    db.flush()
    return raw, item


def issue_refresh_token(db: Session, user: User, device_id: str) -> tuple[str, MobileRefreshToken]:
    raw, item = _new_refresh_token(db, user, device_id)
    db.commit()
    db.refresh(item)
    return raw, item


def mobile_login(db: Session, email: str, password: str, device_id: str) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    raw, _ = issue_refresh_token(db, user, device_id)
    return {
        "access_token": create_access_token(user.id, user.role, 60),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
    }


def _revoke_device_family(db: Session, user_id: str, device_id: str, now: datetime) -> int:
    count = 0
    for token in db.scalars(
        select(MobileRefreshToken)
        .where(
            MobileRefreshToken.user_id == user_id,
            MobileRefreshToken.device_id == device_id,
            MobileRefreshToken.revoked_at.is_(None),
        )
        .with_for_update()
    ):
        token.revoked_at = now
        count += 1
    return count


def rotate_refresh_token(db: Session, raw: str, device_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    token_hash = _hash(raw)
    item = db.scalar(
        select(MobileRefreshToken)
        .where(
            MobileRefreshToken.token_hash == token_hash,
            MobileRefreshToken.device_id == device_id,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(status_code=401, detail="Refresh token invalid")
    if item.revoked_at:
        if item.replaced_by_id:
            _revoke_device_family(db, item.user_id, device_id, now)
            db.commit()
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")
    expires = item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        item.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")
    user = db.get(User, item.user_id)
    if not user or not user.is_active:
        item.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="User unavailable")
    try:
        new_raw, new_item = _new_refresh_token(db, user, device_id)
        item.revoked_at = now
        item.replaced_by_id = new_item.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Refresh token rotation conflict") from exc
    return {
        "access_token": create_access_token(user.id, user.role, 60),
        "refresh_token": new_raw,
        "token_type": "bearer",
        "expires_in": 3600,
    }


def register_device(
    db: Session,
    user: User,
    device_id: str,
    platform: str,
    push_token: str | None,
    app_version: str | None,
) -> MobileDevice:
    item = db.scalar(
        select(MobileDevice).where(
            MobileDevice.user_id == user.id,
            MobileDevice.device_id == device_id,
        )
    )
    if not item:
        item = MobileDevice(
            user_id=user.id,
            device_id=device_id,
            platform=platform,
            push_token=push_token,
            app_version=app_version,
        )
        db.add(item)
    else:
        item.platform = platform
        item.push_token = push_token
        item.app_version = app_version
        item.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


def send_mobile_push(
    db: Session,
    *,
    user_ids: list[str],
    title: str,
    body: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    devices = list(
        db.scalars(
            select(MobileDevice).where(
                MobileDevice.user_id.in_(user_ids),
                MobileDevice.push_token.is_not(None),
            )
        )
    )
    messages = [
        PushMessage(to=str(device.push_token), title=title, body=body, data=data)
        for device in devices
        if device.push_token
    ]
    try:
        tickets = send_expo_push(messages)
    except PushDeliveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    disabled_tokens: list[str] = []
    for device, ticket in zip(devices, tickets):
        details = ticket.get("details") if isinstance(ticket, dict) else None
        if ticket.get("status") == "error" and isinstance(details, dict) and details.get("error") == "DeviceNotRegistered":
            disabled_tokens.append(str(device.push_token))
            device.push_token = None
    db.commit()
    return {
        "target_devices": len(messages),
        "tickets": tickets,
        "disabled_tokens": disabled_tokens,
    }


def apply_mutation(
    db: Session,
    user: User,
    device_id: str,
    client_mutation_id: str,
    mutation_type: str,
    payload: dict,
) -> MobileMutation:
    existing = db.scalar(
        select(MobileMutation).where(
            MobileMutation.user_id == user.id,
            MobileMutation.device_id == device_id,
            MobileMutation.client_mutation_id == client_mutation_id,
        )
    )
    if existing:
        return existing
    result: dict[str, Any] = {"applied": True}
    if mutation_type == "favorite.add":
        property_id = payload.get("property_id")
        if not db.get(Property, property_id):
            raise HTTPException(status_code=404, detail="Property not found")
        if not db.scalar(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.property_id == property_id)
        ):
            db.add(Favorite(user_id=user.id, property_id=property_id))
        result["property_id"] = property_id
    elif mutation_type == "favorite.remove":
        item = db.scalar(
            select(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.property_id == payload.get("property_id"),
            )
        )
        if item:
            db.delete(item)
    elif mutation_type == "capture.metadata":
        required = {"capture_session_id", "metadata"}
        if not required.issubset(payload):
            raise HTTPException(status_code=422, detail="capture.metadata requires capture_session_id and metadata")
        result.update({"capture_session_id": payload["capture_session_id"], "queued": True})
    elif mutation_type == "analytics.event":
        if not payload.get("event"):
            raise HTTPException(status_code=422, detail="analytics.event requires event")
        result.update({"event": payload["event"], "accepted": True})
    else:
        raise HTTPException(status_code=422, detail="Unsupported mutation type")
    mutation = MobileMutation(
        user_id=user.id,
        device_id=device_id,
        client_mutation_id=client_mutation_id,
        mutation_type=mutation_type,
        payload_json=payload,
        status="applied",
        result_json=result,
    )
    db.add(mutation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(
            select(MobileMutation).where(
                MobileMutation.user_id == user.id,
                MobileMutation.device_id == device_id,
                MobileMutation.client_mutation_id == client_mutation_id,
            )
        )
        if duplicate:
            return duplicate
        raise
    db.refresh(mutation)
    return mutation


def revoke_mobile_tokens(
    db: Session,
    user: User,
    device_id: str,
    raw: str | None = None,
) -> int:
    base = select(MobileRefreshToken).where(
        MobileRefreshToken.user_id == user.id,
        MobileRefreshToken.device_id == device_id,
    )
    if raw:
        item = db.scalar(
            base.where(MobileRefreshToken.token_hash == _hash(raw)).with_for_update()
        )
        if not item:
            return 0
        if item.revoked_at is None:
            item.revoked_at = datetime.now(timezone.utc)
            db.commit()
        # Logout is idempotent: an already-revoked matching token is acknowledged.
        return 1
    count = 0
    now = datetime.now(timezone.utc)
    for item in db.scalars(
        base.where(MobileRefreshToken.revoked_at.is_(None)).with_for_update()
    ):
        item.revoked_at = now
        count += 1
    db.commit()
    return count
