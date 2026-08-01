from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import ARAsset, ARSession, CaptureSession, ReconstructionArtifact, ReconstructionJob, User, VRSession, VRTourConfig
from ..p2_dependencies import get_org_context
from ..p2_schemas import ARSessionCreate, AssetReviewCreate, CaptureFileCreate, CaptureSessionCreate, ReconstructionStartCreate, VRSessionCreate
from ..services.p2_spatial import add_capture_file, process_reconstruction, review_artifact, start_reconstruction
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router=APIRouter(tags=["p2-spatial"])

@router.post("/captures",status_code=201)
def capture(payload:CaptureSessionCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_feature(db,ctx.organization.id,"reconstruction"); require_org_permission(ctx,"spatial.write")
    from ..models import Property
    prop=db.get(Property,payload.property_id)
    if not prop or prop.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Property not found")
    item=CaptureSession(organization_id=ctx.organization.id,property_id=prop.id,created_by_user_id=ctx.user.id,status="collecting",capture_type=payload.capture_type,requirements_json=payload.requirements or {"minimum_images":12,"coverage":"360 degrees"}); db.add(item); db.commit(); return {"id":item.id,"status":item.status,"requirements":item.requirements_json}

@router.post("/captures/{session_id}/files",status_code=201)
def capture_file(session_id:str,payload:CaptureFileCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    session=db.get(CaptureSession,session_id)
    if not session or session.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Capture session not found")
    try: item=add_capture_file(db,session,url=payload.url,sha256=payload.sha256,mime_type=payload.mime_type,size_bytes=payload.size_bytes,metadata=payload.metadata)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    return {"id":item.id,"sha256":item.sha256,"mime_type":item.mime_type}

@router.post("/captures/{session_id}/reconstruct",status_code=202)
def reconstruct(session_id:str,payload:ReconstructionStartCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    session=db.get(CaptureSession,session_id)
    if not session or session.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Capture session not found")
    try: job=start_reconstruction(db,session,payload.representation)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    return {"id":job.id,"status":job.status,"stage":job.stage,"representation":job.representation}

@router.post("/reconstruction-jobs/{job_id}/run-local")
def run_local(job_id:str,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"spatial.write"); job=db.get(ReconstructionJob,job_id); session=db.get(CaptureSession,job.session_id) if job else None
    if not job or not session or session.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Job not found")
    return process_reconstruction(db,job.id)

@router.post("/reconstruction-artifacts/{artifact_id}/review")
def review(artifact_id:str,payload:AssetReviewCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    if ctx.member.role not in {"owner","manager","reviewer"}: raise HTTPException(status_code=403,detail="Reviewer role required")
    artifact=db.get(ReconstructionArtifact,artifact_id); job=db.get(ReconstructionJob,artifact.job_id) if artifact else None; session=db.get(CaptureSession,job.session_id) if job else None
    if not artifact or not session or session.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Artifact not found")
    item=review_artifact(db,artifact,ctx.user.id,payload.status,payload.notes); return {"id":item.id,"status":item.status,"published":artifact.published}

@router.get("/properties/{property_id}/immersive")
def immersive(property_id:str,db:Session=Depends(get_db)):
    ar=db.scalar(select(ARAsset).where(ARAsset.property_id==property_id,ARAsset.status=="published")); vr=db.scalar(select(VRTourConfig).where(VRTourConfig.property_id==property_id,VRTourConfig.status=="published"))
    return {"ar":None if not ar else {"id":ar.id,"variants":ar.variants_json,"placement":ar.placement_profile_json,"scale_meters":ar.scale_meters},"vr":None if not vr else {"id":vr.id,"navigation":vr.navigation_json,"comfort":vr.comfort_json,"fallback_url":vr.fallback_url},"fallback":"gallery_3d"}

@router.post("/ar-assets/{asset_id}/sessions",status_code=201)
def ar_session(asset_id:str,payload:ARSessionCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    asset=db.get(ARAsset,asset_id)
    if not asset or asset.status!="published": raise HTTPException(status_code=404,detail="AR asset not found")
    item=ARSession(asset_id=asset.id,user_id=user.id,device_json=payload.device,status="started"); db.add(item); db.commit(); return {"id":item.id,"status":item.status}

@router.post("/vr-tours/{tour_id}/sessions",status_code=201)
def vr_session(tour_id:str,payload:VRSessionCreate,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    tour=db.get(VRTourConfig,tour_id)
    if not tour or tour.status!="published": raise HTTPException(status_code=404,detail="VR tour not found")
    item=VRSession(tour_id=tour.id,user_id=user.id,device_profile=payload.device_profile,performance_json=payload.performance,status="started"); db.add(item); db.commit(); return {"id":item.id,"status":item.status,"comfort":tour.comfort_json}
