from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class LegalDocumentVersion(Base, TimestampMixin):
    __tablename__ = "legal_document_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_document_id: Mapped[str] = mapped_column(ForeignKey("property_documents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(1024))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(120), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    uploaded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("property_document_id", "version_number", name="uq_legal_document_version"),)


class LegalDocumentReview(Base, TimestampMixin):
    __tablename__ = "legal_document_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(ForeignKey("legal_document_versions.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LegalDocumentReviewEvent(Base):
    __tablename__ = "legal_document_review_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(ForeignKey("legal_document_versions.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DocumentAccessGrant(Base, TimestampMixin):
    __tablename__ = "document_access_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(ForeignKey("legal_document_versions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    max_downloads: Mapped[int] = mapped_column(Integer, default=1)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentDownloadLog(Base):
    __tablename__ = "document_download_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grant_id: Mapped[str] = mapped_column(ForeignKey("document_access_grants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    watermarked: Mapped[bool] = mapped_column(Boolean, default=False)
