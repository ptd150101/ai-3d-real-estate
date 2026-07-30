from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AIQualityEvaluation,
    AnalyticsEvent,
    AnalyticsSession,
    CRMSyncEvent,
    DailyAgentMetric,
    DailyFunnelMetric,
    DailyPropertyMetric,
    NotificationDelivery,
)

ALLOWED_EVENTS = {
    "search_submitted", "search_result_clicked", "property_viewed", "gallery_opened",
    "viewer_started", "viewer_floor_changed", "panorama_started", "chat_started",
    "chat_tool_used", "chat_handoff_requested", "favorite_added", "saved_search_created",
    "appointment_started", "appointment_completed", "lead_created", "brochure_downloaded",
    "agent_message_sent", "legal_document_downloaded",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ingest_event(db: Session, user_id: str | None, payload) -> AnalyticsEvent:
    if payload.event_name not in ALLOWED_EVENTS:
        raise ValueError("Unknown analytics event")
    session = db.get(AnalyticsSession, payload.session_id) if payload.session_id else None
    if not session:
        session = AnalyticsSession(
            anonymous_id=payload.anonymous_id,
            user_id=user_id,
            consent=payload.consent,
            device_class=payload.device_class,
        )
        db.add(session)
        db.flush()
    else:
        session.last_seen_at = utcnow()
        if user_id:
            session.user_id = user_id
    if payload.dedupe_key:
        existing = db.scalar(select(AnalyticsEvent).where(AnalyticsEvent.dedupe_key == payload.dedupe_key))
        if existing:
            return existing
    metadata = dict(payload.metadata_json)
    # Strip obvious PII keys from analytics payloads.
    for key in list(metadata):
        if key.lower() in {"email", "phone", "full_name", "message", "content", "document_content"}:
            metadata.pop(key, None)
    item = AnalyticsEvent(
        session_id=session.id,
        user_id=user_id,
        event_name=payload.event_name,
        event_version=payload.event_version,
        property_id=payload.property_id,
        agent_id=payload.agent_id,
        metadata_json=metadata,
        dedupe_key=payload.dedupe_key,
        occurred_at=payload.occurred_at or utcnow(),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(AnalyticsEvent).where(AnalyticsEvent.dedupe_key == payload.dedupe_key))
        if existing:
            return existing
        raise
    return item


def aggregate_day(db: Session, metric_date: date) -> dict[str, Any]:
    start = datetime.combine(metric_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    events = list(db.scalars(select(AnalyticsEvent).where(AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at < end)))
    counts = Counter(x.event_name for x in events)
    for name, value in counts.items():
        item = db.scalar(select(DailyFunnelMetric).where(DailyFunnelMetric.metric_date == metric_date, DailyFunnelMetric.metric_name == name))
        if item:
            item.value = value
        else:
            db.add(DailyFunnelMetric(metric_date=metric_date, metric_name=name, value=value))
    property_ids = {x.property_id for x in events if x.property_id}
    for property_id in property_ids:
        subset = [x for x in events if x.property_id == property_id]
        values = Counter(x.event_name for x in subset)
        item = db.scalar(select(DailyPropertyMetric).where(DailyPropertyMetric.metric_date == metric_date, DailyPropertyMetric.property_id == property_id))
        if not item:
            item = DailyPropertyMetric(metric_date=metric_date, property_id=property_id)
            db.add(item)
        item.views = values["property_viewed"]
        item.viewer_starts = values["viewer_started"]
        item.panorama_starts = values["panorama_started"]
        item.chat_starts = values["chat_started"]
        item.leads = values["lead_created"]
        item.appointments = values["appointment_completed"]
    agent_ids = {x.agent_id for x in events if x.agent_id}
    for agent_id in agent_ids:
        subset = [x for x in events if x.agent_id == agent_id]
        values = Counter(x.event_name for x in subset)
        item = db.scalar(select(DailyAgentMetric).where(DailyAgentMetric.metric_date == metric_date, DailyAgentMetric.agent_id == agent_id))
        if not item:
            item = DailyAgentMetric(metric_date=metric_date, agent_id=agent_id)
            db.add(item)
        item.messages_received = values["agent_message_sent"]
        item.appointments_completed = values["appointment_completed"]
    db.commit()
    return {"date": metric_date.isoformat(), "events": len(events), "metrics": dict(counts)}


def dashboard(db: Session, start_date: date, end_date: date) -> dict[str, Any]:
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    funnel_rows = db.execute(select(AnalyticsEvent.event_name, func.count(AnalyticsEvent.id)).where(
        AnalyticsEvent.occurred_at >= start_dt,
        AnalyticsEvent.occurred_at < end_dt,
    ).group_by(AnalyticsEvent.event_name)).all()
    properties = list(db.scalars(select(DailyPropertyMetric).where(DailyPropertyMetric.metric_date.between(start_date, end_date))))
    agents = list(db.scalars(select(DailyAgentMetric).where(DailyAgentMetric.metric_date.between(start_date, end_date))))
    quality = db.execute(select(
        func.avg(AIQualityEvaluation.answer_helpful),
        func.avg(AIQualityEvaluation.citation_coverage),
        func.sum(AIQualityEvaluation.unanswered),
        func.sum(AIQualityEvaluation.handoff_required),
    ).where(AIQualityEvaluation.created_at >= start_dt, AIQualityEvaluation.created_at < end_dt)).one()
    notification_rows = db.execute(select(NotificationDelivery.status, func.count(NotificationDelivery.id)).where(
        NotificationDelivery.created_at >= start_dt,
        NotificationDelivery.created_at < end_dt,
    ).group_by(NotificationDelivery.status)).all()
    crm_rows = db.execute(select(CRMSyncEvent.status, func.count(CRMSyncEvent.id)).where(
        CRMSyncEvent.created_at >= start_dt,
        CRMSyncEvent.created_at < end_dt,
    ).group_by(CRMSyncEvent.status)).all()
    return {
        "start_date": start_date,
        "end_date": end_date,
        "funnel": {name: int(value) for name, value in funnel_rows},
        "property_metrics": [{
            "date": x.metric_date, "property_id": x.property_id, "views": x.views,
            "viewer_starts": x.viewer_starts, "panorama_starts": x.panorama_starts,
            "chat_starts": x.chat_starts, "leads": x.leads, "appointments": x.appointments,
        } for x in properties],
        "agent_metrics": [{
            "date": x.metric_date, "agent_id": x.agent_id, "leads_assigned": x.leads_assigned,
            "messages_received": x.messages_received, "appointments_completed": x.appointments_completed,
            "response_time_seconds": x.response_time_seconds,
        } for x in agents],
        "ai_quality": {"helpful_rate": float(quality[0] or 0), "citation_coverage": float(quality[1] or 0), "unanswered": int(quality[2] or 0), "handoff_required": int(quality[3] or 0)},
        "notification_health": {name: int(value) for name, value in notification_rows},
        "crm_health": {name: int(value) for name, value in crm_rows},
    }
