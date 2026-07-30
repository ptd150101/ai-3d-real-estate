from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import BackgroundJob, User
from ..schemas import UploadResponse
from ..services.storage import StorageError, save_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])

@router.post("", response_model=UploadResponse, status_code=201)
def upload(file: UploadFile = File(...), namespace: str = "uploads", db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    try:
        url, size, content_type = save_upload(file.file, file.filename or "upload.bin", file.content_type, namespace)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = None
    if content_type in {"model/gltf-binary", "model/gltf+json", "application/octet-stream"} or (file.filename or "").lower().endswith((".glb", ".gltf")):
        job = BackgroundJob(job_type="process_3d_model", payload_json={"url": url, "filename": file.filename, "content_type": content_type})
        db.add(job); db.commit(); db.refresh(job); job_id = job.id
    return UploadResponse(url=url, filename=file.filename or "upload.bin", content_type=content_type, size=size, job_id=job_id)
