from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class AgentReview(Base, TimestampMixin):
    __tablename__ = "agent_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    communication_rating: Mapped[int] = mapped_column(Integer)
    knowledge_rating: Mapped[int] = mapped_column(Integer)
    responsiveness_rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="published", index=True)
    edited_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewResponse(Base, TimestampMixin):
    __tablename__ = "review_responses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(ForeignKey("agent_reviews.id", ondelete="CASCADE"), unique=True)
    agent_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)


class ReviewReport(Base, TimestampMixin):
    __tablename__ = "review_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(ForeignKey("agent_reviews.id", ondelete="CASCADE"), index=True)
    reporter_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(120))
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("review_id", "reporter_user_id", name="uq_review_reporter"),)
