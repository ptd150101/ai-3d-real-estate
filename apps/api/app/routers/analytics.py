from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user_optional, require_roles
from ..models import AIQualityEvaluation, AnalyticsEvent, AnalyticsSession, User
from ..p1_schemas import AIQualityCreate, AnalyticsDashboard, AnalyticsEventCreate
from ..services.analytics import aggregate_day, dashboard, ingest_event
from ..services.jobs_p1 import enqueue_job

router = APIRouter(tags=["analytics"])


@router.post("/analytics/events", status_code=202)
def event(payload: AnalyticsEventCreate, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    try:
        item = ingest_event(db, user.id if user else None, payload); db.commit()
        return {"id": item.id, "session_id": item.session_id, "accepted": True}
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/analytics/ai-quality", status_code=201)
def ai_quality(payload: AIQualityCreate, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    item = AIQualityEvaluation(
        chat_session_id=payload.chat_session_id,
        evaluator_user_id=user.id if user else None,
        answer_helpful=payload.answer_helpful,
        citation_coverage=payload.citation_coverage,
        handoff_required=int(payload.handoff_required),
        unanswered=int(payload.unanswered),
        notes=payload.notes,
    )
    db.add(item); db.commit(); db.refresh(item); return {"id": item.id}


@router.get("/admin/analytics/dashboard", response_model=AnalyticsDashboard)
def admin_dashboard(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    end_date = end_date or date.today()
    start_date = start_date or end_date - timedelta(days=29)
    return dashboard(db, start_date, end_date)


@router.post("/admin/analytics/aggregate")
def aggregate(metric_date: date | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    metric_date = metric_date or date.today()
    job = enqueue_job(db, "analytics_aggregation", {"date": metric_date.isoformat()}, idempotency_key=f"analytics:{metric_date.isoformat()}")
    db.commit(); return {"job_id": job.id, "status": job.status}


@router.delete("/analytics/me", status_code=204)
def delete_my_analytics(db: Session = Depends(get_db), user: User = Depends(require_roles("buyer", "agent", "admin", "legal_reviewer"))):
    session_ids = list(db.scalars(select(AnalyticsSession.id).where(AnalyticsSession.user_id == user.id)))
    if session_ids:
        db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.session_id.in_(session_ids)))
    db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.user_id == user.id))
    db.execute(delete(AnalyticsSession).where(AnalyticsSession.user_id == user.id))
    db.commit(); return Response(status_code=204)
