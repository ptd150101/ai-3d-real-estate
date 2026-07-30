from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Appointment, CalendarConnection, CalendarSyncEvent, Property
from .jobs_p1 import enqueue_job
from .secrets import unseal_secret


class CalendarProvider(Protocol):
    def upsert_event(self, connection: CalendarConnection, appointment: Appointment, property_obj: Property | None) -> dict[str, Any]: ...
    def delete_event(self, connection: CalendarConnection, external_event_id: str) -> dict[str, Any]: ...


class LocalICSProvider:
    def upsert_event(self, connection, appointment, property_obj):
        return {"external_event_id": f"ics-{appointment.id}", "status": "synced"}
    def delete_event(self, connection, external_event_id):
        return {"external_event_id": external_event_id, "status": "deleted"}


class HTTPProvider:
    def upsert_event(self, connection, appointment, property_obj):
        endpoint = (connection.config_json or {}).get("events_endpoint")
        if not endpoint:
            return {"external_event_id": f"{connection.provider}-{appointment.id}", "status": "simulated"}
        token = unseal_secret(connection.access_token_encrypted)
        response = httpx.post(endpoint, json={"appointment_id": appointment.id, "start_at": appointment.scheduled_at.isoformat(), "summary": f"Xem nhà - {property_obj.title if property_obj else 'Nestora'}", "location": property_obj.address if property_obj else None}, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=20)
        response.raise_for_status(); data=response.json() if response.content else {}
        return {"external_event_id": str(data.get("id") or data.get("external_event_id") or f"{connection.provider}-{appointment.id}"), "status": "synced", "provider_response": data}
    def delete_event(self, connection, external_event_id):
        endpoint = (connection.config_json or {}).get("events_endpoint")
        if endpoint:
            token=unseal_secret(connection.access_token_encrypted)
            response=httpx.delete(f"{endpoint.rstrip('/')}/{external_event_id}", headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=20); response.raise_for_status()
        return {"external_event_id": external_event_id, "status": "deleted"}


def provider_for(connection: CalendarConnection) -> CalendarProvider:
    return LocalICSProvider() if connection.provider == "ics" else HTTPProvider()


def queue_calendar_sync(db: Session, appointment: Appointment, action: str) -> int:
    if not appointment.agent_id: return 0
    connections=list(db.scalars(select(CalendarConnection).where(CalendarConnection.agent_id == appointment.agent_id, CalendarConnection.status == "active")))
    count=0
    for connection in connections:
        existing=db.scalar(select(CalendarSyncEvent).where(CalendarSyncEvent.connection_id==connection.id, CalendarSyncEvent.appointment_id==appointment.id, CalendarSyncEvent.action==action, CalendarSyncEvent.status.in_(["queued","processing","completed"])))
        if existing: continue
        item=CalendarSyncEvent(connection_id=connection.id, appointment_id=appointment.id, action=action, payload_json={"scheduled_at": appointment.scheduled_at.isoformat(), "status": appointment.status})
        db.add(item); db.flush(); enqueue_job(db, "calendar_sync", {"sync_event_id": item.id}, idempotency_key=f"calendar:{connection.id}:{appointment.id}:{action}:{appointment.scheduled_at.isoformat()}"); count+=1
    return count


def sync_calendar_event(db: Session, sync_event_id: str) -> dict[str, Any]:
    item=db.get(CalendarSyncEvent, sync_event_id)
    if not item: return {"status":"missing"}
    connection=db.get(CalendarConnection, item.connection_id); appointment=db.get(Appointment, item.appointment_id) if item.appointment_id else None
    if not connection or not appointment: raise ValueError("Calendar connection or appointment missing")
    provider=provider_for(connection); prop=db.get(Property, appointment.property_id)
    if item.action == "delete" and item.external_event_id: result=provider.delete_event(connection,item.external_event_id)
    else: result=provider.upsert_event(connection,appointment,prop)
    item.external_event_id=result.get("external_event_id") or item.external_event_id; item.status="completed"; item.synced_at=datetime.now(timezone.utc); item.error=None; db.commit(); return result
