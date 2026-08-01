from __future__ import annotations

import hashlib, secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import AgencyVerificationCase, ListingQuota, Organization, OrganizationFeatureFlag, OrganizationInvitation, OrganizationMember, User
from ..p2_dependencies import get_org_context
from ..p2_schemas import FeatureFlagUpdate, OrganizationCreate, OrganizationInviteCreate, OrganizationMemberUpdate
from ..services.p2_tenant import OrgContext, create_tenant_export, require_org_permission

router=APIRouter(prefix="/organizations",tags=["p2-organizations"])

def org_dict(org): return {"id":org.id,"name":org.name,"slug":org.slug,"status":org.status,"verified":org.verified,"settings":org.settings_json}

@router.get("/me")
def my_organizations(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    rows=[]
    for m in db.scalars(select(OrganizationMember).where(OrganizationMember.user_id==user.id,OrganizationMember.status=="active")):
        org=db.get(Organization,m.organization_id)
        if org: rows.append({**org_dict(org),"membership":{"id":m.id,"role":m.role,"status":m.status}})
    return rows

@router.post("")
def create_organization(payload:OrganizationCreate,db:Session=Depends(get_db),user:User=Depends(require_roles("admin"))):
    if db.scalar(select(Organization).where(Organization.slug==payload.slug)): raise HTTPException(status_code=409,detail="Organization slug exists")
    org=Organization(name=payload.name,slug=payload.slug,status="active",verified=False); db.add(org); db.flush(); db.add(OrganizationMember(organization_id=org.id,user_id=user.id,role="owner",status="active")); db.add(ListingQuota(organization_id=org.id,key="published_listings",limit_value=50,used_value=0)); db.commit(); return org_dict(org)

@router.get("/current")
def current(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    flags=[{"key":x.key,"enabled":x.enabled,"config":x.config_json} for x in db.scalars(select(OrganizationFeatureFlag).where(OrganizationFeatureFlag.organization_id==ctx.organization.id))]
    quotas=[{"key":x.key,"limit":x.limit_value,"used":x.used_value} for x in db.scalars(select(ListingQuota).where(ListingQuota.organization_id==ctx.organization.id))]
    return {**org_dict(ctx.organization),"member_role":ctx.member.role,"flags":flags,"quotas":quotas}

@router.get("/members")
def members(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"organization.read"); result=[]
    for m in db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id==ctx.organization.id)):
        u=db.get(User,m.user_id); result.append({"id":m.id,"user_id":m.user_id,"email":u.email if u else None,"full_name":u.full_name if u else None,"role":m.role,"status":m.status})
    return result

@router.post("/invitations")
def invite(payload:OrganizationInviteCreate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"members.write"); raw=secrets.token_urlsafe(32); item=OrganizationInvitation(organization_id=ctx.organization.id,email=str(payload.email).lower(),role=payload.role,token_hash=hashlib.sha256(raw.encode()).hexdigest(),status="pending",expires_at=datetime.now(timezone.utc)+timedelta(days=7)); db.add(item); db.commit(); return {"id":item.id,"email":item.email,"role":item.role,"status":item.status,"invite_token":raw if __import__('app.config',fromlist=['get_settings']).get_settings().environment!="production" else None}

@router.patch("/members/{member_id}")
def update_member(member_id:str,payload:OrganizationMemberUpdate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    require_org_permission(ctx,"members.write"); item=db.get(OrganizationMember,member_id)
    if not item or item.organization_id!=ctx.organization.id: raise HTTPException(status_code=404,detail="Member not found")
    if payload.role: item.role=payload.role
    if payload.status: item.status=payload.status
    db.commit(); return {"id":item.id,"role":item.role,"status":item.status}

@router.put("/features/{key}")
def update_feature(key:str,payload:FeatureFlagUpdate,ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    if ctx.member.role not in {"owner","manager"}: raise HTTPException(status_code=403,detail="Owner or manager required")
    item=db.scalar(select(OrganizationFeatureFlag).where(OrganizationFeatureFlag.organization_id==ctx.organization.id,OrganizationFeatureFlag.key==key))
    if not item: item=OrganizationFeatureFlag(organization_id=ctx.organization.id,key=key); db.add(item)
    item.enabled=payload.enabled; item.config_json=payload.config_json; db.commit(); return {"key":key,"enabled":item.enabled,"config":item.config_json}

@router.post("/exports")
def export_tenant(ctx:OrgContext=Depends(get_org_context),db:Session=Depends(get_db)):
    item=create_tenant_export(db,ctx); return {"id":item.id,"status":item.status,"url":item.object_url,"checksum":item.checksum}

@router.get("/platform/verification",dependencies=[Depends(require_roles("admin"))])
def verification_queue(db:Session=Depends(get_db)):
    return [{"id":x.id,"organization_id":x.organization_id,"status":x.status,"documents":x.documents_json,"notes":x.notes} for x in db.scalars(select(AgencyVerificationCase).order_by(AgencyVerificationCase.created_at.desc()))]

@router.patch("/platform/verification/{case_id}",dependencies=[Depends(require_roles("admin"))])
def review_verification(case_id:str,status:str,notes:str|None=None,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    item=db.get(AgencyVerificationCase,case_id)
    if not item: raise HTTPException(status_code=404,detail="Case not found")
    item.status=status; item.notes=notes; item.reviewer_user_id=user.id
    org=db.get(Organization,item.organization_id)
    if status=="approved": org.verified=True
    db.commit(); return {"id":item.id,"status":item.status}
