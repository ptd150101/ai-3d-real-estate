from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MLEvaluation, MLDeployment, MLModelVersion, MLUsageRecord
from ..p2_dependencies import get_org_context
from ..p2_schemas import MLArtifactCreate, MLEvaluationCreate, MLModelCreate, MLPromoteCreate
from ..services.model_runtime import check_deployment_health
from ..services.p2_spatial import create_ml_artifact, promote_ml_model
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router = APIRouter(prefix="/mlops", tags=["p2-mlops"])


@router.post("/artifacts", status_code=201)
def artifact(
    payload: MLArtifactCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "mlops")
    require_org_permission(ctx, "ai.manage")
    item = create_ml_artifact(
        db,
        organization_id=ctx.organization.id,
        kind=payload.kind,
        uri=payload.uri,
        content_hash=payload.sha256,
        metadata=payload.metadata,
    )
    return {"id": item.id, "sha256": item.sha256, "uri": item.uri}


@router.post("/models", status_code=201)
def model(
    payload: MLModelCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "ai.manage")
    item = MLModelVersion(
        organization_id=ctx.organization.id,
        name=payload.name,
        task=payload.task,
        version=payload.version,
        status="candidate",
        artifact_id=payload.artifact_id,
        feature_version=payload.feature_version,
        metrics_json=payload.metrics,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "status": item.status}


@router.post("/models/{model_id}/evaluations", status_code=201)
def evaluation(
    model_id: str,
    payload: MLEvaluationCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "ai.manage")
    model = db.get(MLModelVersion, model_id)
    if not model or model.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Model not found")
    item = MLEvaluation(
        model_version_id=model.id,
        dataset_version=payload.dataset_version,
        metrics_json=payload.metrics,
        passed=payload.passed,
        gate_json=payload.gate,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "passed": item.passed}


@router.post("/models/{model_id}/promote")
def promote(
    model_id: str,
    payload: MLPromoteCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "ai.manage")
    model = db.get(MLModelVersion, model_id)
    if not model or model.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        deployment = promote_ml_model(db, model, payload.environment, payload.traffic_percent)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "id": deployment.id,
        "model_id": model.id,
        "environment": deployment.environment,
        "traffic_percent": deployment.traffic_percent,
        "status": deployment.status,
    }


def _rollback(db: Session, deployment: MLDeployment, model: MLModelVersion) -> MLDeployment | None:
    deployment.status = "rolled_back"
    deployment.traffic_percent = 0
    deployment.ended_at = datetime.now(timezone.utc)
    model.status = "retired"
    previous = db.execute(
        select(MLDeployment, MLModelVersion)
        .join(MLModelVersion, MLDeployment.model_version_id == MLModelVersion.id)
        .where(
            MLModelVersion.organization_id == model.organization_id,
            MLModelVersion.task == model.task,
            MLDeployment.environment == deployment.environment,
            MLDeployment.id != deployment.id,
            MLDeployment.status.in_(["active", "retired"]),
        )
        .order_by(MLDeployment.started_at.desc())
        .limit(1)
    ).first()
    restored: MLDeployment | None = None
    if previous:
        restored, restored_model = previous
        restored.status = "active"
        restored.traffic_percent = 100
        restored.ended_at = None
        restored_model.status = "production"
    db.commit()
    return restored


@router.post("/deployments/{deployment_id}/rollback")
def rollback(
    deployment_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "ai.manage")
    deployment = db.get(MLDeployment, deployment_id)
    model = db.get(MLModelVersion, deployment.model_version_id) if deployment else None
    if not deployment or not model or model.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Deployment not found")
    restored = _rollback(db, deployment, model)
    return {
        "id": deployment.id,
        "status": deployment.status,
        "restored_deployment_id": restored.id if restored else None,
    }


@router.post("/deployments/{deployment_id}/health")
def deployment_health(
    deployment_id: str,
    auto_rollback: bool = True,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "ai.manage")
    deployment = db.get(MLDeployment, deployment_id)
    model = db.get(MLModelVersion, deployment.model_version_id) if deployment else None
    if not deployment or not model or model.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Deployment not found")
    health = check_deployment_health(db, deployment)
    db.add(
        MLUsageRecord(
            organization_id=ctx.organization.id,
            job_type="deployment_health",
            units=1,
            cost_amount=0,
            metadata_json={"deployment_id": deployment.id, **health},
        )
    )
    restored = None
    if not health.get("healthy") and auto_rollback and deployment.status == "active":
        restored = _rollback(db, deployment, model)
    else:
        db.commit()
    return {
        "deployment_id": deployment.id,
        **health,
        "auto_rolled_back": bool(restored or deployment.status == "rolled_back"),
        "restored_deployment_id": restored.id if restored else None,
    }


@router.get("/dashboard")
def dashboard(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "analytics.read")
    models = [
        {
            "id": item.id,
            "name": item.name,
            "task": item.task,
            "version": item.version,
            "status": item.status,
            "metrics": item.metrics_json,
        }
        for item in db.scalars(
            select(MLModelVersion).where(MLModelVersion.organization_id == ctx.organization.id)
        )
    ]
    deployments = [
        {
            "id": deployment.id,
            "model_id": model.id,
            "task": model.task,
            "environment": deployment.environment,
            "status": deployment.status,
            "traffic_percent": deployment.traffic_percent,
            "started_at": deployment.started_at,
        }
        for deployment, model in db.execute(
            select(MLDeployment, MLModelVersion)
            .join(MLModelVersion, MLDeployment.model_version_id == MLModelVersion.id)
            .where(MLModelVersion.organization_id == ctx.organization.id)
        )
    ]
    usage = list(
        db.scalars(
            select(MLUsageRecord).where(MLUsageRecord.organization_id == ctx.organization.id)
        )
    )
    return {
        "models": models,
        "deployments": deployments,
        "usage": {
            "units": sum(item.units for item in usage),
            "cost": round(sum(item.cost_amount for item in usage), 4),
        },
        "governance": {
            "evaluation_gate_required": True,
            "weighted_canary_routing": True,
            "health_auto_rollback": True,
            "data_deletion_propagation": "tracked by artifact lineage",
        },
    }
