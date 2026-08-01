from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import client_ip, get_current_user, get_current_user_optional
from ..models import Appointment, Favorite, Lead, Property, SavedSearch, User
from ..schemas import AppointmentCreate, AppointmentRead, AppointmentUpdate, CompareRequest, CompareResponse, FavoriteRead, LeadCreate, LeadRead, MortgageRequest, MortgageResponse, SavedSearchCreate, SavedSearchRead
from ..services.audit import write_audit
from ..services.crm import route_lead
from ..services.mortgage import calculate_mortgage
from ..services.notification import emit_event
from ..services.saved_search import get_or_create_subscription
from ..services.search import property_query_options
from ..services.serializers import property_detail, property_summary

router = APIRouter(tags=["engagement"])


@router.post("/appointments", response_model=AppointmentRead, status_code=201)
def create_appointment(payload: AppointmentCreate, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    property_obj = db.get(Property, payload.property_id)
    if not property_obj: raise HTTPException(status_code=404, detail="Property not found")
    item = Appointment(**payload.model_dump(), user_id=user.id if user else None, agent_id=property_obj.agent_id, organization_id=property_obj.organization_id)
    db.add(item); db.flush()
    write_audit(db, actor=user, action="appointment.create", entity_type="appointment", entity_id=item.id, after=payload.model_dump(mode="json"), ip_address=client_ip(request))
    if user:
        emit_event(db, event_type="appointment.created", aggregate_type="appointment", aggregate_id=item.id, recipients=[user.id], payload={"property_title": property_obj.title, "scheduled_at": item.scheduled_at.isoformat()}, idempotency_key=f"appointment.created:{item.id}")
    db.commit(); db.refresh(item); return item


@router.get("/appointments/me", response_model=list[AppointmentRead])
def my_appointments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(Appointment).where(Appointment.user_id == user.id).order_by(Appointment.scheduled_at.desc())))


@router.patch("/appointments/{appointment_id}", response_model=AppointmentRead)
def update_appointment(appointment_id: str, payload: AppointmentUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(Appointment, appointment_id)
    if not item: raise HTTPException(status_code=404, detail="Appointment not found")
    if user.role not in {"admin", "agent"} and item.user_id != user.id: raise HTTPException(status_code=403, detail="Not allowed")
    before = {"scheduled_at": str(item.scheduled_at), "status": item.status, "note": item.note}
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    write_audit(db, actor=user, action="appointment.update", entity_type="appointment", entity_id=item.id, before=before, after=payload.model_dump(exclude_unset=True, mode="json"), ip_address=client_ip(request))
    db.commit(); db.refresh(item); return item


@router.post("/leads", response_model=LeadRead, status_code=201)
def create_lead(payload: LeadCreate, request: Request, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    # Local dedupe: update an open lead with the same phone/property instead of multiplying CRM contacts.
    item = db.scalar(select(Lead).where(Lead.phone == payload.phone, Lead.property_id == payload.property_id, Lead.status.in_(["new", "contacted"])).order_by(Lead.created_at.desc()))
    if item:
        item.message = payload.message or item.message
        item.email = payload.email or item.email
    else:
        property_obj = db.get(Property, payload.property_id) if payload.property_id else None
        item = Lead(**payload.model_dump(), user_id=user.id if user else None, organization_id=property_obj.organization_id if property_obj else None)
        db.add(item); db.flush()
    route_lead(db, item)
    write_audit(db, actor=user, action="lead.create", entity_type="lead", entity_id=item.id, after=payload.model_dump(mode="json"), ip_address=client_ip(request))
    db.commit(); db.refresh(item); return item


@router.post("/tools/mortgage", response_model=MortgageResponse)
def mortgage(payload: MortgageRequest): return calculate_mortgage(payload)


@router.get("/favorites", response_model=list[FavoriteRead])
def favorites(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(Favorite, Property).join(Property, Favorite.property_id == Property.id).where(Favorite.user_id == user.id).options(*property_query_options()).order_by(Favorite.created_at.desc())).all()
    return [FavoriteRead(property=property_summary(p), created_at=f.created_at) for f, p in rows]


@router.put("/favorites/{property_id}", status_code=204)
def add_favorite(property_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.get(Property, property_id): raise HTTPException(status_code=404, detail="Property not found")
    if not db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.property_id == property_id)):
        db.add(Favorite(user_id=user.id, property_id=property_id)); db.commit()
    return Response(status_code=204)


@router.delete("/favorites/{property_id}", status_code=204)
def remove_favorite(property_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.property_id == property_id)); db.commit(); return Response(status_code=204)


@router.get("/saved-searches", response_model=list[SavedSearchRead])
def list_saved_searches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at.desc())))


@router.post("/saved-searches", response_model=SavedSearchRead, status_code=201)
def create_saved_search(payload: SavedSearchCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = SavedSearch(user_id=user.id, **payload.model_dump()); db.add(item); db.flush(); get_or_create_subscription(db, item); db.commit(); db.refresh(item); return item


@router.delete("/saved-searches/{search_id}", status_code=204)
def delete_saved_search(search_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(SavedSearch, search_id)
    if not item or item.user_id != user.id: raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(item); db.commit(); return Response(status_code=204)


@router.post("/compare", response_model=CompareResponse)
def compare(payload: CompareRequest, db: Session = Depends(get_db)):
    properties = list(db.scalars(select(Property).where(Property.id.in_(payload.property_ids)).options(*property_query_options())).unique())
    if len(properties) < 2: raise HTTPException(status_code=400, detail="At least two valid properties are required")
    cheapest = min(properties, key=lambda x: x.price); largest = max(properties, key=lambda x: x.area_m2)
    highlights = [f"{cheapest.title} có giá thấp nhất", f"{largest.title} có diện tích lớn nhất"]
    with_3d = [p.title for p in properties if p.has_3d]
    if with_3d: highlights.append("Có trải nghiệm 3D: " + ", ".join(with_3d))
    return CompareResponse(properties=[property_detail(db, p) for p in properties], highlights=highlights)
