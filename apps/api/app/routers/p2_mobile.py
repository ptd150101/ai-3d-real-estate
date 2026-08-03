from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import Organization, OrganizationMember, Property, User
from ..p2_dependencies import get_org_context
from ..p2_schemas import (
    MobileDeviceCreate,
    MobileLoginCreate,
    MobileLogoutCreate,
    MobileMutationCreate,
    MobilePushCreate,
    MobileRefreshCreate,
)
from ..services.p2_mobile import (
    apply_mutation,
    mobile_login,
    register_device,
    revoke_mobile_tokens,
    rotate_refresh_token,
    send_mobile_push,
)
from ..services.p2_tenant import OrgContext, require_feature, require_org_permission

router = APIRouter(prefix="/mobile", tags=["p2-mobile"])


@router.post("/auth/login")
def login(payload: MobileLoginCreate, db: Session = Depends(get_db)):
    return mobile_login(db, str(payload.email), payload.password, payload.device_id)


@router.post("/auth/refresh")
def refresh(payload: MobileRefreshCreate, db: Session = Depends(get_db)):
    return rotate_refresh_token(db, payload.refresh_token, payload.device_id)


@router.post("/auth/logout")
def logout(
    payload: MobileLogoutCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"revoked": revoke_mobile_tokens(db, user, payload.device_id, payload.refresh_token)}


@router.post("/devices", status_code=201)
def device(
    payload: MobileDeviceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = register_device(
        db,
        user,
        payload.device_id,
        payload.platform,
        payload.push_token,
        payload.app_version,
    )
    return {
        "id": item.id,
        "device_id": item.device_id,
        "platform": item.platform,
        "push_registered": bool(item.push_token),
    }


@router.post("/push")
def push(
    payload: MobilePushCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    require_feature(db, ctx.organization.id, "mobile")
    require_org_permission(ctx, "members.write")
    allowed = {
        member.user_id
        for member in db.scalars(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization.id,
                OrganizationMember.status == "active",
                OrganizationMember.user_id.in_(payload.user_ids),
            )
        )
    }
    return send_mobile_push(
        db,
        user_ids=sorted(allowed),
        title=payload.title,
        body=payload.body,
        data=payload.data,
    )


@router.post("/mutations", status_code=201)
def mutation(
    payload: MobileMutationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = apply_mutation(
        db,
        user,
        payload.device_id,
        payload.client_mutation_id,
        payload.mutation_type,
        payload.payload,
    )
    return {"id": item.id, "status": item.status, "result": item.result_json}


@router.get("/bootstrap")
def bootstrap(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    memberships = list(
        db.scalars(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == "active",
            )
        )
    )
    orgs = []
    organization_ids: list[str] = []
    for membership in memberships:
        org = db.get(Organization, membership.organization_id)
        if org:
            organization_ids.append(org.id)
            orgs.append(
                {"id": org.id, "name": org.name, "slug": org.slug, "role": membership.role}
            )
    property_query = select(Property).where(Property.status == "published")
    if organization_ids:
        property_query = property_query.where(Property.organization_id.in_(organization_ids))
    properties = [
        {
            "id": item.id,
            "organization_id": item.organization_id,
            "slug": item.slug,
            "title": item.title,
            "price": item.price,
            "district": item.district,
            "property_type": item.property_type,
            "has_3d": item.has_3d,
            "latitude": item.latitude,
            "longitude": item.longitude,
        }
        for item in db.scalars(property_query.order_by(Property.created_at.desc()).limit(100))
    ]
    return {
        "user": {"id": user.id, "full_name": user.full_name, "role": user.role},
        "organizations": orgs,
        "properties": properties,
        "deep_links": [
            "nestora://property/{slug}",
            "nestora://messages/{thread_id}",
            "nestora://capture/{session_id}",
        ],
    }
