from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ContractEnvelope,
    ContractParticipant,
    ContractTemplate,
    LegalDocumentPolicy,
    SignatureEvent,
    SignatureEvidence,
)
from ..security import create_scoped_token, decode_scoped_token
from .storage import save_private_bytes

SIGNING_TOKEN_SCOPE = "contract-sign"


def _render_pdf(title: str, body: str) -> bytes:
    buffer = io.BytesIO()
    font = "Helvetica"
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]:
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont("NestoraUnicode", candidate))
                font = "NestoraUnicode"
                break
            except Exception:
                pass
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont(font, 16)
    c.drawString(48, height - 60, title)
    c.setFont(font, 10)
    y = height - 90
    for paragraph in body.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n").splitlines():
        words = paragraph.split()
        line = ""
        for word in words:
            if c.stringWidth(line + " " + word, font, 10) > width - 96:
                c.drawString(48, y, line)
                y -= 15
                line = word
            else:
                line = (line + " " + word).strip()
        if line:
            c.drawString(48, y, line)
            y -= 15
        if y < 60:
            c.showPage()
            c.setFont(font, 10)
            y = height - 60
    c.save()
    return buffer.getvalue()


def issue_signing_token(envelope: ContractEnvelope, participant: ContractParticipant) -> tuple[str, datetime]:
    settings = get_settings()
    token = create_scoped_token(
        SIGNING_TOKEN_SCOPE,
        {
            "envelope_id": envelope.id,
            "participant_id": participant.id,
            "participant_user_id": participant.user_id,
            "participant_email": participant.email.lower(),
        },
        expires_minutes=settings.document_signing_ttl_minutes,
    )
    claims = decode_scoped_token(token, SIGNING_TOKEN_SCOPE)
    return token, datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)


def verify_signing_token(token: str, *, envelope_id: str, participant_id: str) -> dict[str, Any]:
    try:
        claims = decode_scoped_token(token, SIGNING_TOKEN_SCOPE)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired signing token") from exc
    if claims.get("envelope_id") != envelope_id or claims.get("participant_id") != participant_id:
        raise HTTPException(status_code=403, detail="Signing token does not match participant")
    if not claims.get("jti"):
        raise HTTPException(status_code=401, detail="Signing token is missing replay protection")
    return claims


def create_envelope(
    db: Session,
    *,
    organization_id: str,
    template: ContractTemplate,
    reservation_order_id: str | None,
    data: dict,
    participants: list[dict],
    provider: str = "local",
) -> ContractEnvelope:
    policy = db.scalar(
        select(LegalDocumentPolicy).where(
            LegalDocumentPolicy.document_type == template.document_type,
            LegalDocumentPolicy.jurisdiction == "VN",
        )
    )
    if not policy or not policy.approved:
        raise HTTPException(status_code=409, detail="Document type has not passed legal approval")

    normalized_participants: list[dict[str, Any]] = []
    identities: set[tuple[str | None, str]] = set()
    for index, participant in enumerate(participants, 1):
        email = str(participant.get("email", "")).strip().lower()
        if not email:
            raise HTTPException(status_code=422, detail="Every participant requires an email")
        user_id = participant.get("user_id")
        identity = (user_id, email)
        if identity in identities:
            raise HTTPException(status_code=422, detail="Duplicate contract participant")
        identities.add(identity)
        signing_order = int(participant.get("signing_order", index))
        if signing_order < 1:
            raise HTTPException(status_code=422, detail="Signing order must be positive")
        normalized_participants.append(
            {
                "user_id": user_id,
                "email": email,
                "role": participant.get("role", "signer"),
                "signing_order": signing_order,
            }
        )

    content = template.content_html
    for field in template.allowed_fields_json:
        content = content.replace("{{" + field + "}}", str(data.get(field, "")))
    pdf = _render_pdf(template.name, content)
    checksum = hashlib.sha256(pdf).hexdigest()
    envelope = ContractEnvelope(
        organization_id=organization_id,
        template_id=template.id,
        reservation_order_id=reservation_order_id,
        status="sent",
        provider=provider,
        document_checksum=checksum,
        data_json=data,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(envelope)
    db.flush()

    storage_key, _, _ = save_private_bytes(
        pdf,
        f"{envelope.id}.pdf",
        "contracts",
        "application/pdf",
    )
    envelope.document_url = storage_key
    for participant in normalized_participants:
        db.add(ContractParticipant(envelope_id=envelope.id, status="pending", **participant))
    db.commit()
    db.refresh(envelope)
    return envelope


def record_signature(
    db: Session,
    *,
    envelope: ContractEnvelope,
    participant: ContractParticipant,
    provider_event_id: str,
    metadata: dict,
) -> ContractEnvelope:
    locked_envelope = db.scalar(
        select(ContractEnvelope).where(ContractEnvelope.id == envelope.id).with_for_update()
    )
    locked_participant = db.scalar(
        select(ContractParticipant).where(ContractParticipant.id == participant.id).with_for_update()
    )
    if not locked_envelope or not locked_participant:
        raise HTTPException(status_code=404, detail="Envelope or participant not found")
    envelope = locked_envelope
    participant = locked_participant

    if db.scalar(select(SignatureEvent).where(SignatureEvent.provider_event_id == provider_event_id)):
        return envelope
    if participant.status == "signed":
        return envelope
    if envelope.status in {"completed", "voided", "expired"}:
        raise HTTPException(status_code=409, detail=f"Envelope cannot be signed in status {envelope.status}")

    now = datetime.now(timezone.utc)
    expires_at = envelope.expires_at
    if expires_at and (expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)) <= now:
        envelope.status = "expired"
        db.commit()
        raise HTTPException(status_code=409, detail="Envelope has expired")

    earlier_pending = db.scalar(
        select(ContractParticipant)
        .where(
            ContractParticipant.envelope_id == envelope.id,
            ContractParticipant.signing_order < participant.signing_order,
            ContractParticipant.status != "signed",
        )
        .limit(1)
    )
    if earlier_pending:
        raise HTTPException(status_code=409, detail="A previous signer must complete first")

    participant.status = "signed"
    participant.signed_at = now
    db.add(
        SignatureEvent(
            envelope_id=envelope.id,
            participant_id=participant.id,
            event_type="signed",
            provider_event_id=provider_event_id,
            event_at=participant.signed_at,
            metadata_json=metadata,
        )
    )
    db.flush()

    pending = db.scalar(
        select(ContractParticipant)
        .where(
            ContractParticipant.envelope_id == envelope.id,
            ContractParticipant.status != "signed",
        )
        .limit(1)
    )
    if not pending:
        envelope.status = "completed"
        envelope.completed_at = now
        evidence = {
            "envelope_id": envelope.id,
            "document_checksum": envelope.document_checksum,
            "completed_at": envelope.completed_at.isoformat(),
            "events": [
                {
                    "id": event.id,
                    "type": event.event_type,
                    "provider_event_id": event.provider_event_id,
                    "event_at": event.event_at.isoformat(),
                }
                for event in db.scalars(
                    select(SignatureEvent)
                    .where(SignatureEvent.envelope_id == envelope.id)
                    .order_by(SignatureEvent.event_at)
                )
            ],
        }
        checksum = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        db.add(
            SignatureEvidence(
                envelope_id=envelope.id,
                checksum=checksum,
                evidence_json=evidence,
                object_url=envelope.document_url,
            )
        )
    db.commit()
    db.refresh(envelope)
    return envelope


def expire_and_remind(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    expired = 0
    reminders = 0
    for envelope in db.scalars(select(ContractEnvelope).where(ContractEnvelope.status == "sent")):
        exp = envelope.expires_at
        if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) <= now:
            envelope.status = "expired"
            expired += 1
        elif exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) - now < timedelta(hours=24):
            reminders += 1
    db.commit()
    return {"expired": expired, "reminders": reminders}
