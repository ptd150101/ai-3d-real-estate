from __future__ import annotations

import hashlib
import json
import mimetypes

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models import (
    ARAsset,
    ARSession,
    CaptureFile,
    CaptureSession,
    ReconstructionArtifact,
    ReconstructionJob,
    User,
    VRSession,
    VRTourConfig,
)
from ..p2_dependencies import get_org_context
from ..p2_schemas import (
    ARSessionCreate,
    AssetReviewCreate,
    CaptureFileCreate,
    CaptureSessionCreate,
    ReconstructionStartCreate,
    VRSessionCreate,
)
from ..services.jobs_p1 import enqueue_job
from ..services.p2_spatial import (
    ALLOWED_CAPTURE_TYPES,
    add_capture_file,
    process_reconstruction,
    review_artifact,
    start_reconstruction,
)
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission
from ..services.storage import save_private_bytes, safe_filename

router = APIRouter(tags=["p2-spatial"])
MAX_CAPTURE_UPLOAD_BYTES = 50 * 1024 * 1024


def _capture_session(db: Session, ctx: OrgContext, session_id: str) -> CaptureSession:
    session = db.get(CaptureSession, session_id)
    if not session or session.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Capture session not found")
    return session


@router.get("/captures")
def list_captures(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "reconstruction")
    require_org_permission(ctx, "spatial.write")
    sessions = list(
        db.scalars(
            select(CaptureSession)
            .where(CaptureSession.organization_id == ctx.organization.id)
            .order_by(CaptureSession.created_at.desc())
            .limit(100)
        )
    )
    result = []
    for session in sessions:
        file_count = int(
            db.scalar(
                select(func.count(CaptureFile.id)).where(CaptureFile.session_id == session.id)
            )
            or 0
        )
        latest_job = db.scalar(
            select(ReconstructionJob)
            .where(ReconstructionJob.session_id == session.id)
            .order_by(ReconstructionJob.created_at.desc())
            .limit(1)
        )
        result.append(
            {
                "id": session.id,
                "property_id": session.property_id,
                "status": session.status,
                "capture_type": session.capture_type,
                "requirements": session.requirements_json,
                "quality_report": session.quality_report_json,
                "file_count": file_count,
                "job_id": latest_job.id if latest_job else None,
                "created_at": session.created_at,
            }
        )
    return result


@router.post("/captures", status_code=201)
def capture(
    payload: CaptureSessionCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "reconstruction")
    require_org_permission(ctx, "spatial.write")
    from ..models import Property

    prop = db.get(Property, payload.property_id)
    if not prop or prop.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Property not found")
    item = CaptureSession(
        organization_id=ctx.organization.id,
        property_id=prop.id,
        created_by_user_id=ctx.user.id,
        status="collecting",
        capture_type=payload.capture_type,
        requirements_json=payload.requirements
        or {"minimum_images": 12, "coverage": "360 degrees"},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "status": item.status, "requirements": item.requirements_json}


@router.post("/captures/{session_id}/upload", status_code=201)
def upload_capture_file(
    session_id: str,
    file: UploadFile = File(...),
    metadata: str = Form(default="{}"),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "reconstruction")
    require_org_permission(ctx, "spatial.write")
    session = _capture_session(db, ctx, session_id)
    data = file.file.read(MAX_CAPTURE_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Capture file is empty")
    if len(data) > MAX_CAPTURE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Capture file exceeds 50 MB")
    filename = safe_filename(file.filename or "capture.bin")
    mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime_type not in ALLOWED_CAPTURE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported capture type")
    try:
        metadata_json = json.loads(metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="metadata must be valid JSON") from exc
    if not isinstance(metadata_json, dict):
        raise HTTPException(status_code=422, detail="metadata must be a JSON object")
    digest = hashlib.sha256(data).hexdigest()
    storage_key, size, stored_type = save_private_bytes(
        data,
        filename,
        f"captures/{session.id}",
        mime_type,
    )
    url = f"private://{storage_key}" if get_settings().storage_backend == "s3" else storage_key
    try:
        item = add_capture_file(
            db,
            session,
            url=url,
            sha256=digest,
            mime_type=stored_type,
            size_bytes=size,
            metadata={
                **metadata_json,
                "original_filename": filename,
                "uploaded_by": ctx.user.id,
                "private": True,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": item.id,
        "sha256": item.sha256,
        "mime_type": item.mime_type,
        "size_bytes": item.size_bytes,
        "sequence": (item.metadata_json or {}).get("sequence"),
    }


@router.post("/captures/{session_id}/files", status_code=201)
def capture_file(
    session_id: str,
    payload: CaptureFileCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "spatial.write")
    session = _capture_session(db, ctx, session_id)
    try:
        item = add_capture_file(
            db,
            session,
            url=payload.url,
            sha256=payload.sha256,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": item.id, "sha256": item.sha256, "mime_type": item.mime_type}


@router.post("/captures/{session_id}/reconstruct", status_code=202)
def reconstruct(
    session_id: str,
    payload: ReconstructionStartCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "spatial.write")
    session = _capture_session(db, ctx, session_id)
    try:
        job = start_reconstruction(db, session, payload.representation)
        enqueue_job(
            db,
            "p2.reconstruction",
            {"job_id": job.id},
            idempotency_key=f"p2-reconstruction:{job.id}",
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "representation": job.representation,
    }


def _run_reconstruction(job_id: str, ctx: OrgContext, db: Session):
    require_org_permission(ctx, "spatial.write")
    job = db.get(ReconstructionJob, job_id)
    session = db.get(CaptureSession, job.session_id) if job else None
    if not job or not session or session.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return process_reconstruction(db, job.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reconstruction-jobs/{job_id}/run")
def run(
    job_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    """Run the configured reconstruction backend (fixture, COLMAP or Nerfstudio)."""
    return _run_reconstruction(job_id, ctx, db)


@router.post("/reconstruction-jobs/{job_id}/run-local")
def run_local(
    job_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    """Backward-compatible alias used by deterministic CI fixtures."""
    return _run_reconstruction(job_id, ctx, db)


@router.get("/reconstruction-jobs")
def list_jobs(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "spatial.write")
    rows = list(
        db.execute(
            select(ReconstructionJob, CaptureSession)
            .join(CaptureSession, ReconstructionJob.session_id == CaptureSession.id)
            .where(CaptureSession.organization_id == ctx.organization.id)
            .order_by(ReconstructionJob.created_at.desc())
            .limit(100)
        )
    )
    result = []
    for job, session in rows:
        artifact = db.scalar(
            select(ReconstructionArtifact)
            .where(ReconstructionArtifact.job_id == job.id)
            .order_by(ReconstructionArtifact.version.desc())
            .limit(1)
        )
        result.append(
            {
                "id": job.id,
                "session_id": session.id,
                "property_id": session.property_id,
                "representation": job.representation,
                "status": job.status,
                "stage": job.stage,
                "progress": job.progress,
                "checkpoint": job.checkpoint_json,
                "error": job.error,
                "cost_amount": job.cost_amount,
                "artifact": None
                if not artifact
                else {
                    "id": artifact.id,
                    "asset_type": artifact.asset_type,
                    "version": artifact.version,
                    "published": artifact.published,
                    "metadata": artifact.metadata_json,
                    "url": artifact.url if artifact.published else None,
                },
                "created_at": job.created_at,
            }
        )
    return result


@router.get("/reconstruction-jobs/{job_id}")
def get_job(
    job_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    job = db.get(ReconstructionJob, job_id)
    session = db.get(CaptureSession, job.session_id) if job else None
    if not job or not session or session.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Job not found")
    artifact = db.scalar(
        select(ReconstructionArtifact)
        .where(ReconstructionArtifact.job_id == job.id)
        .order_by(ReconstructionArtifact.version.desc())
    )
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "checkpoint": job.checkpoint_json,
        "error": job.error,
        "cost_amount": job.cost_amount,
        "artifact_id": artifact.id if artifact else None,
    }


@router.post("/reconstruction-artifacts/{artifact_id}/review")
def review(
    artifact_id: str,
    payload: AssetReviewCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    if ctx.member.role not in {"owner", "manager", "reviewer"}:
        raise HTTPException(status_code=403, detail="Reviewer role required")
    artifact = db.get(ReconstructionArtifact, artifact_id)
    job = db.get(ReconstructionJob, artifact.job_id) if artifact else None
    session = db.get(CaptureSession, job.session_id) if job else None
    if not artifact or not session or session.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        item = review_artifact(db, artifact, ctx.user.id, payload.status, payload.notes)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": item.id, "status": item.status, "published": artifact.published}


@router.get("/properties/{property_id}/immersive")
def immersive(property_id: str, db: Session = Depends(get_db)):
    ar = db.scalar(
        select(ARAsset).where(ARAsset.property_id == property_id, ARAsset.status == "published")
    )
    vr = db.scalar(
        select(VRTourConfig).where(
            VRTourConfig.property_id == property_id,
            VRTourConfig.status == "published",
        )
    )
    variants = ar.variants_json if ar else {}
    web_asset = variants.get("web") or variants.get("web_splat") or (vr.fallback_url if vr else None)
    return {
        "ar": None
        if not ar
        else {
            "id": ar.id,
            "variants": variants,
            "placement": ar.placement_profile_json,
            "scale_meters": ar.scale_meters,
        },
        "vr": None
        if not vr
        else {
            "id": vr.id,
            "navigation": vr.navigation_json,
            "comfort": vr.comfort_json,
            "fallback_url": vr.fallback_url,
        },
        "web_asset": web_asset,
        "fallback": "gallery_3d",
    }


@router.post("/ar-assets/{asset_id}/sessions", status_code=201)
def ar_session(
    asset_id: str,
    payload: ARSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = db.get(ARAsset, asset_id)
    if not asset or asset.status != "published":
        raise HTTPException(status_code=404, detail="AR asset not found")
    item = ARSession(
        asset_id=asset.id,
        user_id=user.id,
        device_json=payload.device,
        status="started",
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "status": item.status}


@router.post("/vr-tours/{tour_id}/sessions", status_code=201)
def vr_session(
    tour_id: str,
    payload: VRSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tour = db.get(VRTourConfig, tour_id)
    if not tour or tour.status != "published":
        raise HTTPException(status_code=404, detail="VR tour not found")
    item = VRSession(
        tour_id=tour.id,
        user_id=user.id,
        device_profile=payload.device_profile,
        performance_json=payload.performance,
        status="started",
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "status": item.status, "comfort": tour.comfort_json}
