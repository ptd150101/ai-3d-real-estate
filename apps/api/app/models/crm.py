from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class CRMConnection(Base, TimestampMixin):
    __tablename__ = "crm_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agency_id: Mapped[str | None] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    base_url: Mapped[str | None] = mapped_column(String(1024))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class CRMEntityMapping(Base, TimestampMixin):
    __tablename__ = "crm_entity_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    local_id: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(300), index=True)
    __table_args__ = (UniqueConstraint("connection_id", "entity_type", "local_id", name="uq_crm_local_mapping"), UniqueConstraint("connection_id", "entity_type", "external_id", name="uq_crm_external_mapping"))


class CRMSyncEvent(Base, TimestampMixin):
    __tablename__ = "crm_sync_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(ForeignKey("crm_connections.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    local_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(48))
    direction: Mapped[str] = mapped_column(String(16), default="outbound")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRoutingRule(Base, TimestampMixin):
    __tablename__ = "agent_routing_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agency_id: Mapped[str | None] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    strategy: Mapped[str] = mapped_column(String(48), default="round_robin")
    target_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class AgentCapacityState(Base, TimestampMixin):
    __tablename__ = "agent_capacity_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), unique=True, index=True)
    max_open_leads: Mapped[int] = mapped_column(Integer, default=30)
    open_leads: Mapped[int] = mapped_column(Integer, default=0)
    online: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class LeadAssignmentHistory(Base):
    __tablename__ = "lead_assignment_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("agent_routing_rules.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(500))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
