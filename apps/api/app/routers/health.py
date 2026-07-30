from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..config import get_settings
from ..database import get_db
router = APIRouter(tags=["health"])
@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1")); return {"status": "ok", "service": get_settings().app_name}
@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1")); return {"status": "ready"}
@router.get("/metrics")
def metrics(): return {"service": "nestora-api", "status": 1}
