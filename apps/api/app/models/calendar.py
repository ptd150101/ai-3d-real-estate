from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class AgentAvailabilityRule(Base, TimestampMixin):
    __tablename__ = "agent_availability_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=60)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("agent_id", "weekday", "start_minute", "end_minute", name="uq_agent_availability_rule"),)


class AgentAvailabilityException(Base, TimestampMixin):
    __tablename__ = "agent_availability_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(300))


class AppointmentSlot(Base, TimestampMixin):
    __tablename__ = "appointment_slots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="available", index=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"), unique=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("agent_id", "start_at", name="uq_agent_slot_start"),)


class CalendarConnection(Base, TimestampMixin):
    __tablename__ = "calendar_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    account_email: Mapped[str | None] = mapped_column(String(320))
    external_calendar_id: Mapped[str | None] = mapped_column(String(300))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)


class CalendarSyncEvent(Base, TimestampMixin):
    __tablename__ = "calendar_sync_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("calendar_connections.id", ondelete="CASCADE"), index=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"), index=True)
    direction: Mapped[str] = mapped_column(String(16), default="outbound")
    external_event_id: Mapped[str | None] = mapped_column(String(300), index=True)
    action: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
