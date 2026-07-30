from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NearbyPlace, Property
from ..schemas import PropertyDetail, PropertySummary


def property_summary(property_obj: Property) -> PropertySummary:
    return PropertySummary.model_validate(property_obj)


def property_detail(db: Session, property_obj: Property) -> PropertyDetail:
    data = PropertyDetail.model_validate(property_obj)
    places = list(db.scalars(select(NearbyPlace).where(NearbyPlace.property_id == property_obj.id).order_by(NearbyPlace.distance_m.asc())))
    return data.model_copy(update={"nearby_places": places})
