from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import BrochureAsset, ModelNavigationZone, PanoramaHotspot, PanoramaLink, PanoramaScene, Property, User
from ..p1_schemas import BrochureRead, BrochureRequest, NavigationZoneCreate, PanoramaGraph, PanoramaHotspotCreate, PanoramaLinkCreate, PanoramaSceneCreate
from ..services.experience import generate_brochure, panorama_graph
from ..services.jobs_p1 import enqueue_job

router = APIRouter(tags=["experience"])


@router.get("/properties/{property_id}/panorama", response_model=PanoramaGraph)
def public_panorama(property_id: str, db: Session = Depends(get_db)):
    if not db.get(Property, property_id): raise HTTPException(status_code=404, detail="Property not found")
    return panorama_graph(db, property_id)


@router.post("/admin/panorama/scenes", status_code=201)
def create_scene(payload: PanoramaSceneCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    if not db.get(Property, payload.property_id): raise HTTPException(status_code=404, detail="Property not found")
    item = PanoramaScene(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item)
    return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@router.patch("/admin/panorama/scenes/{scene_id}")
def update_scene(scene_id: str, payload: PanoramaSceneCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = db.get(PanoramaScene, scene_id)
    if not item: raise HTTPException(status_code=404, detail="Scene not found")
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@router.post("/admin/panorama/links", status_code=201)
def create_link(payload: PanoramaLinkCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = PanoramaLink(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@router.post("/admin/panorama/hotspots", status_code=201)
def create_hotspot(payload: PanoramaHotspotCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = PanoramaHotspot(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@router.post("/admin/panorama/navigation-zones", status_code=201)
def create_zone(payload: NavigationZoneCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    item = ModelNavigationZone(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@router.delete("/admin/panorama/{entity}/{entity_id}", status_code=204)
def delete_entity(entity: str, entity_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles("admin", "agent"))):
    classes = {"scenes": PanoramaScene, "links": PanoramaLink, "hotspots": PanoramaHotspot, "navigation-zones": ModelNavigationZone}
    cls = classes.get(entity)
    if not cls: raise HTTPException(status_code=400, detail="Unsupported panorama entity")
    item = db.get(cls, entity_id)
    if not item: raise HTTPException(status_code=404, detail="Entity not found")
    db.delete(item); db.commit(); return Response(status_code=204)


@router.get("/properties/{property_id}/brochure", response_model=BrochureRead)
def get_brochure(property_id: str, db: Session = Depends(get_db)):
    item = db.scalar(select(BrochureAsset).where(BrochureAsset.property_id == property_id, BrochureAsset.status == "ready").order_by(BrochureAsset.generated_at.desc()))
    if not item: raise HTTPException(status_code=404, detail="Brochure not generated")
    return item


@router.post("/properties/{property_id}/brochure")
def request_brochure(property_id: str, payload: BrochureRequest, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop or prop.status != "published": raise HTTPException(status_code=404, detail="Property not found")
    existing = db.scalar(select(BrochureAsset).where(BrochureAsset.property_id == property_id, BrochureAsset.template_version == payload.template_version, BrochureAsset.status == "ready").order_by(BrochureAsset.generated_at.desc()))
    if existing and not payload.force:
        return {"status": "ready", "brochure": {c.name: getattr(existing, c.name) for c in existing.__table__.columns}}
    job = enqueue_job(db, "brochure_render", {"property_id": property_id, "template_version": payload.template_version, "force": payload.force}, idempotency_key=f"brochure:{property_id}:{prop.updated_at.isoformat()}:{payload.template_version}" if not payload.force else None)
    db.commit(); return {"status": "queued", "job_id": job.id}
