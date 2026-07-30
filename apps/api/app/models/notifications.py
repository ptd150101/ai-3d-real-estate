from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class NotificationPreference(Base, TimestampMixin):
    __tablename__ = "notification_preferences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    zalo_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    categories_json: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh")
    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class NotificationDelivery(Base, TimestampMixin):
    __tablename__ = "notification_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(ForeignKey("notification_events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="local")
    recipient: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    idempotency_key: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(256), index=True)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)


class NotificationTemplate(Base, TimestampMixin):
    __tablename__ = "notification_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    locale: Mapped[str] = mapped_column(String(16), default="vi")
    subject_template: Mapped[str | None] = mapped_column(String(300))
    body_template: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("event_type", "channel", "locale", name="uq_notification_template"),)


class NotificationUnsubscribe(Base):
    __tablename__ = "notification_unsubscribes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(24), index=True)
    event_type: Mapped[str | None] = mapped_column(String(120), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedSearchSubscription(Base, TimestampMixin):
    __tablename__ = "saved_search_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    saved_search_id: Mapped[str] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"), unique=True, index=True)
    frequency: Mapped[str] = mapped_column(String(24), default="daily", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notify_price_drop: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class SavedSearchMatch(Base):
    __tablename__ = "saved_search_matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    saved_search_id: Mapped[str] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    match_score: Mapped[int] = mapped_column(Integer, default=100)
    current_price: Mapped[int | None] = mapped_column(BigInteger)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (UniqueConstraint("saved_search_id", "property_id", name="uq_saved_search_match"),)
