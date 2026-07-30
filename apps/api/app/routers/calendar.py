from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import Agent, AgentAvailabilityException, AgentAvailabilityRule, Appointment, CalendarConnection, CalendarSyncEvent, User, Property
from ..p1_schemas import (
    AppointmentReschedule, AppointmentStatusUpdate,
    CalendarConnectionCreate, CalendarConnectionRead,
    AvailabilityExceptionCreate,
    AvailabilityExceptionRead,
    AvailabilityRuleCreate,
    AvailabilityRuleRead,
    SlotBookingCreate,
    SlotRead,
)
from ..services.availability import book_slot, change_appointment_status, generate_slots, reschedule_appointment
from ..services.secrets import seal_secret

router = APIRouter(tags=["calendar"])


def agent_for_user(db: Session, user: User) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.user_id == user.id))
    if not agent and user.role != "admin":
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return agent


@router.get("/agent/calendar-connections", response_model=list[CalendarConnectionRead])
def calendar_connections(db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    agent = agent_for_user(db, user)
    if not agent: return []
    return list(db.scalars(select(CalendarConnection).where(CalendarConnection.agent_id == agent.id)))


@router.post("/agent/calendar-connections", response_model=CalendarConnectionRead, status_code=201)
def create_calendar_connection(payload: CalendarConnectionCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    agent = agent_for_user(db, user)
    if not agent: raise HTTPException(status_code=400, detail="Admin must select an agent")
    item = CalendarConnection(agent_id=agent.id, provider=payload.provider, account_email=str(payload.account_email) if payload.account_email else None, external_calendar_id=payload.external_calendar_id, access_token_encrypted=seal_secret(payload.access_token), refresh_token_encrypted=seal_secret(payload.refresh_token), config_json=payload.config_json, status=payload.status)
    db.add(item); db.commit(); db.refresh(item); return item


@router.get("/agents/{agent_id}/availability", response_model=list[SlotRead])
def public_availability(agent_id: str, start: date = Query(default_factory=date.today), days: int = Query(14, ge=1, le=31), db: Session = Depends(get_db)):
    if not db.get(Agent, agent_id): raise HTTPException(status_code=404, detail="Agent not found")
    return generate_slots(db, agent_id, start, days)


@router.get("/agent/availability-rules", response_model=list[AvailabilityRuleRead])
def my_rules(db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    agent = agent_for_user(db, user)
    if not agent: return []
    return list(db.scalars(select(AgentAvailabilityRule).where(AgentAvailabilityRule.agent_id == agent.id).order_by(AgentAvailabilityRule.weekday, AgentAvailabilityRule.start_minute)))


@router.post("/agent/availability-rules", response_model=AvailabilityRuleRead, status_code=201)
def create_rule(payload: AvailabilityRuleCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    agent = agent_for_user(db, user)
    if not agent: raise HTTPException(status_code=400, detail="Admin must use an agent-scoped endpoint")
    item = AgentAvailabilityRule(agent_id=agent.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item


@router.delete("/agent/availability-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    item = db.get(AgentAvailabilityRule, rule_id)
    if not item: raise HTTPException(status_code=404, detail="Rule not found")
    agent = agent_for_user(db, user)
    if user.role != "admin" and item.agent_id != agent.id: raise HTTPException(status_code=403, detail="Not allowed")
    db.delete(item); db.commit(); return Response(status_code=204)


@router.post("/agent/availability-exceptions", response_model=AvailabilityExceptionRead, status_code=201)
def create_exception(payload: AvailabilityExceptionCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    agent = agent_for_user(db, user)
    if not agent: raise HTTPException(status_code=400, detail="Admin must select an agent")
    item = AgentAvailabilityException(agent_id=agent.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item


@router.post("/appointments/book", status_code=201)
def book(payload: SlotBookingCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prop = db.get(Property, payload.property_id)
    if not prop: raise HTTPException(status_code=404, detail="Property not found")
    if prop.agent_id and prop.agent_id != payload.agent_id: raise HTTPException(status_code=400, detail="Agent does not own this listing")
    try:
        item = book_slot(db, property_obj=prop, agent_id=payload.agent_id, user_id=user.id, start_at=payload.start_at, full_name=payload.full_name, phone=payload.phone, email=str(payload.email) if payload.email else None, note=payload.note)
        db.commit(); db.refresh(item)
        return {"id": item.id, "status": item.status, "scheduled_at": item.scheduled_at, "property_id": item.property_id, "agent_id": item.agent_id}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/appointments/{appointment_id}.ics")
def appointment_ics(appointment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(Appointment, appointment_id)
    if not item: raise HTTPException(status_code=404, detail="Appointment not found")
    agent = db.scalar(select(Agent).where(Agent.user_id == user.id)) if user.role == "agent" else None
    if user.role != "admin" and item.user_id != user.id and (not agent or item.agent_id != agent.id): raise HTTPException(status_code=403, detail="Not allowed")
    start = item.scheduled_at.astimezone(timezone.utc); end = start + timedelta(hours=1)
    prop = db.get(Property, item.property_id)
    body = "\r\n".join(["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Nestora//Appointment//VI","BEGIN:VEVENT",f"UID:{item.id}@nestora",f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",f"SUMMARY:Xem nhà - {prop.title if prop else 'Nestora'}",f"LOCATION:{prop.address if prop else ''}","END:VEVENT","END:VCALENDAR",""])
    return Response(content=body, media_type="text/calendar", headers={"Content-Disposition": f'attachment; filename="appointment-{item.id}.ics"'})


@router.patch("/appointments/{appointment_id}/reschedule")
def reschedule(appointment_id: str, payload: AppointmentReschedule, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item=db.get(Appointment, appointment_id)
    if not item: raise HTTPException(status_code=404, detail="Appointment not found")
    agent=db.scalar(select(Agent).where(Agent.user_id==user.id)) if user.role=="agent" else None
    if user.role!="admin" and item.user_id!=user.id and (not agent or item.agent_id!=agent.id): raise HTTPException(status_code=403, detail="Not allowed")
    try:
        reschedule_appointment(db,item,payload.start_at,user.id); db.commit(); db.refresh(item)
        return {"id":item.id,"status":item.status,"scheduled_at":item.scheduled_at}
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=409,detail=str(exc)) from exc


@router.patch("/appointments/{appointment_id}/status")
def status(appointment_id: str, payload: AppointmentStatusUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(Appointment, appointment_id)
    if not item: raise HTTPException(status_code=404, detail="Appointment not found")
    agent = db.scalar(select(Agent).where(Agent.user_id == user.id)) if user.role == "agent" else None
    if user.role != "admin" and item.user_id != user.id and (not agent or item.agent_id != agent.id): raise HTTPException(status_code=403, detail="Not allowed")
    if user.role == "buyer" and payload.status not in {"cancelled_by_buyer"}: raise HTTPException(status_code=403, detail="Buyer can only cancel")
    change_appointment_status(db, item, payload.status, user.id)
    db.commit(); db.refresh(item)
    return {"id": item.id, "status": item.status, "scheduled_at": item.scheduled_at}
