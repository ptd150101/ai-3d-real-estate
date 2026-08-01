from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MLEvaluation, MLDeployment, MLModelVersion, MLUsageRecord
from ..p2_dependencies import get_org_context
from ..p2_schemas import MLArtifactCreate, MLEvaluationCreate, MLModelCreate, MLPromoteCreate
from ..services.p2_spatial import create_ml_artifact, promote_ml_model
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router=APIRouter(prefix="/mlops",tags=["p2-mlops"])

@router.post("/artifacts",status_code=201)
def artifact(payload:MLArtifactCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_feature(db,ctx.organization.id,"mlops"); require_org_permission(ctx,"ai.manage"); item=create_ml_artifact(db,organization_id=ctx.organization.id,kind=payload.kind,uri=payload.uri,content_hash=payload.sha256,metadata=payload.metadata); return {"id":item.id,"sha256":item.sha256,"uri":item.uri}

@router.post("/models",status_code=201)
def model(payload:MLModelCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); item=MLModelVersion(organization_id=ctx.organization.id,name=payload.name,task=payload.task,version=payload.version,status="candidate",artifact_id=payload.artifact_id,feature_version=payload.feature_version,metrics_json=payload.metrics); db.add(item); db.commit(); return {"id":item.id,"status":item.status}

@router.post("/models/{model_id}/evaluations",status_code=201)
def evaluation(model_id:str,payload:MLEvaluationCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); model=db.get(MLModelVersion,model_id)
    if not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Model not found")
    item=MLEvaluation(model_version_id=model.id,dataset_version=payload.dataset_version,metrics_json=payload.metrics,passed=payload.passed,gate_json=payload.gate); db.add(item); db.commit(); return {"id":item.id,"passed":item.passed}

@router.post("/models/{model_id}/promote")
def promote(model_id:str,payload:MLPromoteCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); model=db.get(MLModelVersion,model_id)
    if not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Model not found")
    try: deployment=promote_ml_model(db,model,payload.environment,payload.traffic_percent)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    return {"id":deployment.id,"model_id":model.id,"environment":deployment.environment,"traffic_percent":deployment.traffic_percent,"status":deployment.status}

@router.post("/deployments/{deployment_id}/rollback")
def rollback(deployment_id:str,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); deployment=db.get(MLDeployment,deployment_id); model=db.get(MLModelVersion,deployment.model_version_id) if deployment else None
    if not deployment or not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Deployment not found")
    deployment.status="rolled_back"; deployment.ended_at=datetime.now(timezone.utc); model.status="retired"; db.commit(); return {"id":deployment.id,"status":deployment.status}

@router.get("/dashboard")
def dashboard(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"analytics.read")
    models=[{"id":x.id,"name":x.name,"task":x.task,"version":x.version,"status":x.status,"metrics":x.metrics_json} for x in db.scalars(select(MLModelVersion).where(MLModelVersion.organization_id==ctx.organization.id))]
    usage=list(db.scalars(select(MLUsageRecord).where(MLUsageRecord.organization_id==ctx.organization.id)))
    return {"models":models,"usage":{"units":sum(x.units for x in usage),"cost":round(sum(x.cost_amount for x in usage),4)},"governance":{"evaluation_gate_required":True,"rollback_supported":True,"data_deletion_propagation":"tracked by artifact lineage"}}
