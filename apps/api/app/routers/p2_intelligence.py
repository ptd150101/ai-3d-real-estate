from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import RecommendationFeedback, RecommendationProfile, User, ValuationEvaluation, ValuationModelVersion, ValuationRequest, ValuationResult
from ..p2_dependencies import get_org_context
from ..p2_schemas import DriftCreate, ModelEvaluationCreate, RecommendationFeedbackCreate, RecommendationProfileUpdate, ValuationCreate, ValuationModelCreate, ValuationOverrideCreate
from ..services.p2_intelligence import promote_valuation_model, recommend, record_drift, value_property
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router=APIRouter(tags=["p2-intelligence"])

@router.post("/valuations",status_code=201)
def valuation(payload:ValuationCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    org_id=None
    if payload.property_id:
        from ..models import Property
        prop=db.get(Property,payload.property_id); org_id=prop.organization_id if prop else None
        if org_id: require_feature(db,org_id,"valuation")
    request,result,comps=value_property(db,user=user,organization_id=org_id,property_id=payload.property_id,inputs=payload.model_dump(exclude={"property_id"},exclude_none=True)); return {"id":request.id,"status":result.status,"estimate":result.override_value or result.estimate,"range":{"lower":result.lower_bound,"upper":result.upper_bound},"confidence":result.confidence,"explanation":result.explanation_json,"feature_snapshot":result.feature_snapshot_json,"comparables":[{"property_id":x.property_id,"similarity":x.similarity,"adjustments":x.adjustments_json} for x in comps]}

@router.get("/valuations/{request_id}")
def get_valuation(request_id:str,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    request=db.get(ValuationRequest,request_id)
    if not request or (request.user_id!=user.id and user.role not in {"admin","agent"}): raise HTTPException(status_code=404,detail="Valuation not found")
    result=db.scalar(select(ValuationResult).where(ValuationResult.request_id==request.id)); return {"id":request.id,"status":result.status,"estimate":result.override_value or result.estimate,"original_estimate":result.estimate,"lower":result.lower_bound,"upper":result.upper_bound,"confidence":result.confidence,"explanation":result.explanation_json}

@router.post("/valuations/{request_id}/override")
def override(request_id:str,payload:ValuationOverrideCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); request=db.get(ValuationRequest,request_id)
    if not request or request.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Valuation not found")
    result=db.scalar(select(ValuationResult).where(ValuationResult.request_id==request.id)); result.override_value=payload.value; result.override_reason=payload.reason; db.commit(); return {"id":request.id,"estimate":result.override_value,"original_estimate":result.estimate,"reason":result.override_reason}

@router.get("/recommendations")
def recommendations(limit:int=Query(12,ge=1,le=50),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    return {"items":recommend(db,user,limit),"fallback":"deterministic search is used when personalization is disabled"}

@router.post("/recommendations/feedback",status_code=201)
def feedback(payload:RecommendationFeedbackCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=RecommendationFeedback(user_id=user.id,property_id=payload.property_id,action=payload.action,metadata_json=payload.metadata); db.add(item); db.commit(); return {"id":item.id,"action":item.action}

@router.patch("/recommendations/profile")
def profile(payload:RecommendationProfileUpdate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=db.scalar(select(RecommendationProfile).where(RecommendationProfile.user_id==user.id))
    if not item: item=RecommendationProfile(user_id=user.id,enabled=True,signals_json={}); db.add(item)
    if payload.enabled is not None: item.enabled=payload.enabled
    if payload.reset: item.signals_json={}; item.reset_at=datetime.now(timezone.utc); db.query(RecommendationFeedback).filter(RecommendationFeedback.user_id==user.id).delete()
    db.commit(); return {"enabled":item.enabled,"reset_at":item.reset_at}

@router.post("/valuation-models",status_code=201)
def create_model(payload:ValuationModelCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); item=ValuationModelVersion(organization_id=ctx.organization.id,name=payload.name,version=payload.version,status="candidate",feature_version=payload.feature_version,metrics_json=payload.metrics,baseline_metrics_json=payload.baseline_metrics,trained_at=datetime.now(timezone.utc)); db.add(item); db.commit(); return {"id":item.id,"status":item.status}

@router.post("/valuation-models/{model_id}/evaluations",status_code=201)
def evaluate_model(model_id:str,payload:ModelEvaluationCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); model=db.get(ValuationModelVersion,model_id)
    if not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Model not found")
    item=ValuationEvaluation(model_version_id=model.id,split_type=payload.split_type,segment=payload.segment,metrics_json=payload.metrics,passed=payload.passed); db.add(item); db.commit(); return {"id":item.id,"passed":item.passed}

@router.post("/valuation-models/{model_id}/promote")
def promote(model_id:str,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); model=db.get(ValuationModelVersion,model_id)
    if not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Model not found")
    try: model=promote_valuation_model(db,model)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    return {"id":model.id,"status":model.status}

@router.post("/valuation-models/{model_id}/drift")
def drift(model_id:str,payload:DriftCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"ai.manage"); model=db.get(ValuationModelVersion,model_id)
    if not model or model.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Model not found")
    item=record_drift(db,model,payload.segment,payload.value,payload.threshold); return {"id":item.id,"status":item.status,"model_status":model.status}
