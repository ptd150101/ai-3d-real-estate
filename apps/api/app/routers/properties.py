from __future__ import annotations
import math
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Property
from ..schemas import NaturalSearchRequest, NaturalSearchResponse, PaginatedProperties, PropertyDetail, SearchFilters
from ..services.search import get_facets, parse_natural_query, property_query_options, search_properties
from ..services.serializers import property_detail, property_summary
router = APIRouter(prefix="/properties", tags=["properties"])
@router.get("", response_model=PaginatedProperties)
def list_properties(q: str | None = None, transaction_type: str | None = None, property_type: list[str] = Query(default=[]), city: str | None = None, district: list[str] = Query(default=[]), min_price: int | None = None, max_price: int | None = None, min_area: float | None = None, max_area: float | None = None, bedrooms: int | None = None, bathrooms: int | None = None, legal_status: list[str] = Query(default=[]), furnishing: list[str] = Query(default=[]), has_3d: bool | None = None, is_owner_listing: bool | None = None, latitude: float | None = None, longitude: float | None = None, radius_km: float | None = None, sort: str = "newest", page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=48), db: Session = Depends(get_db)) -> PaginatedProperties:
    filters = SearchFilters(**locals()); items, total = search_properties(db, filters, page, page_size)
    return PaginatedProperties(items=[property_summary(x) for x in items], total=total, page=page, page_size=page_size, pages=max(1, math.ceil(total / page_size)), facets=get_facets(db))
@router.post("/parse-search", response_model=NaturalSearchResponse)
def natural_search(payload: NaturalSearchRequest) -> NaturalSearchResponse:
    filters, explanation = parse_natural_query(payload.query); return NaturalSearchResponse(filters=filters, explanation=explanation)
@router.get("/{identifier}", response_model=PropertyDetail)
def get_property(identifier: str, db: Session = Depends(get_db)) -> PropertyDetail:
    item = db.scalar(select(Property).where((Property.id == identifier) | (Property.slug == identifier)).options(*property_query_options()))
    if not item or item.status not in {"published", "sold", "rented"}: raise HTTPException(status_code=404, detail="Property not found")
    item.view_count += 1; db.commit(); return property_detail(db, item)
@router.get("/{identifier}/similar", response_model=list[PropertyDetail])
def similar_properties(identifier: str, limit: int = Query(4, ge=1, le=12), db: Session = Depends(get_db)) -> list[PropertyDetail]:
    current = db.scalar(select(Property).where((Property.id == identifier) | (Property.slug == identifier)))
    if not current: raise HTTPException(status_code=404, detail="Property not found")
    price_margin = max(500_000_000, int(current.price * 0.3))
    stmt = select(Property).where(Property.id != current.id, Property.status == "published", Property.city == current.city, Property.price.between(current.price - price_margin, current.price + price_margin)).options(*property_query_options()).order_by((Property.district == current.district).desc(), Property.is_featured.desc()).limit(limit)
    return [property_detail(db, p) for p in db.scalars(stmt).unique()]
