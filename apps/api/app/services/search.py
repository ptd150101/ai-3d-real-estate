from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from ..models import Agent, Property, PropertyModel3D
from ..schemas import SearchFilters
from .cache import cache
from .geo import haversine_km

DISTRICT_ALIASES = {"cau giay": "Cầu Giấy", "tay ho": "Tây Hồ", "long bien": "Long Biên", "nam tu liem": "Nam Từ Liêm", "bac tu liem": "Bắc Từ Liêm", "dong da": "Đống Đa", "hai ba trung": "Hai Bà Trưng", "hoan kiem": "Hoàn Kiếm", "ha dong": "Hà Đông", "thanh xuan": "Thanh Xuân", "ba dinh": "Ba Đình", "hoang mai": "Hoàng Mai", "dong anh": "Đông Anh", "gia lam": "Gia Lâm"}
PROPERTY_TYPES = {"chung cu": "apartment", "can ho": "apartment", "nha pho": "townhouse", "biet thu": "villa", "dat": "land", "shophouse": "shophouse", "van phong": "office"}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def parse_money(value: str) -> int | None:
    normalized = normalize(value).replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ty|trieu)", normalized)
    if not match:
        return None
    return round(float(match.group(1)) * (1_000_000_000 if match.group(2) == "ty" else 1_000_000))


def parse_natural_query(query: str) -> tuple[SearchFilters, str]:
    normalized = normalize(query)
    filters = SearchFilters(q=query)
    if any(x in normalized for x in ["thue", "cho thue"]): filters.transaction_type = "rent"
    elif any(x in normalized for x in ["mua", "ban"]): filters.transaction_type = "sale"
    for alias, district in DISTRICT_ALIASES.items():
        if alias in normalized: filters.district.append(district)
    for alias, property_type in PROPERTY_TYPES.items():
        if alias in normalized: filters.property_type.append(property_type)
    bedroom = re.search(r"(?:it nhat|toi thieu|>=)?\s*(\d+)\s*(?:phong ngu|pn)", normalized)
    if bedroom: filters.bedrooms = int(bedroom.group(1))
    bathroom = re.search(r"(\d+)\s*(?:wc|phong tam)", normalized)
    if bathroom: filters.bathrooms = int(bathroom.group(1))
    money = parse_money(query)
    if money:
        if any(x in normalized for x in ["duoi", "toi da", "khong qua", "<"]): filters.max_price = money
        elif any(x in normalized for x in ["tren", "toi thieu", ">"]): filters.min_price = money
        else: filters.min_price = round(money * .8); filters.max_price = round(money * 1.2)
    area = re.search(r"(\d+(?:\.\d+)?)\s*m2", normalized)
    if area:
        amount = float(area.group(1))
        if "duoi" in normalized: filters.max_area = amount
        elif "tren" in normalized or "it nhat" in normalized: filters.min_area = amount
        else: filters.min_area = amount * .8; filters.max_area = amount * 1.2
    if "3d" in normalized or "mo hinh" in normalized: filters.has_3d = True
    if "chinh chu" in normalized: filters.is_owner_listing = True
    if "so do" in normalized: filters.legal_status.append("Sổ đỏ")
    parts: list[str] = []
    if filters.transaction_type: parts.append("giao dịch " + filters.transaction_type)
    if filters.district: parts.append("khu vực " + ", ".join(filters.district))
    if filters.max_price: parts.append(f"giá tối đa {filters.max_price:,} VND")
    if filters.bedrooms: parts.append(f"ít nhất {filters.bedrooms} phòng ngủ")
    if filters.has_3d: parts.append("có trải nghiệm 3D")
    return filters, "Đã hiểu: " + (", ".join(parts) if parts else "tìm kiếm theo nội dung mô tả") + "."


def apply_filters(stmt, filters: SearchFilters, include_unpublished: bool = False):
    conditions = []
    if not include_unpublished: conditions.append(Property.status == "published")
    if filters.transaction_type: conditions.append(Property.transaction_type == filters.transaction_type)
    if filters.property_type: conditions.append(Property.property_type.in_(filters.property_type))
    if filters.city: conditions.append(func.lower(Property.city) == filters.city.lower())
    if filters.district: conditions.append(Property.district.in_(filters.district))
    if filters.min_price is not None: conditions.append(Property.price >= filters.min_price)
    if filters.max_price is not None: conditions.append(Property.price <= filters.max_price)
    if filters.min_area is not None: conditions.append(Property.area_m2 >= filters.min_area)
    if filters.max_area is not None: conditions.append(Property.area_m2 <= filters.max_area)
    if filters.bedrooms is not None: conditions.append(Property.bedrooms >= filters.bedrooms)
    if filters.bathrooms is not None: conditions.append(Property.bathrooms >= filters.bathrooms)
    if filters.legal_status: conditions.append(Property.legal_status.in_(filters.legal_status))
    if filters.furnishing: conditions.append(Property.furnishing.in_(filters.furnishing))
    if filters.has_3d is not None: conditions.append(Property.has_3d == filters.has_3d)
    if filters.is_owner_listing is not None: conditions.append(Property.is_owner_listing == filters.is_owner_listing)
    if filters.q:
        pattern = f"%{filters.q.lower()}%"
        conditions.append(or_(func.lower(Property.title).like(pattern), func.lower(Property.description).like(pattern), func.lower(Property.address).like(pattern), func.lower(Property.district).like(pattern)))
    return stmt.where(and_(*conditions)) if conditions else stmt


def property_query_options():
    return (selectinload(Property.media), selectinload(Property.features), selectinload(Property.agent).selectinload(Agent.agency), selectinload(Property.project), selectinload(Property.model_3d).selectinload(PropertyModel3D.floors), selectinload(Property.model_3d).selectinload(PropertyModel3D.hotspots), selectinload(Property.documents))


def search_properties(db: Session, filters: SearchFilters, page: int = 1, page_size: int = 12, include_unpublished: bool = False) -> tuple[list[Property], int]:
    base = apply_filters(select(Property), filters, include_unpublished)
    postgres_geo = filters.latitude is not None and filters.longitude is not None and filters.radius_km is not None and db.bind is not None and db.bind.dialect.name == "postgresql"
    if postgres_geo:
        condition = text("ST_DWithin(ST_SetSRID(ST_MakePoint(properties.longitude, properties.latitude), 4326)::geography, ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326)::geography, :radius_m)").bindparams(origin_lon=filters.longitude, origin_lat=filters.latitude, radius_m=filters.radius_km * 1000)
        base = base.where(Property.latitude.is_not(None), Property.longitude.is_not(None), condition)
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    if filters.sort == "price_asc": base = base.order_by(Property.price.asc())
    elif filters.sort == "price_desc": base = base.order_by(Property.price.desc())
    elif filters.sort == "area_desc": base = base.order_by(Property.area_m2.desc())
    else: base = base.order_by(Property.is_featured.desc(), Property.published_at.desc(), Property.created_at.desc())
    items = list(db.scalars(base.options(*property_query_options()).offset((page - 1) * page_size).limit(page_size)).unique())
    if filters.latitude is not None and filters.longitude is not None and filters.radius_km is not None and not postgres_geo:
        items = [p for p in items if p.latitude is not None and p.longitude is not None and haversine_km(filters.latitude, filters.longitude, p.latitude, p.longitude) <= filters.radius_km]
        total = len(items)
    return items, total


def get_facets(db: Session) -> dict[str, Any]:
    cached = cache.get_json("properties:facets")
    if cached is not None: return cached
    districts = db.execute(select(Property.district, func.count(Property.id)).where(Property.status == "published").group_by(Property.district)).all()
    property_types = db.execute(select(Property.property_type, func.count(Property.id)).where(Property.status == "published").group_by(Property.property_type)).all()
    result = {"districts": [{"value": key, "count": count} for key, count in districts], "property_types": [{"value": key, "count": count} for key, count in property_types]}
    cache.set_json("properties:facets", result, ttl=300)
    return result
