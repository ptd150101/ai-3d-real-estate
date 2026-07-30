from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Agent,
    AgentCapacityState,
    AgentRoutingRule,
    CRMConnection,
    CRMEntityMapping,
    CRMSyncEvent,
    Lead,
    LeadAssignmentHistory,
    Property,
)
from .jobs_p1 import enqueue_job
from .notification import emit_event
from .secrets import unseal_secret


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def conditions_match(rule: AgentRoutingRule, lead: Lead, property_obj: Property | None) -> bool:
    conditions = rule.conditions_json or {}
    if conditions.get("district") and (not property_obj or property_obj.district not in conditions["district"]):
        return False
    if conditions.get("property_type") and (not property_obj or property_obj.property_type not in conditions["property_type"]):
        return False
    if conditions.get("min_price") and (not property_obj or property_obj.price < int(conditions["min_price"])):
        return False
    if conditions.get("max_price") and (not property_obj or property_obj.price > int(conditions["max_price"])):
        return False
    if conditions.get("source") and lead.source not in conditions["source"]:
        return False
    return True


def eligible_agents(db: Session, agency_id: str | None = None) -> list[tuple[Agent, AgentCapacityState]]:
    stmt = select(Agent).where(Agent.verified.is_(True))
    if agency_id:
        stmt = stmt.where(Agent.agency_id == agency_id)
    agents = list(db.scalars(stmt))
    output: list[tuple[Agent, AgentCapacityState]] = []
    for agent in agents:
        capacity = db.scalar(select(AgentCapacityState).where(AgentCapacityState.agent_id == agent.id))
        if not capacity:
            capacity = AgentCapacityState(agent_id=agent.id)
            db.add(capacity)
            db.flush()
        if capacity.online and capacity.open_leads < capacity.max_open_leads and (not capacity.paused_until or capacity.paused_until < utcnow()):
            output.append((agent, capacity))
    return output


def route_lead(db: Session, lead: Lead) -> Agent | None:
    property_obj = db.get(Property, lead.property_id) if lead.property_id else None
    if property_obj and property_obj.agent_id:
        agent = db.get(Agent, property_obj.agent_id)
        if agent:
            reason = "Listing owner"
            return assign_lead(db, lead, agent, None, reason)
    rules = list(db.scalars(select(AgentRoutingRule).where(AgentRoutingRule.active.is_(True)).order_by(AgentRoutingRule.priority.asc())))
    for rule in rules:
        if not conditions_match(rule, lead, property_obj):
            continue
        if rule.target_agent_id:
            agent = db.get(Agent, rule.target_agent_id)
            if agent:
                return assign_lead(db, lead, agent, rule, f"Rule {rule.name}: target agent")
        candidates = eligible_agents(db, rule.agency_id)
        if not candidates:
            continue
        if rule.strategy == "least_loaded":
            agent, _ = min(candidates, key=lambda item: (item[1].open_leads, item[1].last_assigned_at or datetime.min.replace(tzinfo=timezone.utc)))
        else:
            agent, _ = min(candidates, key=lambda item: item[1].last_assigned_at or datetime.min.replace(tzinfo=timezone.utc))
        return assign_lead(db, lead, agent, rule, f"Rule {rule.name}: {rule.strategy}")
    candidates = eligible_agents(db)
    if candidates:
        agent, _ = min(candidates, key=lambda item: (item[1].open_leads, item[1].last_assigned_at or datetime.min.replace(tzinfo=timezone.utc)))
        return assign_lead(db, lead, agent, None, "Default least-loaded routing")
    return None


def assign_lead(db: Session, lead: Lead, agent: Agent, rule: AgentRoutingRule | None, reason: str) -> Agent:
    previous = lead.assigned_agent_id
    lead.assigned_agent_id = agent.id
    state = db.scalar(select(AgentCapacityState).where(AgentCapacityState.agent_id == agent.id))
    if not state:
        state = AgentCapacityState(agent_id=agent.id)
        db.add(state)
    if previous != agent.id:
        state.open_leads += 1
    state.last_assigned_at = utcnow()
    db.add(LeadAssignmentHistory(lead_id=lead.id, agent_id=agent.id, rule_id=rule.id if rule else None, reason=reason))
    if agent.user_id:
        emit_event(
            db,
            event_type="lead.assigned",
            aggregate_type="lead",
            aggregate_id=lead.id,
            recipients=[agent.user_id],
            payload={"lead_name": lead.full_name, "lead_id": lead.id},
            idempotency_key=f"lead.assigned:{lead.id}:{agent.id}",
        )
    connections = list(db.scalars(select(CRMConnection).where(CRMConnection.active.is_(True))))
    for connection in connections:
        event = CRMSyncEvent(
            connection_id=connection.id,
            entity_type="lead",
            local_id=lead.id,
            action="upsert",
            idempotency_key=f"crm:{connection.id}:lead:{lead.id}:upsert:{lead.updated_at.isoformat() if lead.updated_at else 'new'}",
            payload_json={
                "id": lead.id, "name": lead.full_name, "phone": lead.phone, "email": lead.email,
                "message": lead.message, "source": lead.source, "status": lead.status,
                "assigned_agent_id": agent.id,
            },
        )
        db.add(event)
        db.flush()
        enqueue_job(db, "crm_sync", {"sync_event_id": event.id}, idempotency_key=f"crm-job:{event.id}")
    return agent


def sync_event(db: Session, event_id: str) -> dict[str, Any]:
    event = db.get(CRMSyncEvent, event_id)
    if not event:
        return {"status": "missing"}
    if event.status == "completed":
        return event.response_json or {"status": "completed"}
    connection = db.get(CRMConnection, event.connection_id)
    if not connection or not connection.active:
        raise ValueError("CRM connection is disabled")
    event.attempts += 1
    if connection.provider == "local" or not connection.base_url:
        response = {"external_id": f"local-{event.entity_type}-{event.local_id}", "provider": "local"}
    else:
        headers = {"Content-Type": "application/json", "Idempotency-Key": event.idempotency_key}
        if connection.api_key_encrypted:
            headers["Authorization"] = f"Bearer {unseal_secret(connection.api_key_encrypted)}"
        result = httpx.post(connection.base_url, json=event.payload_json, headers=headers, timeout=20)
        result.raise_for_status()
        response = result.json() if result.content else {"status": "accepted"}
    external_id = str(response.get("external_id") or response.get("id") or f"{connection.provider}-{event.local_id}")
    mapping = db.scalar(select(CRMEntityMapping).where(
        CRMEntityMapping.connection_id == connection.id,
        CRMEntityMapping.entity_type == event.entity_type,
        CRMEntityMapping.local_id == event.local_id,
    ))
    if mapping:
        mapping.external_id = external_id
    else:
        db.add(CRMEntityMapping(connection_id=connection.id, entity_type=event.entity_type, local_id=event.local_id, external_id=external_id))
    event.response_json = response
    event.status = "completed"
    event.synced_at = utcnow()
    event.error = None
    db.commit()
    return response


def verify_crm_webhook(connection: CRMConnection, raw_body: bytes, signature: str | None) -> bool:
    if not connection.webhook_secret_encrypted:
        return True
    if not signature:
        return False
    secret = unseal_secret(connection.webhook_secret_encrypted) or ""
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
