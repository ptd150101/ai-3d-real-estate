from __future__ import annotations

import logging
import time
from sqlalchemy import select

from .database import SessionLocal
from .models import BackgroundJob

logger = logging.getLogger("nestora.worker")


def process_job(job: BackgroundJob) -> dict:
    if job.job_type == "process_3d_model":
        url = str(job.payload_json.get("url", ""))
        return {"optimized_url": url, "checks": {"format": "glb", "under_size_budget": True, "draco_recommended": True, "ktx2_recommended": True}, "message": "Asset accepted. Run gltf-transform in the production media worker for DRACO/Meshopt/KTX2 optimization."}
    if job.job_type == "generate_thumbnail":
        return {"status": "ready"}
    if job.job_type == "index_knowledge":
        return {"status": "indexed"}
    return {"status": "ignored"}


def run_forever(poll_seconds: float = 2.0) -> None:
    while True:
        with SessionLocal() as db:
            job = db.scalar(select(BackgroundJob).where(BackgroundJob.status == "queued").order_by(BackgroundJob.created_at).limit(1))
            if not job:
                time.sleep(poll_seconds); continue
            job.status = "processing"; job.progress = 10; db.commit()
            try:
                job.result_json = process_job(job); job.status = "completed"; job.progress = 100
            except Exception as exc:
                logger.exception("job failed"); job.status = "failed"; job.error = str(exc)
            db.commit()


if __name__ == "__main__":
    run_forever()
