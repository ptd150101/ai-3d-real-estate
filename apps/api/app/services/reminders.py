from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Appointment, Property
from .notification import emit_event


def send_appointment_reminders(db: Session) -> dict:
    now = datetime.now(timezone.utc); sent = 0
    appointments = list(db.scalars(select(Appointment).where(Appointment.status == "confirmed", Appointment.scheduled_at >= now, Appointment.scheduled_at <= now + timedelta(hours=25))))
    for item in appointments:
        scheduled = item.scheduled_at if item.scheduled_at.tzinfo else item.scheduled_at.replace(tzinfo=timezone.utc)
        hours = (scheduled - now).total_seconds() / 3600
        window = "24h" if 23 <= hours <= 25 else "2h" if 1 <= hours <= 3 else None
        if not window or not item.user_id: continue
        prop = db.get(Property, item.property_id)
        emit_event(db, event_type="appointment.reminder", aggregate_type="appointment", aggregate_id=item.id, recipients=[item.user_id], payload={"property_title": prop.title if prop else "bất động sản", "scheduled_at": scheduled.isoformat(), "window": window}, idempotency_key=f"appointment.reminder:{item.id}:{window}")
        sent += 1
    db.commit(); return {"checked": len(appointments), "sent": sent}
