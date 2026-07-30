from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..dependencies import require_roles
from ..models import BackgroundJob, User
router = APIRouter(prefix="/jobs", tags=["jobs"])
@router.get("")
def list_jobs(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))): return list(db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(100)))
@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    job = db.get(BackgroundJob, job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found")
    return job
