from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ARAsset,
    CaptureFile,
    CaptureSession,
    GeneratedAssetReview,
    GPUWorkerPool,
    MLArtifact,
    MLDeployment,
    MLEvaluation,
    MLModelVersion,
    ReconstructionArtifact,
    ReconstructionJob,
    VRTourConfig,
)
from .reconstruction_backends import (
    ReconstructionError,
    ReconstructionInput,
    get_reconstruction_backend,
)
from .storage import (
    read_private_bytes,
    save_local_bytes,
    save_private_bytes,
    save_s3_bytes,
)

ALLOWED_CAPTURE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/webp",
    "video/mp4",
    "video/quicktime",
}


def add_capture_file(
    db: Session,
    session: CaptureSession,
    *,
    url: str,
    sha256: str,
    mime_type: str,
    size_bytes: int,
    metadata: dict[str, Any],
) -> CaptureFile:
    if mime_type not in ALLOWED_CAPTURE_TYPES:
        raise ValueError("Unsupported capture type")
    if size_bytes <= 0 or size_bytes > 500_000_000:
        raise ValueError("Invalid capture size")
    existing = db.scalar(
        select(CaptureFile).where(
            CaptureFile.session_id == session.id,
            CaptureFile.sha256 == sha256,
        )
    )
    if existing:
        return existing
    item = CaptureFile(
        session_id=session.id,
        url=url,
        sha256=sha256.lower(),
        mime_type=mime_type,
        size_bytes=size_bytes,
        metadata_json=metadata,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def start_reconstruction(
    db: Session,
    session: CaptureSession,
    representation: str = "mesh",
) -> ReconstructionJob:
    settings = get_settings()
    files = list(db.scalars(select(CaptureFile).where(CaptureFile.session_id == session.id)))
    minimum = 1 if settings.fixtures_allowed and settings.reconstruction_backend == "fixture" else 12
    if len(files) < minimum:
        raise ValueError(f"At least {minimum} capture files are required")
    image_count = sum(item.mime_type.startswith("image/") for item in files)
    quality = {
        "file_count": len(files),
        "image_count": image_count,
        "coverage": "good" if len(files) >= 20 else "minimum",
        "blur_check": all((item.metadata_json or {}).get("blur_score", 1) >= 0.2 for item in files),
        "exposure_check": all((item.metadata_json or {}).get("exposure_ok", True) for item in files),
        "overlap_check": len(files) >= minimum,
        "backend": settings.reconstruction_backend,
    }
    session.quality_report_json = quality
    if not quality["blur_check"] or not quality["exposure_check"]:
        session.status = "rejected"
        db.commit()
        raise ValueError("Capture quality insufficient")
    backend = get_reconstruction_backend()
    pool = db.scalar(
        select(GPUWorkerPool).where(
            GPUWorkerPool.organization_id == session.organization_id,
            GPUWorkerPool.name == backend.name,
            GPUWorkerPool.status == "active",
        )
    )
    if not pool:
        pool = GPUWorkerPool(
            organization_id=session.organization_id,
            name=backend.name,
            capabilities_json=["mesh", "gaussian_splat", "glb"],
            status="active",
            max_concurrency=1,
            hourly_cost=settings.gpu_hourly_cost,
        )
        db.add(pool)
        db.flush()
    job = ReconstructionJob(
        session_id=session.id,
        representation=representation,
        status="queued",
        stage="quality_check",
        progress=0,
        checkpoint_json={"backend": backend.name},
        worker_pool_id=pool.id,
    )
    session.status = "processing"
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _private_artifact(data: bytes, *, filename: str, content_type: str) -> str:
    storage_key, _, _ = save_private_bytes(
        data,
        filename,
        "reconstruction-artifacts",
        content_type,
    )
    return storage_key


def _publish_artifact(data: bytes, *, filename: str, content_type: str) -> str:
    settings = get_settings()
    if settings.storage_backend == "s3":
        url, _, _ = save_s3_bytes(data, filename, "generated", content_type)
    else:
        url, _, _ = save_local_bytes(data, filename, "generated", content_type)
    return url


def process_reconstruction(db: Session, job_id: str) -> dict[str, Any]:
    settings = get_settings()
    job = db.scalar(
        select(ReconstructionJob).where(ReconstructionJob.id == job_id).with_for_update()
    )
    if not job:
        raise ValueError("Job not found")
    if job.status == "processing":
        raise ValueError("Reconstruction job is already processing")
    if job.status in {"review", "completed"}:
        artifact = db.scalar(
            select(ReconstructionArtifact)
            .where(ReconstructionArtifact.job_id == job.id)
            .order_by(ReconstructionArtifact.version.desc())
        )
        return {"job_id": job.id, "artifact_id": artifact.id if artifact else None, "status": job.status}
    session = db.get(CaptureSession, job.session_id)
    files = list(db.scalars(select(CaptureFile).where(CaptureFile.session_id == session.id)))
    inputs = [
        ReconstructionInput(
            url=item.url,
            sha256=item.sha256,
            mime_type=item.mime_type,
            size_bytes=item.size_bytes,
        )
        for item in files
    ]
    backend = get_reconstruction_backend()
    job.status = "processing"
    job.error = None
    started = datetime.now(timezone.utc)
    db.commit()

    def progress(stage: str, value: int, details: dict[str, Any]) -> None:
        current = db.get(ReconstructionJob, job_id)
        if not current:
            return
        checkpoint = dict(current.checkpoint_json or {})
        checkpoint[stage] = {
            "status": "completed",
            "at": datetime.now(timezone.utc).isoformat(),
            **details,
        }
        current.stage = stage
        current.progress = max(current.progress, min(value, 95))
        current.checkpoint_json = checkpoint
        db.commit()

    try:
        result = backend.run(
            job_id=job.id,
            inputs=inputs,
            representation=job.representation,
            progress=progress,
        )
        output_bytes = result.output_path.read_bytes()
        if not output_bytes:
            raise ReconstructionError("Reconstruction output is empty")
        suffix = result.output_path.suffix.lower() or ".bin"
        content_type = mimetypes.guess_type(result.output_path.name)[0] or "application/octet-stream"
        storage_key = _private_artifact(
            output_bytes,
            filename=f"{job.id}{suffix}",
            content_type=content_type,
        )
        auxiliary: dict[str, dict[str, Any]] = {}
        for name, path in result.auxiliary_paths.items():
            data = path.read_bytes()
            aux_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            auxiliary[name] = {
                "storage_key": _private_artifact(
                    data,
                    filename=f"{job.id}-{name}{path.suffix.lower()}",
                    content_type=aux_type,
                ),
                "filename": path.name,
                "content_type": aux_type,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        version = int(
            db.scalar(
                select(ReconstructionArtifact.version)
                .where(ReconstructionArtifact.job_id == job.id)
                .order_by(ReconstructionArtifact.version.desc())
                .limit(1)
            )
            or 0
        ) + 1
        artifact = ReconstructionArtifact(
            job_id=job.id,
            asset_type=result.asset_type,
            url=storage_key,
            version=version,
            metadata_json={
                **result.metadata,
                "private": True,
                "content_type": content_type,
                "filename": result.output_path.name,
                "sha256": hashlib.sha256(output_bytes).hexdigest(),
                "auxiliary": auxiliary,
                "scale_meters": 1.0,
                "orientation": "Y-up",
            },
            published=False,
        )
        db.add(artifact)
        job = db.get(ReconstructionJob, job.id)
        elapsed_hours = max((datetime.now(timezone.utc) - started).total_seconds() / 3600, 0)
        pool = db.get(GPUWorkerPool, job.worker_pool_id) if job.worker_pool_id else None
        job.cost_amount = round(elapsed_hours * (pool.hourly_cost if pool else settings.gpu_hourly_cost), 6)
        job.status = "review"
        job.stage = "human_review"
        job.progress = 95
        session.status = "review"
        db.commit()
        db.refresh(artifact)
        return {"job_id": job.id, "artifact_id": artifact.id, "status": job.status}
    except Exception as exc:
        db.rollback()
        failed = db.get(ReconstructionJob, job_id)
        if failed:
            failed.status = "failed"
            failed.stage = "failed"
            failed.error = str(exc)[:4000]
            session = db.get(CaptureSession, failed.session_id)
            if session:
                session.status = "failed"
            db.commit()
        if isinstance(exc, ReconstructionError):
            raise ValueError(str(exc)) from exc
        raise


def review_artifact(
    db: Session,
    artifact: ReconstructionArtifact,
    reviewer_user_id: str,
    status: str,
    notes: str | None,
) -> GeneratedAssetReview:
    artifact = db.scalar(
        select(ReconstructionArtifact)
        .where(ReconstructionArtifact.id == artifact.id)
        .with_for_update()
    )
    item = db.scalar(
        select(GeneratedAssetReview).where(GeneratedAssetReview.artifact_id == artifact.id)
    )
    if not item:
        item = GeneratedAssetReview(
            artifact_id=artifact.id,
            reviewer_user_id=reviewer_user_id,
            status=status,
            notes=notes,
        )
        db.add(item)
    else:
        item.status = status
        item.notes = notes
        item.reviewer_user_id = reviewer_user_id
    if status == "approved" and not artifact.published:
        metadata = dict(artifact.metadata_json or {})
        content = read_private_bytes(artifact.url)
        suffix = Path(metadata.get("filename") or "artifact.bin").suffix or ".bin"
        content_type = metadata.get("content_type") or "application/octet-stream"
        artifact.url = _publish_artifact(
            content,
            filename=f"{artifact.id}{suffix}",
            content_type=content_type,
        )
        published_auxiliary: dict[str, Any] = {}
        for name, entry in (metadata.get("auxiliary") or {}).items():
            if not isinstance(entry, dict) or not entry.get("storage_key"):
                continue
            aux_data = read_private_bytes(entry["storage_key"])
            aux_suffix = Path(entry.get("filename") or name).suffix or ".bin"
            published_auxiliary[name] = {
                **entry,
                "url": _publish_artifact(
                    aux_data,
                    filename=f"{artifact.id}-{name}{aux_suffix}",
                    content_type=entry.get("content_type") or "application/octet-stream",
                ),
            }
        metadata["private"] = False
        metadata["published_auxiliary"] = published_auxiliary
        artifact.metadata_json = metadata
        artifact.published = True
        job = db.get(ReconstructionJob, artifact.job_id)
        job.status = "completed"
        job.progress = 100
        session = db.get(CaptureSession, job.session_id)
        session.status = "completed"
        variants: dict[str, str] = {}
        lower_url = artifact.url.lower()
        if lower_url.endswith(".glb") or artifact.asset_type == "glb":
            variants["web"] = artifact.url
            variants["android"] = artifact.url
        elif artifact.asset_type == "gaussian_splat":
            variants["web_splat"] = artifact.url
        else:
            variants["point_cloud"] = artifact.url
        usdz = (published_auxiliary.get("usdz") or {}).get("url")
        if usdz:
            variants["ios"] = usdz
        ar = db.scalar(select(ARAsset).where(ARAsset.source_artifact_id == artifact.id))
        if not ar:
            ar = ARAsset(
                organization_id=session.organization_id,
                property_id=session.property_id,
                source_artifact_id=artifact.id,
                status="published" if variants else "draft",
                variants_json=variants,
                placement_profile_json={"mode": "floor", "fallback": "3d"},
                scale_meters=float(metadata.get("scale_meters", 1)),
            )
            db.add(ar)
        else:
            ar.variants_json = variants
            ar.status = "published" if variants else "draft"
        tour = db.scalar(select(VRTourConfig).where(VRTourConfig.property_id == session.property_id))
        if not tour:
            tour = VRTourConfig(
                organization_id=session.organization_id,
                property_id=session.property_id,
                source_artifact_id=artifact.id,
                status="published",
                navigation_json={"teleport": True, "snap_turn_degrees": 30},
                comfort_json={"smooth_locomotion": False, "vignette": True},
                fallback_url=artifact.url,
            )
            db.add(tour)
        else:
            tour.source_artifact_id = artifact.id
            tour.status = "published"
            tour.fallback_url = artifact.url
    elif status == "rejected":
        job = db.get(ReconstructionJob, artifact.job_id)
        job.status = "rejected"
        session = db.get(CaptureSession, job.session_id)
        session.status = "rejected"
    db.commit()
    db.refresh(item)
    return item


def create_ml_artifact(
    db: Session,
    *,
    organization_id: str | None,
    kind: str,
    uri: str,
    content_hash: str,
    metadata: dict[str, Any],
) -> MLArtifact:
    existing = db.scalar(select(MLArtifact).where(MLArtifact.sha256 == content_hash))
    if existing:
        return existing
    item = MLArtifact(
        organization_id=organization_id,
        kind=kind,
        uri=uri,
        sha256=content_hash,
        metadata_json=metadata,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def promote_ml_model(
    db: Session,
    model: MLModelVersion,
    environment: str = "production",
    traffic_percent: int = 100,
) -> MLDeployment:
    evaluation = db.scalar(
        select(MLEvaluation).where(
            MLEvaluation.model_version_id == model.id,
            MLEvaluation.passed.is_(True),
        )
    )
    if not evaluation:
        raise ValueError("Model has no passing evaluation")
    if not model.artifact_id:
        raise ValueError("Model has no runtime artifact")
    artifact = db.get(MLArtifact, model.artifact_id)
    if not artifact:
        raise ValueError("Model artifact not found")
    settings = get_settings()
    endpoint = (artifact.metadata_json or {}).get("endpoint") or (
        artifact.uri if str(artifact.uri).startswith(("http://", "https://")) else None
    )
    if (
        environment == "production"
        and settings.environment.lower() in {"production", "prod"}
        and settings.ml_require_live_endpoint_in_production
        and not endpoint
    ):
        raise ValueError("Production model requires a live inference endpoint")
    traffic_percent = max(0, min(100, traffic_percent))
    active = list(
        db.scalars(
            select(MLDeployment)
            .join(MLModelVersion, MLDeployment.model_version_id == MLModelVersion.id)
            .where(
                MLModelVersion.organization_id == model.organization_id,
                MLModelVersion.task == model.task,
                MLDeployment.environment == environment,
                MLDeployment.status == "active",
            )
            .with_for_update()
        )
    )
    if traffic_percent == 100:
        for deployment in active:
            deployment.status = "retired"
            deployment.ended_at = datetime.now(timezone.utc)
    elif active:
        remaining = 100 - traffic_percent
        active[0].traffic_percent = remaining
        for deployment in active[1:]:
            deployment.status = "retired"
            deployment.ended_at = datetime.now(timezone.utc)
    model.status = "production"
    deployment = MLDeployment(
        model_version_id=model.id,
        environment=environment,
        status="active",
        traffic_percent=traffic_percent,
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    return deployment
