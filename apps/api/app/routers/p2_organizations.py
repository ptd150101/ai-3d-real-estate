from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..dependencies import get_current_user, require_roles
from ..models import (
    AgencyVerificationCase,
    ListingQuota,
    Organization,
    OrganizationFeatureFlag,
    OrganizationInvitation,
    OrganizationMember,
    TenantAuditExport,
    User,
)
from ..p2_dependencies import get_org_context
from ..p2_schemas import (
    FeatureFlagUpdate,
    OrganizationCreate,
    OrganizationInvitationAccept,
    OrganizationInviteCreate,
    OrganizationMemberUpdate,
)
from ..services.p2_tenant import (
    OrgContext,
    create_tenant_export,
    initialize_organization,
    require_org_permission,
)
from ..services.storage import StorageError, presign_private_url, read_private_bytes

router = APIRouter(prefix="/organizations", tags=["p2-organizations"])


def org_dict(org):
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "status": org.status,
        "verified": org.verified,
        "settings": org.settings_json,
    }


def _export_url(export_id: str) -> str:
    return f"/api/v1/organizations/exports/{export_id}/download"


@router.get("/me")
def my_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = []
    for member in db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
    ):
        org = db.get(Organization, member.organization_id)
        if org:
            rows.append(
                {
                    **org_dict(org),
                    "membership": {
                        "id": member.id,
                        "role": member.role,
                        "status": member.status,
                    },
                }
            )
    return rows


@router.post("")
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin")),
):
    if db.scalar(select(Organization).where(Organization.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Organization slug exists")
    org = Organization(
        name=payload.name,
        slug=payload.slug,
        status="active",
        verified=False,
    )
    db.add(org)
    db.flush()
    initialize_organization(db, org, owner_user_id=user.id)
    db.commit()
    db.refresh(org)
    return org_dict(org)


@router.get("/current")
def current(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    flags = [
        {"key": item.key, "enabled": item.enabled, "config": item.config_json}
        for item in db.scalars(
            select(OrganizationFeatureFlag).where(
                OrganizationFeatureFlag.organization_id == ctx.organization.id
            )
        )
    ]
    quotas = [
        {"key": item.key, "limit": item.limit_value, "used": item.used_value}
        for item in db.scalars(
            select(ListingQuota).where(ListingQuota.organization_id == ctx.organization.id)
        )
    ]
    return {
        **org_dict(ctx.organization),
        "member_role": ctx.member.role,
        "permissions": sorted(ctx.permissions),
        "flags": flags,
        "quotas": quotas,
    }


@router.get("/members")
def members(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "organization.read")
    result = []
    for member in db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ctx.organization.id
        )
    ):
        user = db.get(User, member.user_id)
        result.append(
            {
                "id": member.id,
                "user_id": member.user_id,
                "email": user.email if user else None,
                "full_name": user.full_name if user else None,
                "role": member.role,
                "status": member.status,
            }
        )
    return result


@router.post("/invitations")
def invite(
    payload: OrganizationInviteCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "members.write")
    email = str(payload.email).lower()
    existing = db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == ctx.organization.id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.status == "pending",
        )
    )
    if existing:
        existing.status = "revoked"
    raw = secrets.token_urlsafe(32)
    item = OrganizationInvitation(
        organization_id=ctx.organization.id,
        email=email,
        role=payload.role,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(item)
    db.commit()
    return {
        "id": item.id,
        "email": item.email,
        "role": item.role,
        "status": item.status,
        "invite_token": raw if get_settings().environment != "production" else None,
    }


@router.post("/invitations/accept")
def accept_invitation(
    payload: OrganizationInvitationAccept,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    item = db.scalar(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.token_hash == token_hash)
        .with_for_update()
    )
    if not item or item.status != "pending":
        raise HTTPException(status_code=404, detail="Invitation not found")
    expires_at = item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        item.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")
    if item.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="Invitation email does not match current user")

    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == item.organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if not member:
        member = OrganizationMember(
            organization_id=item.organization_id,
            user_id=user.id,
            role=item.role,
            status="active",
        )
        db.add(member)
    else:
        member.role = item.role
        member.status = "active"
    item.status = "accepted"
    item.accepted_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "organization_id": item.organization_id,
        "membership_id": member.id,
        "role": member.role,
        "status": member.status,
    }


@router.patch("/members/{member_id}")
def update_member(
    member_id: str,
    payload: OrganizationMemberUpdate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "members.write")
    item = db.get(OrganizationMember, member_id)
    if not item or item.organization_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Member not found")
    if item.user_id == ctx.user.id and payload.status == "suspended":
        raise HTTPException(status_code=409, detail="You cannot suspend your own membership")
    if payload.role:
        item.role = payload.role
    if payload.status:
        item.status = payload.status
    db.commit()
    return {"id": item.id, "role": item.role, "status": item.status}


@router.put("/features/{key}")
def update_feature(
    key: str,
    payload: FeatureFlagUpdate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "members.write")
    item = db.scalar(
        select(OrganizationFeatureFlag).where(
            OrganizationFeatureFlag.organization_id == ctx.organization.id,
            OrganizationFeatureFlag.key == key,
        )
    )
    if not item:
        item = OrganizationFeatureFlag(
            organization_id=ctx.organization.id,
            key=key,
        )
        db.add(item)
    item.enabled = payload.enabled
    item.config_json = payload.config_json
    db.commit()
    return {"key": key, "enabled": item.enabled, "config": item.config_json}


@router.post("/exports")
def export_tenant(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    item = create_tenant_export(db, ctx)
    return {
        "id": item.id,
        "status": item.status,
        "url": _export_url(item.id),
        "checksum": item.checksum,
    }


@router.get("/exports/{export_id}/download")
def download_tenant_export(
    export_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_org_permission(ctx, "organization.read")
    item = db.get(TenantAuditExport, export_id)
    if not item or item.organization_id != ctx.organization.id or not item.object_url:
        raise HTTPException(status_code=404, detail="Export not found")
    signed_url = presign_private_url(item.object_url)
    if signed_url:
        return RedirectResponse(signed_url, status_code=307, headers={"cache-control": "private, no-store"})
    try:
        content = read_private_bytes(item.object_url)
    except (StorageError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Export not found") from exc
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "content-disposition": f'attachment; filename="tenant-export-{item.id}.json"',
            "cache-control": "private, no-store",
        },
    )


@router.get("/platform/verification", dependencies=[Depends(require_roles("admin"))])
def verification_queue(db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "organization_id": item.organization_id,
            "status": item.status,
            "documents": item.documents_json,
            "notes": item.notes,
        }
        for item in db.scalars(
            select(AgencyVerificationCase).order_by(AgencyVerificationCase.created_at.desc())
        )
    ]


@router.patch("/platform/verification/{case_id}", dependencies=[Depends(require_roles("admin"))])
def review_verification(
    case_id: str,
    status: str,
    notes: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if status not in {"approved", "rejected", "needs_changes"}:
        raise HTTPException(status_code=422, detail="Invalid verification status")
    item = db.get(AgencyVerificationCase, case_id)
    if not item:
        raise HTTPException(status_code=404, detail="Case not found")
    item.status = status
    item.notes = notes
    item.reviewer_user_id = user.id
    org = db.get(Organization, item.organization_id)
    if status == "approved" and org:
        org.verified = True
    elif status == "rejected" and org:
        org.verified = False
    db.commit()
    return {"id": item.id, "status": item.status}
