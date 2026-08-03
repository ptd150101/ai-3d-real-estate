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
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
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
from .signature_providers import (
    InvalidSignatureWebhook,
    SignatureProviderConfigurationError,
    SignatureProviderRequestError,
    get_signature_provider,
)
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
    document = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    document.setFont(font, 16)
    document.drawString(48, height - 60, title)
    document.setFont(font, 10)
    y = height - 90
    for paragraph in body.replace("<br>", "\n").replace("<p>", "").replace("</p>", "\n").splitlines():
        words = paragraph.split()
        line = ""
        for word in words:
            if document.stringWidth(line + " " + word, font, 10) > width - 96:
                document.drawString(48, y, line)
                y -= 15
                line = word
            else:
                line = (line + " " + word).strip()
        if line:
            document.drawString(48, y, line)
            y -= 15
        if y < 60:
            document.showPage()
            document.setFont(font, 10)
            y = height - 60
    document.save()
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


def _normalize_participants(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
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
        normalized.append(
            {
                "user_id": user_id,
                "email": email,
                "name": participant.get("name") or email,
                "role": participant.get("role", "signer"),
                "signing_order": signing_order,
                "anchor": participant.get("anchor") or "[[SIGN_HERE]]",
            }
        )
    return normalized


def create_envelope(
    db: Session,
    *,
    organization_id: str,
    template: ContractTemplate,
    reservation_order_id: str | None,
    data: dict[str, Any],
    participants: list[dict[str, Any]],
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
    normalized = _normalize_participants(participants)

    content = template.content_html
    for field in template.allowed_fields_json:
        content = content.replace("{{" + field + "}}", str(data.get(field, "")))
    pdf = _render_pdf(template.name, content)
    checksum = hashlib.sha256(pdf).hexdigest()
    envelope = ContractEnvelope(
        organization_id=organization_id,
        template_id=template.id,
        reservation_order_id=reservation_order_id,
        status="creating",
        provider=provider,
        document_checksum=checksum,
        data_json=dict(data),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(envelope)
    db.flush()
    storage_key, _, _ = save_private_bytes(pdf, f"{envelope.id}.pdf", "contracts", "application/pdf")
    envelope.document_url = storage_key

    rows: list[ContractParticipant] = []
    for participant in normalized:
        row = ContractParticipant(
            envelope_id=envelope.id,
            user_id=participant["user_id"],
            email=participant["email"],
            role=participant["role"],
            signing_order=participant["signing_order"],
            status="pending",
        )
        db.add(row)
        rows.append(row)
    db.flush()

    try:
        adapter = get_signature_provider(provider)
        provider_result = adapter.create_envelope(
            document_name=f"{template.name}.pdf",
            document_bytes=pdf,
            subject=template.name,
            participants=[
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "email": row.email,
                    "name": next(item["name"] for item in normalized if item["email"] == row.email),
                    "signing_order": row.signing_order,
                    "anchor": next(item["anchor"] for item in normalized if item["email"] == row.email),
                }
                for row in rows
            ],
            metadata={
                "nestora_envelope_id": envelope.id,
                "organization_id": organization_id,
                "reservation_order_id": reservation_order_id,
                "document_checksum": checksum,
            },
        )
    except SignatureProviderConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SignatureProviderRequestError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    provider_meta = {
        "name": adapter.name,
        "envelope_id": provider_result.envelope_id,
        "status": provider_result.status,
    }
    envelope.provider = adapter.name
    envelope.status = "sent"
    envelope.data_json = {**envelope.data_json, "_signature_provider": provider_meta}
    db.commit()
    db.refresh(envelope)
    return envelope


def create_provider_signing_view(
    db: Session,
    *,
    envelope: ContractEnvelope,
    participant: ContractParticipant,
) -> str:
    provider_meta = (envelope.data_json or {}).get("_signature_provider") or {}
    provider_name = str(provider_meta.get("name") or envelope.provider)
    provider_envelope_id = str(provider_meta.get("envelope_id") or "")
    if provider_name == "local":
        raise HTTPException(status_code=409, detail="Local signing uses a Nestora signing token")
    if not provider_envelope_id:
        raise HTTPException(status_code=409, detail="Provider envelope id is unavailable")
    settings = get_settings()
    try:
        result = get_signature_provider(provider_name).create_recipient_view(
            provider_envelope_id=provider_envelope_id,
            participant={
                "id": participant.id,
                "user_id": participant.user_id,
                "email": participant.email,
                "name": participant.email,
            },
            return_url=settings.docusign_return_url
            or f"{settings.site_url}/agency/contracts?envelope_id={envelope.id}",
        )
    except SignatureProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SignatureProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result.url


def record_signature(
    db: Session,
    *,
    envelope: ContractEnvelope,
    participant: ContractParticipant,
    provider_event_id: str,
    metadata: dict[str, Any],
) -> ContractEnvelope:
    envelope = db.scalar(
        select(ContractEnvelope).where(ContractEnvelope.id == envelope.id).with_for_update()
    )
    participant = db.scalar(
        select(ContractParticipant).where(ContractParticipant.id == participant.id).with_for_update()
    )
    if not envelope or not participant:
        raise HTTPException(status_code=404, detail="Envelope or participant not found")
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
            event_at=now,
            metadata_json=metadata,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.get(ContractEnvelope, envelope.id)

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
        events = list(
            db.scalars(
                select(SignatureEvent)
                .where(SignatureEvent.envelope_id == envelope.id)
                .order_by(SignatureEvent.event_at)
            )
        )
        evidence = {
            "envelope_id": envelope.id,
            "document_checksum": envelope.document_checksum,
            "completed_at": envelope.completed_at.isoformat(),
            "provider": envelope.provider,
            "events": [
                {
                    "id": event.id,
                    "type": event.event_type,
                    "provider_event_id": event.provider_event_id,
                    "event_at": event.event_at.isoformat(),
                    "metadata": event.metadata_json,
                }
                for event in events
            ],
        }
        evidence_checksum = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        existing_evidence = db.scalar(
            select(SignatureEvidence).where(SignatureEvidence.envelope_id == envelope.id)
        )
        if not existing_evidence:
            db.add(
                SignatureEvidence(
                    envelope_id=envelope.id,
                    checksum=evidence_checksum,
                    evidence_json=evidence,
                    object_url=envelope.document_url,
                )
            )
    db.commit()
    db.refresh(envelope)
    return envelope


def process_provider_webhook(
    db: Session,
    *,
    provider: str,
    raw_body: bytes,
    payload: dict[str, Any],
    signature: str,
) -> dict[str, Any]:
    try:
        events = get_signature_provider(provider).parse_webhook(
            raw_body=raw_body,
            payload=payload,
            signature=signature,
        )
    except SignatureProviderConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidSignatureWebhook as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    processed = 0
    ignored = 0
    for event in events:
        envelope = next(
            (
                item
                for item in db.scalars(
                    select(ContractEnvelope)
                    .where(ContractEnvelope.provider == provider)
                    .order_by(ContractEnvelope.created_at.desc())
                    .limit(500)
                )
                if ((item.data_json or {}).get("_signature_provider") or {}).get("envelope_id")
                == event.envelope_id
            ),
            None,
        )
        if not envelope:
            ignored += 1
            continue
        participant = None
        if event.recipient_id:
            participant = db.get(ContractParticipant, event.recipient_id)
            if participant and participant.envelope_id != envelope.id:
                participant = None
        if not participant and event.email:
            participant = db.scalar(
                select(ContractParticipant).where(
                    ContractParticipant.envelope_id == envelope.id,
                    ContractParticipant.email == event.email.lower(),
                )
            )
        if not participant or event.status != "signed":
            ignored += 1
            continue
        record_signature(
            db,
            envelope=envelope,
            participant=participant,
            provider_event_id=event.event_id,
            metadata={"provider": provider, "payload": event.payload},
        )
        processed += 1
    return {"processed": processed, "ignored": ignored}


def expire_and_remind(db: Session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    expired = 0
    reminders = 0
    for envelope in db.scalars(
        select(ContractEnvelope).where(ContractEnvelope.status == "sent").with_for_update(skip_locked=True)
    ):
        exp = envelope.expires_at
        if exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) <= now:
            envelope.status = "expired"
            expired += 1
        elif exp and (exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)) - now < timedelta(hours=24):
            reminders += 1
    db.commit()
    return {"expired": expired, "reminders": reminders}
