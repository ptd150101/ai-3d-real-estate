from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AgentAvailabilityException,
    AgentAvailabilityRule,
    Appointment,
    AppointmentSlot,
    Property,
)
from .calendar_sync import queue_calendar_sync
from .notification import emit_event


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def generate_slots(db: Session, agent_id: str, start_date: date, days: int = 14) -> list[dict]:
    rules = list(
        db.scalars(
            select(AgentAvailabilityRule).where(
                AgentAvailabilityRule.agent_id == agent_id,
                AgentAvailabilityRule.active.is_(True),
            )
        )
    )
    if not rules:
        rules = [
            AgentAvailabilityRule(
                agent_id=agent_id,
                weekday=i,
                start_minute=9 * 60,
                end_minute=17 * 60,
                slot_minutes=60,
                buffer_minutes=15,
            )
            for i in range(0, 6)
        ]
    start_utc = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_utc = start_utc + timedelta(days=days + 1)
    exceptions = list(
        db.scalars(
            select(AgentAvailabilityException).where(
                AgentAvailabilityException.agent_id == agent_id,
                AgentAvailabilityException.end_at >= start_utc,
                AgentAvailabilityException.start_at <= end_utc,
            )
        )
    )
    booked = list(
        db.scalars(
            select(AppointmentSlot).where(
                AppointmentSlot.agent_id == agent_id,
                AppointmentSlot.start_at >= start_utc,
                AppointmentSlot.start_at < end_utc,
                AppointmentSlot.status.in_(["held", "booked"]),
            )
        )
    )
    result: list[dict] = []
    now = datetime.now(timezone.utc) + timedelta(minutes=30)
    for offset in range(days):
        current_date = start_date + timedelta(days=offset)
        for rule in rules:
            if current_date.weekday() != rule.weekday:
                continue
            tz = ZoneInfo(rule.timezone or "Asia/Ho_Chi_Minh")
            cursor_local = datetime.combine(
                current_date,
                time(rule.start_minute // 60, rule.start_minute % 60),
                tzinfo=tz,
            )
            end_local = datetime.combine(current_date, time.min, tzinfo=tz) + timedelta(
                minutes=rule.end_minute
            )
            while cursor_local + timedelta(minutes=rule.slot_minutes) <= end_local:
                slot_start = cursor_local.astimezone(timezone.utc)
                slot_end = (cursor_local + timedelta(minutes=rule.slot_minutes)).astimezone(
                    timezone.utc
                )
                cursor_local += timedelta(minutes=rule.slot_minutes + rule.buffer_minutes)
                if slot_start <= now:
                    continue
                overridden = next(
                    (
                        item
                        for item in exceptions
                        if aware(item.start_at) < slot_end and aware(item.end_at) > slot_start
                    ),
                    None,
                )
                unavailable = bool(overridden and not overridden.available)
                existing = next(
                    (item for item in booked if aware(item.start_at) == slot_start),
                    None,
                )
                result.append(
                    {
                        "id": existing.id if existing else None,
                        "agent_id": agent_id,
                        "start_at": slot_start,
                        "end_at": slot_end,
                        "available": not unavailable and existing is None,
                        "status": existing.status
                        if existing
                        else ("blocked" if unavailable else "available"),
                    }
                )
    return result


def book_slot(
    db: Session,
    *,
    property_obj: Property,
    agent_id: str,
    user_id: str | None,
    start_at: datetime,
    full_name: str,
    phone: str,
    email: str | None,
    note: str | None,
    source: str = "web",
) -> Appointment:
    start_at = aware(start_at).astimezone(timezone.utc)
    available = [
        item
        for item in generate_slots(db, agent_id, start_at.date(), days=2)
        if aware(item["start_at"]) == start_at and item["available"]
    ]
    if not available:
        raise ValueError("Selected appointment slot is no longer available")
    end_at = aware(available[0]["end_at"])
    appointment = Appointment(
        property_id=property_obj.id,
        user_id=user_id,
        agent_id=agent_id,
        full_name=full_name,
        phone=phone,
        email=email,
        scheduled_at=start_at,
        note=note,
        status="pending",
        source=source,
    )
    db.add(appointment)
    db.flush()
    slot = AppointmentSlot(
        agent_id=agent_id,
        start_at=start_at,
        end_at=end_at,
        status="booked",
        appointment_id=appointment.id,
    )
    db.add(slot)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Selected appointment slot was just booked") from exc
    queue_calendar_sync(db, appointment, "upsert")
    if user_id:
        emit_event(
            db,
            event_type="appointment.created",
            aggregate_type="appointment",
            aggregate_id=appointment.id,
            recipients=[user_id],
            payload={
                "property_title": property_obj.title,
                "scheduled_at": start_at.isoformat(),
            },
            idempotency_key=f"appointment.created:{appointment.id}",
        )
    return appointment


def change_appointment_status(
    db: Session,
    appointment: Appointment,
    status: str,
    actor_user_id: str | None = None,
) -> None:
    appointment.status = status
    slot = db.scalar(
        select(AppointmentSlot).where(AppointmentSlot.appointment_id == appointment.id)
    )
    if status in {"rejected", "cancelled_by_buyer", "cancelled_by_agent"} and slot:
        db.delete(slot)
    elif status in {"confirmed", "completed", "no_show"} and slot:
        slot.status = "booked"
    queue_calendar_sync(
        db,
        appointment,
        "delete"
        if status in {"rejected", "cancelled_by_buyer", "cancelled_by_agent"}
        else "upsert",
    )
    recipients = [item for item in [appointment.user_id] if item]
    if recipients:
        event_type = (
            "appointment.confirmed"
            if status == "confirmed"
            else "appointment.cancelled"
            if status.startswith("cancelled") or status == "rejected"
            else None
        )
        if event_type:
            property_obj = db.get(Property, appointment.property_id)
            emit_event(
                db,
                event_type=event_type,
                aggregate_type="appointment",
                aggregate_id=appointment.id,
                recipients=recipients,
                payload={
                    "property_title": property_obj.title
                    if property_obj
                    else "bất động sản",
                    "scheduled_at": aware(appointment.scheduled_at).isoformat(),
                },
                idempotency_key=f"{event_type}:{appointment.id}:{status}",
                actor_user_id=actor_user_id,
            )


def reschedule_appointment(
    db: Session,
    appointment: Appointment,
    start_at: datetime,
    actor_user_id: str | None = None,
) -> Appointment:
    if appointment.status in {
        "completed",
        "no_show",
        "rejected",
        "cancelled_by_buyer",
        "cancelled_by_agent",
    }:
        raise ValueError("Appointment can no longer be rescheduled")
    start_at = aware(start_at).astimezone(timezone.utc)
    slot = db.scalar(
        select(AppointmentSlot).where(AppointmentSlot.appointment_id == appointment.id)
    )
    if not slot:
        raise ValueError("Appointment slot not found")
    old_start, old_end, old_status = slot.start_at, slot.end_at, slot.status
    slot.status = "rescheduling"
    db.flush()
    available = [
        item
        for item in generate_slots(db, appointment.agent_id, start_at.date(), days=2)
        if aware(item["start_at"]) == start_at and item["available"]
    ]
    if not available:
        slot.start_at, slot.end_at, slot.status = old_start, old_end, old_status
        raise ValueError("Selected appointment slot is no longer available")
    try:
        slot.start_at = start_at
        slot.end_at = aware(available[0]["end_at"])
        slot.status = "booked"
        appointment.scheduled_at = start_at
        appointment.status = "pending"
        db.flush()
    except IntegrityError as exc:
        slot.start_at, slot.end_at, slot.status = old_start, old_end, old_status
        raise ValueError("Selected appointment slot was just booked") from exc
    queue_calendar_sync(db, appointment, "upsert")
    if appointment.user_id:
        property_obj = db.get(Property, appointment.property_id)
        emit_event(
            db,
            event_type="appointment.rescheduled",
            aggregate_type="appointment",
            aggregate_id=appointment.id,
            recipients=[appointment.user_id],
            payload={
                "property_title": property_obj.title
                if property_obj
                else "bất động sản",
                "scheduled_at": start_at.isoformat(),
            },
            idempotency_key=(
                f"appointment.rescheduled:{appointment.id}:{start_at.isoformat()}"
            ),
            actor_user_id=actor_user_id,
        )
    return appointment
