from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import CRMConnection, CRMSyncEvent, AgentRoutingRule, Lead, User
from ..p1_schemas import CRMConnectionCreate, CRMConnectionRead, CRMSyncRead, RoutingRuleCreate, RoutingRuleRead
from ..services.crm import route_lead, sync_event, verify_crm_webhook
from ..services.jobs_p1 import enqueue_job
from ..services.secrets import seal_secret

router = APIRouter(tags=["crm"])


@router.get("/admin/crm/connections", response_model=list[CRMConnectionRead])
def connections(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return list(db.scalars(select(CRMConnection).order_by(CRMConnection.created_at.desc())))


@router.post("/admin/crm/connections", response_model=CRMConnectionRead, status_code=201)
def create_connection(payload: CRMConnectionCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    item = CRMConnection(
        agency_id=payload.agency_id, provider=payload.provider, base_url=payload.base_url,
        api_key_encrypted=seal_secret(payload.api_key), webhook_secret_encrypted=seal_secret(payload.webhook_secret),
        config_json=payload.config_json, active=payload.active,
    )
    db.add(item); db.commit(); db.refresh(item); return item


@router.patch("/admin/crm/connections/{connection_id}", response_model=CRMConnectionRead)
def update_connection(connection_id: str, payload: CRMConnectionCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    item = db.get(CRMConnection, connection_id)
    if not item: raise HTTPException(status_code=404, detail="CRM connection not found")
    values = payload.model_dump(exclude_unset=True)
    if "api_key" in values: item.api_key_encrypted = seal_secret(values.pop("api_key"))
    if "webhook_secret" in values: item.webhook_secret_encrypted = seal_secret(values.pop("webhook_secret"))
    for key, value in values.items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return item


@router.get("/admin/crm/routing-rules", response_model=list[RoutingRuleRead])
def routing_rules(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return list(db.scalars(select(AgentRoutingRule).order_by(AgentRoutingRule.priority)))


@router.post("/admin/crm/routing-rules", response_model=RoutingRuleRead, status_code=201)
def create_rule(payload: RoutingRuleCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    item = AgentRoutingRule(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item


@router.get("/admin/crm/sync-events", response_model=list[CRMSyncRead])
def sync_events(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    stmt = select(CRMSyncEvent)
    if status: stmt = stmt.where(CRMSyncEvent.status == status)
    return list(db.scalars(stmt.order_by(CRMSyncEvent.created_at.desc()).limit(200)))


@router.post("/admin/crm/sync-events/{event_id}/retry")
def retry_sync(event_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    event = db.get(CRMSyncEvent, event_id)
    if not event: raise HTTPException(status_code=404, detail="Sync event not found")
    event.status = "queued"; event.error = None
    job = enqueue_job(db, "crm_sync", {"sync_event_id": event.id}, idempotency_key=f"crm-retry:{event.id}:{event.attempts}")
    db.commit(); return {"job_id": job.id, "status": job.status}


@router.post("/admin/leads/{lead_id}/route")
def route(lead_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    lead = db.get(Lead, lead_id)
    if not lead: raise HTTPException(status_code=404, detail="Lead not found")
    agent = route_lead(db, lead); db.commit()
    return {"lead_id": lead.id, "assigned_agent_id": agent.id if agent else None}


@router.post("/webhooks/crm/{connection_id}", status_code=202)
async def crm_webhook(connection_id: str, request: Request, db: Session = Depends(get_db)):
    connection = db.get(CRMConnection, connection_id)
    if not connection: raise HTTPException(status_code=404, detail="Connection not found")
    body = await request.body()
    if not verify_crm_webhook(connection, body, request.headers.get("x-signature")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    # Inbound events are retained for replay; domain mutation is explicit and provider-specific.
    event = CRMSyncEvent(connection_id=connection.id, entity_type="webhook", local_id=request.headers.get("x-event-id", "unknown"), action="receive", direction="inbound", status="completed", idempotency_key=f"webhook:{connection.id}:{request.headers.get('x-event-id', hash(body))}", payload_json={"raw": body.decode(errors="replace")[:10000]})
    db.add(event); db.commit(); return {"accepted": True}
