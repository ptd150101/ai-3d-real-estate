from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Agency, Agent, Appointment, FeatureKillSwitch, ListingQuota, MarketplacePlan,
    Organization, OrganizationFeatureFlag, OrganizationMember, OrganizationRole,
    OrganizationSubscription, Project, Property, TenantAuditExport, User, Lead,
)

SYSTEM_ROLES: dict[str, list[str]] = {
    "owner": ["*"],
    "manager": ["organization.read", "members.write", "properties.write", "finance.read", "contracts.write", "ai.use", "spatial.write"],
    "agent": ["organization.read", "properties.write", "leads.write", "contracts.read", "ai.use", "spatial.write"],
    "reviewer": ["organization.read", "contracts.review", "assets.review"],
    "finance": ["organization.read", "finance.read", "finance.write", "contracts.read"],
    "analyst": ["organization.read", "analytics.read", "ai.manage"],
}
DEFAULT_FEATURES = ["payments", "contracts", "valuation", "recommendations", "reconstruction", "ar", "vr", "mobile", "mlops"]

@dataclass
class OrgContext:
    organization: Organization
    member: OrganizationMember
    user: User


def ensure_default_tenant(db: Session) -> Organization:
    org = db.scalar(select(Organization).order_by(Organization.created_at).limit(1))
    if not org:
        agency = db.scalar(select(Agency).order_by(Agency.created_at).limit(1))
        org = Organization(name=agency.name if agency else "Nestora Prime", slug="nestora-prime", status="active", verified=bool(agency and agency.verified))
        db.add(org); db.flush()
    agencies = list(db.scalars(select(Agency).where(Agency.organization_id.is_(None))))
    for agency in agencies: agency.organization_id = org.id
    for model in (Agent, Project, Property, Appointment, Lead):
        for item in db.scalars(select(model).where(model.organization_id.is_(None))): item.organization_id = org.id
    users = list(db.scalars(select(User).where(User.role.in_(["admin", "agent"]))))
    for user in users:
        if not db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id==org.id, OrganizationMember.user_id==user.id)):
            role = "owner" if user.role == "admin" else "agent"
            db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, status="active"))
    for name, permissions in SYSTEM_ROLES.items():
        if not db.scalar(select(OrganizationRole).where(OrganizationRole.organization_id==org.id, OrganizationRole.name==name)):
            db.add(OrganizationRole(organization_id=org.id, name=name, permissions_json=permissions, system=True))
    plan = db.scalar(select(MarketplacePlan).where(MarketplacePlan.code=="pro"))
    if not plan:
        plan=MarketplacePlan(code="pro", name="Professional", monthly_price=0, entitlements_json={k:True for k in DEFAULT_FEATURES}, active=True); db.add(plan); db.flush()
    if not db.scalar(select(OrganizationSubscription).where(OrganizationSubscription.organization_id==org.id)):
        db.add(OrganizationSubscription(organization_id=org.id, plan_id=plan.id, status="active", current_period_end=datetime.now(timezone.utc)+timedelta(days=3650)))
    if not db.scalar(select(ListingQuota).where(ListingQuota.organization_id==org.id, ListingQuota.key=="published_listings")):
        db.add(ListingQuota(organization_id=org.id, key="published_listings", limit_value=1000, used_value=int(db.scalar(select(Property).where(Property.organization_id==org.id).count()) or 0) if False else 0))
    for key in DEFAULT_FEATURES:
        if not db.scalar(select(OrganizationFeatureFlag).where(OrganizationFeatureFlag.organization_id==org.id, OrganizationFeatureFlag.key==key)):
            db.add(OrganizationFeatureFlag(organization_id=org.id, key=key, enabled=True, config_json={}))
    db.commit(); db.refresh(org); return org


def resolve_org_context(db: Session, user: User, requested_id: str | None = None) -> OrgContext:
    stmt=select(OrganizationMember).where(OrganizationMember.user_id==user.id, OrganizationMember.status=="active")
    if requested_id: stmt=stmt.where(OrganizationMember.organization_id==requested_id)
    member=db.scalar(stmt.order_by(OrganizationMember.created_at).limit(1))
    if not member:
        if user.role == "admin":
            org=db.get(Organization, requested_id) if requested_id else db.scalar(select(Organization).order_by(Organization.created_at).limit(1))
            if org:
                member=OrganizationMember(organization_id=org.id,user_id=user.id,role="owner",status="active")
                db.add(member); db.commit(); db.refresh(member)
        if not member: raise HTTPException(status_code=403,detail="No active organization membership")
    org=db.get(Organization,member.organization_id)
    if not org or org.status!="active": raise HTTPException(status_code=403,detail="Organization unavailable")
    return OrgContext(org,member,user)


def require_org_permission(ctx: OrgContext, permission: str) -> None:
    perms=SYSTEM_ROLES.get(ctx.member.role,[])
    if "*" not in perms and permission not in perms: raise HTTPException(status_code=403,detail=f"Missing organization permission: {permission}")


def feature_enabled(db: Session, organization_id: str, key: str) -> bool:
    kill=db.scalar(select(FeatureKillSwitch).where(FeatureKillSwitch.organization_id==organization_id, FeatureKillSwitch.key==key))
    global_kill=db.scalar(select(FeatureKillSwitch).where(FeatureKillSwitch.organization_id.is_(None), FeatureKillSwitch.key==key))
    if (kill and kill.enabled) or (global_kill and global_kill.enabled): return False
    flag=db.scalar(select(OrganizationFeatureFlag).where(OrganizationFeatureFlag.organization_id==organization_id, OrganizationFeatureFlag.key==key))
    return bool(flag and flag.enabled)


def require_feature(db: Session, organization_id: str, key: str) -> None:
    if not feature_enabled(db,organization_id,key): raise HTTPException(status_code=403,detail=f"Feature disabled: {key}")


def create_tenant_export(db: Session, ctx: OrgContext) -> TenantAuditExport:
    require_org_permission(ctx,"organization.read")
    item=TenantAuditExport(organization_id=ctx.organization.id, requested_by_user_id=ctx.user.id, status="processing")
    db.add(item); db.flush()
    payload={
        "organization":{"id":ctx.organization.id,"name":ctx.organization.name,"slug":ctx.organization.slug},
        "members":[{"user_id":m.user_id,"role":m.role,"status":m.status} for m in db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id==ctx.organization.id))],
        "properties":[{"id":p.id,"slug":p.slug,"title":p.title,"status":p.status} for p in db.scalars(select(Property).where(Property.organization_id==ctx.organization.id))],
        "exported_at":datetime.now(timezone.utc).isoformat(),
    }
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
    checksum=hashlib.sha256(raw).hexdigest()
    root=get_settings().storage_path/"private"/"tenant-exports"; root.mkdir(parents=True,exist_ok=True)
    path=root/f"{item.id}.json"; path.write_bytes(raw)
    item.object_url=f"/storage/private/tenant-exports/{item.id}.json"; item.checksum=checksum; item.status="completed"
    db.commit(); db.refresh(item); return item
