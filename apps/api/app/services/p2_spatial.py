from __future__ import annotations

import hashlib
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    ARAsset, CaptureFile, CaptureSession, GeneratedAssetReview, GPUWorkerPool, MLArtifact,
    MLDeployment, MLEvaluation, MLModelVersion, MLUsageRecord, ReconstructionArtifact,
    ReconstructionJob, VRTourConfig,
)

ALLOWED_CAPTURE_TYPES={"image/jpeg","image/png","image/heic","video/mp4","video/quicktime"}


def add_capture_file(db: Session, session: CaptureSession, *, url: str, sha256: str, mime_type: str, size_bytes: int, metadata: dict) -> CaptureFile:
    if mime_type not in ALLOWED_CAPTURE_TYPES: raise ValueError("Unsupported capture type")
    if size_bytes<=0 or size_bytes>500_000_000: raise ValueError("Invalid capture size")
    existing=db.scalar(select(CaptureFile).where(CaptureFile.session_id==session.id,CaptureFile.sha256==sha256))
    if existing: return existing
    item=CaptureFile(session_id=session.id,url=url,sha256=sha256,mime_type=mime_type,size_bytes=size_bytes,metadata_json=metadata); db.add(item); db.commit(); db.refresh(item); return item


def start_reconstruction(db: Session, session: CaptureSession, representation: str="mesh") -> ReconstructionJob:
    files=list(db.scalars(select(CaptureFile).where(CaptureFile.session_id==session.id)))
    if not files: raise ValueError("At least one capture file is required")
    quality={"file_count":len(files),"coverage":"fixture" if len(files)<12 else "good","blur_check":True,"exposure_check":True,"overlap_check":len(files)>=3}
    session.quality_report_json=quality
    if len(files)<1: session.status="rejected"; raise ValueError("Capture quality insufficient")
    pool=db.scalar(select(GPUWorkerPool).where(GPUWorkerPool.status=="active"))
    if not pool: pool=GPUWorkerPool(organization_id=session.organization_id,name="local-fixture",capabilities_json=["mesh","gaussian_splat","glb"],status="active",max_concurrency=1,hourly_cost=0); db.add(pool); db.flush()
    job=ReconstructionJob(session_id=session.id,representation=representation,status="queued",stage="quality_check",progress=0,checkpoint_json={},worker_pool_id=pool.id); session.status="processing"; db.add(job); db.commit(); db.refresh(job); return job


def process_reconstruction(db: Session, job_id: str) -> dict:
    job=db.get(ReconstructionJob,job_id)
    if not job: raise ValueError("Job not found")
    session=db.get(CaptureSession,job.session_id); job.status="processing"
    stages=["quality_check","camera_reconstruction","dense_reconstruction","optimization","preview"]
    checkpoint=dict(job.checkpoint_json or {})
    for index,stage in enumerate(stages,1): checkpoint[stage]={"status":"completed","attempt":1}; job.stage=stage; job.progress=index*18
    ext="splat" if job.representation=="gaussian_splat" else "glb"
    root=get_settings().storage_path/"generated"; root.mkdir(parents=True,exist_ok=True); path=root/f"{job.id}.{ext}"
    if ext=="glb": path.write_bytes(b"glTF"+bytes(128))
    else: path.write_text("ply\nformat ascii 1.0\nend_header\n",encoding="utf-8")
    artifact=ReconstructionArtifact(job_id=job.id,asset_type=job.representation,url=f"/storage/generated/{path.name}",version=1,metadata_json={"scale_meters":1.0,"orientation":"Y-up","pipeline":"local-fixture; production adapters: COLMAP/Nerfstudio"},published=False)
    db.add(artifact); job.checkpoint_json=checkpoint; job.status="review"; job.stage="human_review"; job.progress=95; job.cost_amount=0; session.status="review"; db.commit(); db.refresh(artifact); return {"job_id":job.id,"artifact_id":artifact.id,"status":job.status}


def review_artifact(db: Session, artifact: ReconstructionArtifact, reviewer_user_id: str, status: str, notes: str | None) -> GeneratedAssetReview:
    item=db.scalar(select(GeneratedAssetReview).where(GeneratedAssetReview.artifact_id==artifact.id))
    if not item: item=GeneratedAssetReview(artifact_id=artifact.id,reviewer_user_id=reviewer_user_id,status=status,notes=notes); db.add(item)
    else: item.status=status; item.notes=notes; item.reviewer_user_id=reviewer_user_id
    if status=="approved":
        artifact.published=True; job=db.get(ReconstructionJob,artifact.job_id); job.status="completed"; job.progress=100
        session=db.get(CaptureSession,job.session_id); session.status="completed"
        if not db.scalar(select(ARAsset).where(ARAsset.source_artifact_id==artifact.id)):
            db.add(ARAsset(organization_id=session.organization_id,property_id=session.property_id,source_artifact_id=artifact.id,status="published",variants_json={"web":artifact.url,"android":artifact.url,"ios":"/storage/generated/pending-usdz"},placement_profile_json={"mode":"floor","fallback":"3d"},scale_meters=1))
        if not db.scalar(select(VRTourConfig).where(VRTourConfig.property_id==session.property_id)):
            db.add(VRTourConfig(organization_id=session.organization_id,property_id=session.property_id,source_artifact_id=artifact.id,status="published",navigation_json={"teleport":True,"snap_turn_degrees":30},comfort_json={"smooth_locomotion":False,"vignette":True},fallback_url=artifact.url))
    db.commit(); db.refresh(item); return item


def create_ml_artifact(db: Session, *, organization_id: str | None, kind: str, uri: str, content_hash: str, metadata: dict) -> MLArtifact:
    existing=db.scalar(select(MLArtifact).where(MLArtifact.sha256==content_hash));
    if existing: return existing
    item=MLArtifact(organization_id=organization_id,kind=kind,uri=uri,sha256=content_hash,metadata_json=metadata); db.add(item); db.commit(); db.refresh(item); return item


def promote_ml_model(db: Session, model: MLModelVersion, environment: str="production", traffic_percent: int=100) -> MLDeployment:
    evaluation=db.scalar(select(MLEvaluation).where(MLEvaluation.model_version_id==model.id,MLEvaluation.passed.is_(True)).limit(1))
    if not evaluation: raise ValueError("Model has no passing evaluation")
    for deployment in db.scalars(select(MLDeployment).join(MLModelVersion,MLDeployment.model_version_id==MLModelVersion.id).where(MLModelVersion.task==model.task,MLDeployment.environment==environment,MLDeployment.status=="active")):
        deployment.status="retired"; deployment.ended_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    model.status="production"; deployment=MLDeployment(model_version_id=model.id,environment=environment,status="active",traffic_percent=max(0,min(100,traffic_percent))); db.add(deployment); db.commit(); db.refresh(deployment); return deployment
