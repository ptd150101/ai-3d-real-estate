from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    DocumentAccessGrant,
    DocumentDownloadLog,
    LegalDocumentReview,
    LegalDocumentReviewEvent,
    LegalDocumentVersion,
    PropertyDocument,
    User,
)
from .notification import emit_event


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_version(db: Session, user: User, payload) -> LegalDocumentVersion:
    document = db.get(PropertyDocument, payload.property_document_id)
    if not document:
        raise ValueError("Property document not found")
    next_version = int(db.scalar(select(func.coalesce(func.max(LegalDocumentVersion.version_number), 0)).where(LegalDocumentVersion.property_document_id == document.id)) or 0) + 1
    item = LegalDocumentVersion(version_number=next_version, uploaded_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(LegalDocumentReviewEvent(version_id=item.id, actor_user_id=user.id, action="uploaded", from_status=None, to_status="pending_review"))
    return item


def review_version(db: Session, version: LegalDocumentVersion, reviewer: User, decision: str, notes: str | None) -> LegalDocumentVersion:
    if reviewer.role not in {"admin", "legal_reviewer"}:
        raise PermissionError("Legal reviewer role required")
    previous = version.status
    db.add(LegalDocumentReview(version_id=version.id, reviewer_user_id=reviewer.id, decision=decision, notes=notes))
    version.status = decision
    if decision == "approved":
        db.query(LegalDocumentVersion).filter(
            LegalDocumentVersion.property_document_id == version.property_document_id,
            LegalDocumentVersion.id != version.id,
        ).update({"active": False}, synchronize_session=False)
        version.active = True
        document = db.get(PropertyDocument, version.property_document_id)
        if document:
            document.verified = True
            document.url = version.source_url or document.url
    else:
        version.active = False
    db.add(LegalDocumentReviewEvent(version_id=version.id, actor_user_id=reviewer.id, action="reviewed", from_status=previous, to_status=decision, metadata_json={"notes": notes}))
    return version


def create_grant(db: Session, actor: User, payload) -> tuple[DocumentAccessGrant, str]:
    version = db.get(LegalDocumentVersion, payload.version_id)
    if not version or version.status != "approved" or not version.active:
        raise ValueError("Only active approved document versions can be shared")
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    grant = DocumentAccessGrant(
        version_id=version.id,
        user_id=payload.user_id,
        agent_id=payload.agent_id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(minutes=payload.expires_minutes),
        max_downloads=payload.max_downloads,
    )
    db.add(grant)
    db.flush()
    recipients: list[str] = []
    if payload.user_id:
        recipients.append(payload.user_id)
    if recipients:
        document = db.get(PropertyDocument, version.property_document_id)
        emit_event(
            db,
            event_type="legal_document.shared",
            aggregate_type="legal_document_version",
            aggregate_id=version.id,
            recipients=recipients,
            payload={"document_title": document.title if document else "tài liệu pháp lý", "grant_id": grant.id},
            idempotency_key=f"legal.shared:{grant.id}",
            actor_user_id=actor.id,
        )
    return grant, raw_token


def validate_grant(db: Session, raw_token: str, current_user_id: str | None = None) -> tuple[DocumentAccessGrant, LegalDocumentVersion]:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    grant = db.scalar(select(DocumentAccessGrant).where(DocumentAccessGrant.token_hash == token_hash))
    if not grant:
        raise ValueError("Invalid document grant")
    now = utcnow()
    expires = grant.expires_at if grant.expires_at.tzinfo else grant.expires_at.replace(tzinfo=timezone.utc)
    if grant.revoked_at or expires <= now or grant.download_count >= grant.max_downloads:
        raise ValueError("Document grant has expired")
    if grant.user_id and grant.user_id != current_user_id:
        raise PermissionError("Grant does not belong to this user")
    version = db.get(LegalDocumentVersion, grant.version_id)
    if not version or version.status != "approved" or not version.active:
        raise ValueError("Document is no longer active")
    if version.valid_from:
        start = version.valid_from if version.valid_from.tzinfo else version.valid_from.replace(tzinfo=timezone.utc)
        if start > now:
            raise ValueError("Document is not active yet")
    if version.valid_until:
        end = version.valid_until if version.valid_until.tzinfo else version.valid_until.replace(tzinfo=timezone.utc)
        if end < now:
            raise ValueError("Document has expired")
    return grant, version


def record_download(db: Session, grant: DocumentAccessGrant, user_id: str | None, ip: str | None, user_agent: str | None, watermarked: bool) -> None:
    grant.download_count += 1
    db.add(DocumentDownloadLog(grant_id=grant.id, user_id=user_id, ip_address=ip, user_agent=user_agent, watermarked=watermarked))


def resolve_document_url(version: LegalDocumentVersion) -> str:
    # Storage remains private in production. The API streams local files or redirects to a provider-signed URL.
    return version.source_url or version.storage_key


def approved_version_ids_for_rag(db: Session, property_document_ids: list[str]) -> set[str]:
    return set(db.scalars(select(LegalDocumentVersion.property_document_id).where(
        LegalDocumentVersion.property_document_id.in_(property_document_ids),
        LegalDocumentVersion.status == "approved",
        LegalDocumentVersion.active.is_(True),
    )))


def watermark_pdf(data: bytes, label: str) -> tuple[bytes, bool]:
    """Apply a diagonal audit watermark. Returns original data if the input is not a readable PDF."""
    try:
        import io
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        try:
            pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")); watermark_font="DejaVu"
        except Exception:
            watermark_font="Helvetica"
        reader = PdfReader(io.BytesIO(data)); writer = PdfWriter()
        for page in reader.pages:
            width = float(page.mediabox.width); height = float(page.mediabox.height)
            overlay_buffer = io.BytesIO(); c = canvas.Canvas(overlay_buffer, pagesize=(width, height))
            c.saveState(); c.setFillAlpha(0.14); c.setFont(watermark_font, 14); c.translate(width/2, height/2); c.rotate(35)
            c.drawCentredString(0, 0, label[:180]); c.restoreState(); c.save()
            overlay_buffer.seek(0); overlay = PdfReader(overlay_buffer).pages[0]
            page.merge_page(overlay); writer.add_page(page)
        output = io.BytesIO(); writer.write(output); return output.getvalue(), True
    except Exception:
        return data, False
