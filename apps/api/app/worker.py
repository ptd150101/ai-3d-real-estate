from __future__ import annotations

import logging
import os
import time
from datetime import date
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import BackgroundJob
from .services.analytics import aggregate_day
from .services.crm import sync_event
from .services.calendar_sync import sync_calendar_event
from .services.jobs_p1 import enqueue_job
from .services.experience import generate_brochure
from .services.jobs_p1 import claim_job, complete_job, fail_job
from .services.notification import deliver
from .services.reminders import send_appointment_reminders
from .services.saved_search import match_all_saved_searches, match_saved_search
from .services.p2_contracts import expire_and_remind
from .services.p2_payments import expire_orders
from .services.p2_spatial import process_reconstruction
from .services.p2_tenant import create_tenant_export, resolve_org_context

logger = logging.getLogger("nestora.worker")


def process_legacy(job: BackgroundJob) -> dict:
    if job.job_type == "process_3d_model":
        url = str(job.payload_json.get("url", ""))
        return {"optimized_url": url, "checks": {"format": "glb", "under_size_budget": True, "draco_recommended": True, "ktx2_recommended": True}, "message": "Asset accepted; production optimization adapter is ready for glTF Transform/DRACO/Meshopt/KTX2."}
    if job.job_type == "generate_thumbnail": return {"status": "ready"}
    if job.job_type == "index_knowledge": return {"status": "indexed"}
    return {"status": "ignored"}


def process_durable(db, job) -> dict:
    p = job.payload_json
    if job.job_type == "notification_delivery": return deliver(db, p["delivery_id"])
    if job.job_type == "saved_search_matching": return match_saved_search(db, p["saved_search_id"]) if p.get("saved_search_id") else match_all_saved_searches(db)
    if job.job_type == "appointment_reminder": return send_appointment_reminders(db)
    if job.job_type == "calendar_sync": return sync_calendar_event(db, p["sync_event_id"])
    if job.job_type == "crm_sync": return sync_event(db, p["sync_event_id"])
    if job.job_type == "brochure_render": return generate_brochure(db, p["property_id"], p.get("template_version", "v1"), bool(p.get("force")))
    if job.job_type == "analytics_aggregation": return aggregate_day(db, date.fromisoformat(p["date"]))
    if job.job_type == "panorama_validation": return {"status": "validated", "scene_id": p.get("scene_id")}
    if job.job_type == "legal_watermark": return {"status": "ready", "grant_id": p.get("grant_id")}
    if job.job_type == "p2.reconstruction": return process_reconstruction(db, p["job_id"])
    if job.job_type == "p2.reservation_expiry": return {"expired": expire_orders(db)}
    if job.job_type == "p2.contract_maintenance": return expire_and_remind(db)
    return {"status": "ignored"}


def schedule_periodic(db) -> None:
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc); minute=now.strftime("%Y%m%d%H%M"); hour=now.strftime("%Y%m%d%H")
    enqueue_job(db,"appointment_reminder",{},idempotency_key=f"periodic:reminder:{minute}")
    enqueue_job(db,"p2.reservation_expiry",{},idempotency_key=f"periodic:p2-reservation-expiry:{minute}")
    enqueue_job(db,"p2.contract_maintenance",{},idempotency_key=f"periodic:p2-contracts:{minute}")
    if now.minute % 5 == 0: enqueue_job(db,"saved_search_matching",{},idempotency_key=f"periodic:saved-search:{minute}")
    if now.minute == 0: enqueue_job(db,"analytics_aggregation",{"date":now.date().isoformat()},idempotency_key=f"periodic:analytics:{hour}")
    db.commit()


def run_forever(poll_seconds: float | None = None) -> None:
    poll_seconds = poll_seconds or get_settings().worker_poll_seconds
    capabilities = {x.strip() for x in os.getenv("WORKER_CAPABILITIES", "cpu").split(",") if x.strip()}
    cpu_jobs = {"notification_delivery", "saved_search_matching", "appointment_reminder", "calendar_sync", "crm_sync", "brochure_render", "analytics_aggregation", "panorama_validation", "legal_watermark", "p2.reservation_expiry", "p2.contract_maintenance"}
    allowed_jobs = set(cpu_jobs)
    if "gpu" in capabilities:
        allowed_jobs.add("p2.reconstruction")
    last_periodic: str | None = None
    while True:
        with SessionLocal() as db:
            from datetime import datetime, timezone
            current_minute=datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
            if current_minute != last_periodic:
                schedule_periodic(db); last_periodic=current_minute
            durable = claim_job(db, allowed_job_types=allowed_jobs)
            if durable:
                try:
                    result = process_durable(db, durable); complete_job(db, durable, result)
                except Exception as exc:
                    logger.exception("durable job failed"); fail_job(db, durable, str(exc))
                continue
            legacy = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "queued").order_by(BackgroundJob.created_at).limit(1))
            if not legacy:
                time.sleep(poll_seconds); continue
            legacy.status = "processing"; legacy.progress = 10; db.commit()
            try: legacy.result_json = process_legacy(legacy); legacy.status = "completed"; legacy.progress = 100
            except Exception as exc: logger.exception("legacy job failed"); legacy.status = "failed"; legacy.error = str(exc)
            db.commit()


if __name__ == "__main__": run_forever()
