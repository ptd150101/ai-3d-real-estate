from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import DurableJob


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_job(
    db: Session,
    job_type: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
    max_attempts: int = 5,
) -> DurableJob:
    if idempotency_key:
        existing = db.scalar(select(DurableJob).where(DurableJob.idempotency_key == idempotency_key))
        if existing:
            return existing
    item = DurableJob(
        job_type=job_type,
        payload_json=payload,
        idempotency_key=idempotency_key,
        priority=priority,
        run_after=run_after or now_utc(),
        max_attempts=max_attempts,
    )
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        if idempotency_key:
            existing = db.scalar(select(DurableJob).where(DurableJob.idempotency_key == idempotency_key))
            if existing:
                return existing
        raise
    return item


def claim_job(db: Session, *, worker_id: str | None = None, lease_seconds: int = 90) -> DurableJob | None:
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    now = now_utc()
    stmt = (
        select(DurableJob)
        .where(
            DurableJob.status.in_(["queued", "retry"]),
            DurableJob.run_after <= now,
            or_(DurableJob.locked_until.is_(None), DurableJob.locked_until < now),
        )
        .order_by(DurableJob.priority.asc(), DurableJob.run_after.asc(), DurableJob.created_at.asc())
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    item = db.scalar(stmt)
    if not item:
        return None
    item.status = "processing"
    item.locked_by = worker_id
    item.locked_until = now + timedelta(seconds=lease_seconds)
    item.heartbeat_at = now
    item.attempts += 1
    db.commit()
    db.refresh(item)
    return item


def heartbeat(db: Session, item: DurableJob, lease_seconds: int = 90) -> None:
    now = now_utc()
    item.heartbeat_at = now
    item.locked_until = now + timedelta(seconds=lease_seconds)
    db.commit()


def complete_job(db: Session, item: DurableJob, result: dict[str, Any] | None = None) -> None:
    item.status = "completed"
    item.result_json = result or {}
    item.error = None
    item.locked_by = None
    item.locked_until = None
    db.commit()


def fail_job(db: Session, item: DurableJob, error: str) -> None:
    item.error = error[:10000]
    item.locked_by = None
    item.locked_until = None
    if item.attempts >= item.max_attempts:
        item.status = "dead"
    else:
        item.status = "retry"
        delay = min(3600, 2 ** min(item.attempts, 10) * 15)
        item.run_after = now_utc() + timedelta(seconds=delay)
    db.commit()
