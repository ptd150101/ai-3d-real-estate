from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import Agent, AgentReview, ReviewReport, ReviewResponse, User
from ..p1_schemas import ReviewCreate, ReviewRead, ReviewReportCreate, ReviewResponseCreate, ReviewUpdate
from ..services.reputation import create_review, recompute_agent_rating, respond_to_review, update_review

router = APIRouter(tags=["reviews"])


def serialize(db: Session, item: AgentReview) -> ReviewRead:
    response = db.scalar(select(ReviewResponse).where(ReviewResponse.review_id == item.id))
    return ReviewRead(
        id=item.id, agent_id=item.agent_id, user_id=item.user_id, appointment_id=item.appointment_id,
        rating=item.rating, communication_rating=item.communication_rating,
        knowledge_rating=item.knowledge_rating, responsiveness_rating=item.responsiveness_rating,
        comment=item.comment, verified=item.verified, status=item.status,
        created_at=item.created_at, updated_at=item.updated_at,
        response={"id": response.id, "content": response.content, "created_at": response.created_at} if response else None,
    )


@router.get("/agents/{agent_id}/reviews")
def list_reviews(agent_id: str, page: int = 1, page_size: int = 10, rating: int | None = None, db: Session = Depends(get_db)):
    stmt = select(AgentReview).where(AgentReview.agent_id == agent_id, AgentReview.status == "published")
    if rating: stmt = stmt.where(AgentReview.rating == rating)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(db.scalars(stmt.order_by(AgentReview.created_at.desc()).offset((page-1)*page_size).limit(min(page_size, 50))))
    distribution = {i: int(db.scalar(select(func.count(AgentReview.id)).where(AgentReview.agent_id == agent_id, AgentReview.status == "published", AgentReview.rating == i)) or 0) for i in range(1, 6)}
    agent = db.get(Agent, agent_id)
    return {"items": [serialize(db, x).model_dump() for x in rows], "total": total, "page": page, "page_size": page_size, "rating": agent.rating if agent else 0, "distribution": distribution}


@router.post("/reviews", response_model=ReviewRead, status_code=201)
def add_review(payload: ReviewCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        item = create_review(db, user, payload)
        db.commit(); db.refresh(item)
        return serialize(db, item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/reviews/{review_id}", response_model=ReviewRead)
def edit_review(review_id: str, payload: ReviewUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(AgentReview, review_id)
    if not item: raise HTTPException(status_code=404, detail="Review not found")
    try:
        update_review(db, item, user, payload); db.commit(); db.refresh(item); return serialize(db, item)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reviews/{review_id}/response", status_code=201)
def respond(review_id: str, payload: ReviewResponseCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("agent", "admin"))):
    item = db.get(AgentReview, review_id)
    if not item: raise HTTPException(status_code=404, detail="Review not found")
    try:
        response = respond_to_review(db, item, user, payload.content); db.commit(); db.refresh(response)
        return {"id": response.id, "content": response.content, "created_at": response.created_at}
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/reviews/{review_id}/report", status_code=201)
def report(review_id: str, payload: ReviewReportCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(AgentReview, review_id): raise HTTPException(status_code=404, detail="Review not found")
    existing = db.scalar(select(ReviewReport).where(ReviewReport.review_id == review_id, ReviewReport.reporter_user_id == user.id))
    if existing: return {"id": existing.id, "status": existing.status}
    item = ReviewReport(review_id=review_id, reporter_user_id=user.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return {"id": item.id, "status": item.status}


@router.get("/admin/review-reports")
def reports(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    rows = list(db.scalars(select(ReviewReport).order_by(ReviewReport.created_at.desc())))
    return [{"id": x.id, "review_id": x.review_id, "reason": x.reason, "details": x.details, "status": x.status, "created_at": x.created_at} for x in rows]


@router.patch("/admin/reviews/{review_id}/moderate", status_code=204)
def moderate(review_id: str, status: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    if status not in {"published", "hidden", "removed"}: raise HTTPException(status_code=400, detail="Invalid status")
    item = db.get(AgentReview, review_id)
    if not item: raise HTTPException(status_code=404, detail="Review not found")
    item.status = status; recompute_agent_rating(db, item.agent_id); db.commit(); return Response(status_code=204)
