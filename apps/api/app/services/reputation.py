from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Agent, AgentReview, Appointment, ReviewResponse, User


def recompute_agent_rating(db: Session, agent_id: str) -> float:
    value = db.scalar(select(func.avg(AgentReview.rating)).where(
        AgentReview.agent_id == agent_id,
        AgentReview.status == "published",
        AgentReview.verified.is_(True),
    ))
    rating = round(float(value or 0), 2)
    agent = db.get(Agent, agent_id)
    if agent:
        agent.rating = rating
    return rating


def create_review(db: Session, user: User, payload) -> AgentReview:
    appointment = db.get(Appointment, payload.appointment_id)
    if not appointment or appointment.user_id != user.id:
        raise ValueError("Completed appointment not found")
    if appointment.status != "completed":
        raise ValueError("Only completed appointments can be reviewed")
    if not appointment.agent_id:
        raise ValueError("Appointment has no assigned agent")
    agent = db.get(Agent, appointment.agent_id)
    if agent and agent.user_id == user.id:
        raise ValueError("You cannot review yourself")
    existing = db.scalar(select(AgentReview).where(AgentReview.appointment_id == appointment.id))
    if existing:
        raise ValueError("Appointment was already reviewed")
    item = AgentReview(
        agent_id=appointment.agent_id,
        user_id=user.id,
        appointment_id=appointment.id,
        edited_until=datetime.now(timezone.utc) + timedelta(days=7),
        **payload.model_dump(),
    )
    db.add(item)
    db.flush()
    recompute_agent_rating(db, item.agent_id)
    return item


def update_review(db: Session, item: AgentReview, user: User, payload) -> AgentReview:
    if item.user_id != user.id:
        raise PermissionError("Not allowed")
    edited_until = item.edited_until
    if edited_until and (edited_until if edited_until.tzinfo else edited_until.replace(tzinfo=timezone.utc)) < datetime.now(timezone.utc):
        raise ValueError("Review edit window has expired")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    recompute_agent_rating(db, item.agent_id)
    return item


def respond_to_review(db: Session, review: AgentReview, user: User, content: str) -> ReviewResponse:
    agent = db.get(Agent, review.agent_id)
    if not agent or (user.role != "admin" and agent.user_id != user.id):
        raise PermissionError("Only the reviewed agent can respond")
    existing = db.scalar(select(ReviewResponse).where(ReviewResponse.review_id == review.id))
    if existing:
        existing.content = content
        existing.agent_user_id = user.id
        return existing
    item = ReviewResponse(review_id=review.id, agent_user_id=user.id, content=content)
    db.add(item)
    return item
