from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class AnalyticsSession(Base, TimestampMixin):
    __tablename__ = "analytics_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    anonymous_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    consent: Mapped[str] = mapped_column(String(32), default="essential")
    device_class: Mapped[str | None] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("analytics_sessions.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    event_name: Mapped[str] = mapped_column(String(120), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(220), unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class DailyFunnelMetric(Base):
    __tablename__ = "daily_funnel_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("metric_date", "metric_name", name="uq_daily_funnel_metric"),)


class DailyPropertyMetric(Base):
    __tablename__ = "daily_property_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    viewer_starts: Mapped[int] = mapped_column(Integer, default=0)
    panorama_starts: Mapped[int] = mapped_column(Integer, default=0)
    chat_starts: Mapped[int] = mapped_column(Integer, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    appointments: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("metric_date", "property_id", name="uq_daily_property_metric"),)


class DailyAgentMetric(Base):
    __tablename__ = "daily_agent_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    leads_assigned: Mapped[int] = mapped_column(Integer, default=0)
    messages_received: Mapped[int] = mapped_column(Integer, default=0)
    appointments_completed: Mapped[int] = mapped_column(Integer, default=0)
    response_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("metric_date", "agent_id", name="uq_daily_agent_metric"),)


class AIQualityEvaluation(Base, TimestampMixin):
    __tablename__ = "ai_quality_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True)
    evaluator_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    answer_helpful: Mapped[int | None] = mapped_column(Integer)
    citation_coverage: Mapped[float] = mapped_column(Float, default=0)
    handoff_required: Mapped[int] = mapped_column(Integer, default=0)
    unanswered: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000))
