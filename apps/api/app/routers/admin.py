from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import client_ip, require_roles
from ..models import (
    Appointment, AuditLog, ChatSession, Lead, Property, PropertyDocument, PropertyFeature,
    PropertyFloor, PropertyHotspot, PropertyMedia, PropertyModel3D, User,
)
from ..schemas import (
    AppointmentRead, AppointmentUpdate, AuditLogRead, DashboardMetrics, LeadRead, LeadUpdate,
    PropertyCreate, PropertyDetail, PropertyUpdate,
)
from ..services.audit import write_audit
from ..services.cache import cache
from ..services.search import property_query_options
from ..services.serializers import property_detail

router = APIRouter(prefix="/admin", tags=["admin"])


def replace_children(db: Session, item: Property, payload: PropertyCreate | PropertyUpdate) -> None:
    data = payload.model_dump(exclude_unset=True)
    if "features" in data:
        item.features.clear()
        item.features.extend(PropertyFeature(**feature) for feature in data["features"] or [])
    if "media" in data:
        item.media.clear()
        item.media.extend(PropertyMedia(**media) for media in data["media"] or [])
    if "documents" in data:
        item.documents.clear()
        item.documents.extend(PropertyDocument(**doc) for doc in data["documents"] or [])
    if "model_3d" in data:
        model_data = data["model_3d"]
        if model_data is None:
            item.model_3d = None
            item.has_3d = False
        else:
            floor_data = model_data.pop("floors", [])
            hotspot_data = model_data.pop("hotspots", [])
            model = item.model_3d or PropertyModel3D()
            for key, value in model_data.items(): setattr(model, key, value)
            model.floors.clear(); model.hotspots.clear()
            db.flush()
            for floor in floor_data:
                model.floors.append(PropertyFloor(**floor))
            db.flush()
            for hotspot in hotspot_data:
                model.hotspots.append(PropertyHotspot(**hotspot))
            item.model_3d = model
            item.has_3d = True


def property_to_dict(item: Property) -> dict:
    return {column.name: getattr(item, column.name) for column in Property.__table__.columns}


@router.get("/dashboard", response_model=DashboardMetrics)
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    return DashboardMetrics(
        properties_total=int(db.scalar(select(func.count(Property.id))) or 0),
        properties_published=int(db.scalar(select(func.count(Property.id)).where(Property.status == "published")) or 0),
        appointments_pending=int(db.scalar(select(func.count(Appointment.id)).where(Appointment.status == "pending")) or 0),
        leads_new=int(db.scalar(select(func.count(Lead.id)).where(Lead.status == "new")) or 0),
        chat_sessions_active=int(db.scalar(select(func.count(ChatSession.id)).where(ChatSession.status == "active")) or 0),
        views_total=int(db.scalar(select(func.coalesce(func.sum(Property.view_count), 0))) or 0),
    )


@router.get("/properties", response_model=list[PropertyDetail])
def list_admin_properties(status: str | None = None, q: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    stmt = select(Property).options(*property_query_options()).order_by(Property.updated_at.desc()).limit(limit)
    if status: stmt = stmt.where(Property.status == status)
    if q: stmt = stmt.where(Property.title.ilike(f"%{q}%"))
    return [property_detail(db, x) for x in db.scalars(stmt).unique()]


@router.post("/properties", response_model=PropertyDetail, status_code=201)
def create_property(payload: PropertyCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "agent"))):
    if db.scalar(select(Property).where(Property.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Slug already exists")
    data = payload.model_dump(exclude={"features", "media", "documents", "model_3d"})
    if data.get("status") == "published": data["published_at"] = datetime.now(timezone.utc)
    if data.get("is_verified"): data["verified_at"] = datetime.now(timezone.utc)
    item = Property(**data, owner_id=user.id)
    db.add(item); db.flush(); replace_children(db, item, payload)
    write_audit(db, actor=user, action="property.create", entity_type="property", entity_id=item.id, after=property_to_dict(item), ip_address=client_ip(request))
    db.commit(); cache.delete_prefix("properties:")
    item = db.scalar(select(Property).where(Property.id == item.id).options(*property_query_options()))
    return property_detail(db, item)


@router.get("/properties/{property_id}", response_model=PropertyDetail)
def get_admin_property(property_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = db.scalar(select(Property).where(Property.id == property_id).options(*property_query_options()))
    if not item: raise HTTPException(status_code=404, detail="Property not found")
    return property_detail(db, item)


@router.put("/properties/{property_id}", response_model=PropertyDetail)
def update_property(property_id: str, payload: PropertyUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "agent"))):
    item = db.scalar(select(Property).where(Property.id == property_id).options(*property_query_options()))
    if not item: raise HTTPException(status_code=404, detail="Property not found")
    if payload.slug and db.scalar(select(Property).where(Property.slug == payload.slug, Property.id != property_id)):
        raise HTTPException(status_code=409, detail="Slug already exists")
    before = property_to_dict(item)
    nested = {"features", "media", "documents", "model_3d"}
    for key, value in payload.model_dump(exclude_unset=True, exclude=nested).items(): setattr(item, key, value)
    if payload.status == "published" and not item.published_at: item.published_at = datetime.now(timezone.utc)
    if payload.is_verified and not item.verified_at: item.verified_at = datetime.now(timezone.utc)
    replace_children(db, item, payload)
    write_audit(db, actor=user, action="property.update", entity_type="property", entity_id=item.id, before=before, after=property_to_dict(item), ip_address=client_ip(request))
    db.commit(); cache.delete_prefix("properties:")
    item = db.scalar(select(Property).where(Property.id == property_id).options(*property_query_options()))
    return property_detail(db, item)


@router.post("/properties/{property_id}/publish", response_model=PropertyDetail)
def publish_property(property_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    item = db.get(Property, property_id)
    if not item: raise HTTPException(status_code=404, detail="Property not found")
    if not item.media: raise HTTPException(status_code=400, detail="At least one media item is required")
    item.status = "published"; item.published_at = datetime.now(timezone.utc)
    write_audit(db, actor=user, action="property.publish", entity_type="property", entity_id=item.id, ip_address=client_ip(request))
    db.commit(); cache.delete_prefix("properties:")
    item = db.scalar(select(Property).where(Property.id == property_id).options(*property_query_options()))
    return property_detail(db, item)


@router.post("/properties/{property_id}/unpublish", response_model=PropertyDetail)
def unpublish_property(property_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    item = db.get(Property, property_id)
    if not item: raise HTTPException(status_code=404, detail="Property not found")
    item.status = "draft"
    write_audit(db, actor=user, action="property.unpublish", entity_type="property", entity_id=item.id, ip_address=client_ip(request))
    db.commit(); cache.delete_prefix("properties:")
    item = db.scalar(select(Property).where(Property.id == property_id).options(*property_query_options()))
    return property_detail(db, item)


@router.delete("/properties/{property_id}", status_code=204)
def delete_property(property_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    item = db.get(Property, property_id)
    if not item: raise HTTPException(status_code=404, detail="Property not found")
    before = property_to_dict(item); db.delete(item)
    write_audit(db, actor=user, action="property.delete", entity_type="property", entity_id=property_id, before=before, ip_address=client_ip(request))
    db.commit(); cache.delete_prefix("properties:"); return Response(status_code=204)


@router.get("/appointments", response_model=list[AppointmentRead])
def list_appointments(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    stmt = select(Appointment).order_by(Appointment.scheduled_at.desc())
    if status: stmt = stmt.where(Appointment.status == status)
    return list(db.scalars(stmt))


@router.patch("/appointments/{appointment_id}", response_model=AppointmentRead)
def admin_update_appointment(appointment_id: str, payload: AppointmentUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = db.get(Appointment, appointment_id)
    if not item: raise HTTPException(status_code=404, detail="Appointment not found")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return item


@router.get("/leads", response_model=list[LeadRead])
def list_leads(status: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    stmt = select(Lead).order_by(Lead.created_at.desc())
    if status: stmt = stmt.where(Lead.status == status)
    return list(db.scalars(stmt))


@router.patch("/leads/{lead_id}", response_model=LeadRead)
def update_lead(lead_id: str, payload: LeadUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = db.get(Lead, lead_id)
    if not item: raise HTTPException(status_code=404, detail="Lead not found")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return item


@router.get("/audit-logs", response_model=list[AuditLogRead])
def audit_logs(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)))
