from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from ..models import Agent, Property, PropertyMedia, User
from .cache import cache

SCALE_PREFIX = "mock-"
DEFAULT_TOTAL_PROPERTIES = 1_000_000
DEFAULT_BATCH_SIZE = 50_000

_DISTRICTS = [
    ("Tây Hồ", 21.0690, 105.8180, 95_000_000),
    ("Cầu Giấy", 21.0350, 105.7900, 88_000_000),
    ("Long Biên", 21.0550, 105.9000, 70_000_000),
    ("Nam Từ Liêm", 21.0160, 105.7650, 72_000_000),
    ("Hà Đông", 20.9660, 105.7760, 62_000_000),
    ("Ba Đình", 21.0360, 105.8140, 105_000_000),
    ("Thanh Xuân", 20.9950, 105.8050, 78_000_000),
    ("Hai Bà Trưng", 21.0060, 105.8570, 92_000_000),
    ("Hoàng Mai", 20.9740, 105.8570, 60_000_000),
    ("Gia Lâm", 21.0220, 105.9440, 58_000_000),
    ("Đông Anh", 21.1400, 105.8500, 52_000_000),
    ("Bắc Từ Liêm", 21.0700, 105.7600, 65_000_000),
    ("Đống Đa", 21.0150, 105.8300, 90_000_000),
    ("Hoàn Kiếm", 21.0300, 105.8520, 120_000_000),
]

_TYPE_NAMES = {
    "apartment": "Căn hộ",
    "townhouse": "Nhà phố",
    "villa": "Biệt thự",
    "shophouse": "Shophouse",
    "studio": "Studio",
    "penthouse": "Penthouse",
}
_TYPE_FACTORS = {
    "apartment": 1.00,
    "townhouse": 1.12,
    "villa": 1.25,
    "shophouse": 1.18,
    "studio": 0.92,
    "penthouse": 1.32,
}
_IMAGE_POOLS = {
    "apartment": 15,
    "townhouse": 10,
    "villa": 10,
    "shophouse": 8,
    "studio": 7,
    "penthouse": 10,
}
_DIRECTIONS = ["Đông", "Tây", "Nam", "Bắc", "Đông Nam", "Đông Bắc", "Tây Nam", "Tây Bắc"]
_FURNISHING = ["Đầy đủ", "Cơ bản", "Không nội thất", "Nội thất cao cấp"]

ProgressCallback = Callable[[int, int], None]


def _property_type(sequence: int) -> str:
    bucket = sequence % 100
    if bucket < 40:
        return "apartment"
    if bucket < 65:
        return "townhouse"
    if bucket < 75:
        return "villa"
    if bucket < 85:
        return "shophouse"
    if bucket < 95:
        return "studio"
    return "penthouse"


def _bedrooms(property_type: str, sequence: int) -> int:
    if property_type == "studio":
        return 1
    if property_type == "apartment":
        return 1 + sequence % 4
    if property_type == "townhouse":
        return 2 + sequence % 5
    if property_type == "villa":
        return 3 + sequence % 5
    if property_type == "shophouse":
        return 2 + sequence % 3
    return 2 + sequence % 4


def _area(property_type: str, sequence: int) -> float:
    if property_type == "studio":
        return float(28 + sequence % 28)
    if property_type == "apartment":
        return float(48 + sequence % 105)
    if property_type == "townhouse":
        return float(65 + sequence % 176)
    if property_type == "villa":
        return float(150 + sequence % 351)
    if property_type == "shophouse":
        return float(70 + sequence % 181)
    return float(120 + sequence % 231)


def _deterministic_id(kind: str, sequence: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"nestora:{kind}:{sequence}"))


def _fallback_rows(
    start: int,
    end: int,
    *,
    agents: list[Agent],
    admin: User,
) -> tuple[list[dict], list[dict]]:
    now = datetime.now(timezone.utc)
    properties: list[dict] = []
    media: list[dict] = []
    for sequence in range(start, end + 1):
        district, base_lat, base_lon, price_m2 = _DISTRICTS[(sequence - 1) % len(_DISTRICTS)]
        property_type = _property_type(sequence)
        bedrooms = _bedrooms(property_type, sequence)
        bathrooms = max(1, min(bedrooms, 1 + sequence % 4))
        area = _area(property_type, sequence)
        transaction_type = "sale" if sequence % 10 < 7 else "rent"
        factor = _TYPE_FACTORS[property_type]
        market_value = price_m2 * area * factor * (0.90 + (sequence % 21) / 100)
        price = round(market_value if transaction_type == "sale" else market_value * (0.0035 + (sequence % 5) * 0.0002))
        verified = sequence % 5 != 0
        published_at = now - timedelta(days=180 + sequence % 720, minutes=sequence % 1440)
        agent = agents[(sequence - 1) % len(agents)]
        property_id = _deterministic_id("scale-property", sequence)
        type_name = _TYPE_NAMES[property_type]
        title = f"{type_name} {bedrooms}PN tại {district} #{sequence:07d}"
        address = f"Số {(sequence * 17) % 300 + 1}, đường Mock {(sequence % 80) + 1}"
        ward = f"Phường demo {(sequence % 20) + 1}"
        legal_status = (
            ["Sổ đỏ chính chủ", "Sở hữu lâu dài", "Hợp đồng mua bán"][sequence % 3]
            if transaction_type == "sale"
            else "Hợp đồng thuê chuẩn"
        )
        properties.append(
            {
                "id": property_id,
                "organization_id": agent.organization_id,
                "slug": f"{SCALE_PREFIX}{sequence:07d}",
                "title": title,
                "transaction_type": transaction_type,
                "property_type": property_type,
                "status": "published",
                "price": int(price),
                "currency": "VND",
                "area_m2": area,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "floors_count": 1 if property_type in {"studio", "apartment", "penthouse"} else 2 + sequence % 4,
                "parking_spaces": sequence % 3,
                "address": address,
                "ward": ward,
                "district": district,
                "city": "Hà Nội",
                "latitude": base_lat + ((sequence % 101) - 50) * 0.00008,
                "longitude": base_lon + (((sequence * 7) % 101) - 50) * 0.00008,
                "legal_status": legal_status,
                "furnishing": _FURNISHING[sequence % len(_FURNISHING)],
                "description": f"Dữ liệu mock quy mô lớn cho {type_name.lower()} tại {district}. Mã mẫu #{sequence:07d} dùng để kiểm thử tìm kiếm, bộ lọc, phân trang và tải hệ thống.",
                "year_built": 2010 + sequence % 17,
                "direction": _DIRECTIONS[sequence % len(_DIRECTIONS)],
                "is_featured": False,
                "is_verified": verified,
                "is_owner_listing": sequence % 4 == 0,
                "has_3d": False,
                "view_count": sequence % 500,
                "verified_at": published_at if verified else None,
                "expires_at": now + timedelta(days=365),
                "published_at": published_at,
                "agent_id": agent.id,
                "project_id": None,
                "owner_id": admin.id,
                "created_at": published_at,
                "updated_at": published_at,
            }
        )
        pool = _IMAGE_POOLS[property_type]
        image_index = (sequence - 1) % pool + 1
        image_url = f"/api/backend/demo-assets/images/{property_type}/{image_index}.svg"
        media.append(
            {
                "id": _deterministic_id("scale-media", sequence),
                "property_id": property_id,
                "media_type": "image",
                "url": image_url,
                "thumbnail_url": image_url,
                "alt_text": title,
                "sort_order": 0,
                "metadata_json": {"mock": True, "scale": True},
                "created_at": published_at,
                "updated_at": published_at,
            }
        )
    return properties, media


_POSTGRES_PROPERTY_INSERT = r"""
WITH source AS (
    SELECT
        gs AS n,
        md5('nestora-scale-property-' || gs::text) AS h
    FROM generate_series(:start_sequence, :end_sequence) AS gs
), dimensions AS (
    SELECT
        n,
        h,
        CASE ((n - 1) % 14)
            WHEN 0 THEN 'Tây Hồ' WHEN 1 THEN 'Cầu Giấy' WHEN 2 THEN 'Long Biên'
            WHEN 3 THEN 'Nam Từ Liêm' WHEN 4 THEN 'Hà Đông' WHEN 5 THEN 'Ba Đình'
            WHEN 6 THEN 'Thanh Xuân' WHEN 7 THEN 'Hai Bà Trưng' WHEN 8 THEN 'Hoàng Mai'
            WHEN 9 THEN 'Gia Lâm' WHEN 10 THEN 'Đông Anh' WHEN 11 THEN 'Bắc Từ Liêm'
            WHEN 12 THEN 'Đống Đa' ELSE 'Hoàn Kiếm'
        END AS district,
        CASE ((n - 1) % 14)
            WHEN 0 THEN 21.0690 WHEN 1 THEN 21.0350 WHEN 2 THEN 21.0550
            WHEN 3 THEN 21.0160 WHEN 4 THEN 20.9660 WHEN 5 THEN 21.0360
            WHEN 6 THEN 20.9950 WHEN 7 THEN 21.0060 WHEN 8 THEN 20.9740
            WHEN 9 THEN 21.0220 WHEN 10 THEN 21.1400 WHEN 11 THEN 21.0700
            WHEN 12 THEN 21.0150 ELSE 21.0300
        END AS base_lat,
        CASE ((n - 1) % 14)
            WHEN 0 THEN 105.8180 WHEN 1 THEN 105.7900 WHEN 2 THEN 105.9000
            WHEN 3 THEN 105.7650 WHEN 4 THEN 105.7760 WHEN 5 THEN 105.8140
            WHEN 6 THEN 105.8050 WHEN 7 THEN 105.8570 WHEN 8 THEN 105.8570
            WHEN 9 THEN 105.9440 WHEN 10 THEN 105.8500 WHEN 11 THEN 105.7600
            WHEN 12 THEN 105.8300 ELSE 105.8520
        END AS base_lon,
        CASE ((n - 1) % 14)
            WHEN 0 THEN 95000000 WHEN 1 THEN 88000000 WHEN 2 THEN 70000000
            WHEN 3 THEN 72000000 WHEN 4 THEN 62000000 WHEN 5 THEN 105000000
            WHEN 6 THEN 78000000 WHEN 7 THEN 92000000 WHEN 8 THEN 60000000
            WHEN 9 THEN 58000000 WHEN 10 THEN 52000000 WHEN 11 THEN 65000000
            WHEN 12 THEN 90000000 ELSE 120000000
        END::numeric AS price_m2,
        CASE
            WHEN (n % 100) < 40 THEN 'apartment'
            WHEN (n % 100) < 65 THEN 'townhouse'
            WHEN (n % 100) < 75 THEN 'villa'
            WHEN (n % 100) < 85 THEN 'shophouse'
            WHEN (n % 100) < 95 THEN 'studio'
            ELSE 'penthouse'
        END AS property_type
    FROM source
), enriched AS (
    SELECT
        *,
        CASE property_type
            WHEN 'studio' THEN 1
            WHEN 'apartment' THEN 1 + (n % 4)
            WHEN 'townhouse' THEN 2 + (n % 5)
            WHEN 'villa' THEN 3 + (n % 5)
            WHEN 'shophouse' THEN 2 + (n % 3)
            ELSE 2 + (n % 4)
        END::int AS bedrooms,
        CASE property_type
            WHEN 'studio' THEN 28 + (n % 28)
            WHEN 'apartment' THEN 48 + (n % 105)
            WHEN 'townhouse' THEN 65 + (n % 176)
            WHEN 'villa' THEN 150 + (n % 351)
            WHEN 'shophouse' THEN 70 + (n % 181)
            ELSE 120 + (n % 231)
        END::numeric AS area_m2,
        CASE property_type
            WHEN 'townhouse' THEN 1.12 WHEN 'villa' THEN 1.25 WHEN 'shophouse' THEN 1.18
            WHEN 'studio' THEN 0.92 WHEN 'penthouse' THEN 1.32 ELSE 1.00
        END::numeric AS type_factor,
        CASE property_type
            WHEN 'apartment' THEN 'Căn hộ' WHEN 'townhouse' THEN 'Nhà phố'
            WHEN 'villa' THEN 'Biệt thự' WHEN 'shophouse' THEN 'Shophouse'
            WHEN 'studio' THEN 'Studio' ELSE 'Penthouse'
        END AS type_name
    FROM dimensions
), priced AS (
    SELECT
        *,
        CASE WHEN (n % 10) < 7 THEN 'sale' ELSE 'rent' END AS transaction_type,
        price_m2 * area_m2 * type_factor * (0.90 + (n % 21)::numeric / 100) AS market_value
    FROM enriched
)
INSERT INTO properties (
    id, organization_id, slug, title, transaction_type, property_type, status, price, currency,
    area_m2, bedrooms, bathrooms, floors_count, parking_spaces, address, ward, district, city,
    latitude, longitude, legal_status, furnishing, description, year_built, direction,
    is_featured, is_verified, is_owner_listing, has_3d, view_count, verified_at, expires_at,
    published_at, agent_id, project_id, owner_id, created_at, updated_at
)
SELECT
    substr(h,1,8) || '-' || substr(h,9,4) || '-' || substr(h,13,4) || '-' || substr(h,17,4) || '-' || substr(h,21,12),
    :organization_id,
    'mock-' || lpad(n::text, 7, '0'),
    type_name || ' ' || bedrooms::text || 'PN tại ' || district || ' #' || lpad(n::text, 7, '0'),
    transaction_type,
    property_type,
    'published',
    round(CASE WHEN transaction_type = 'sale' THEN market_value ELSE market_value * (0.0035 + (n % 5)::numeric * 0.0002) END)::bigint,
    'VND',
    area_m2::double precision,
    bedrooms,
    greatest(1, least(bedrooms, 1 + (n % 4)))::int,
    CASE WHEN property_type IN ('studio','apartment','penthouse') THEN 1 ELSE 2 + (n % 4) END::int,
    (n % 3)::int,
    'Số ' || (((n * 17) % 300) + 1)::text || ', đường Mock ' || ((n % 80) + 1)::text,
    'Phường demo ' || ((n % 20) + 1)::text,
    district,
    'Hà Nội',
    base_lat + (((n % 101) - 50)::double precision * 0.00008),
    base_lon + ((((n * 7) % 101) - 50)::double precision * 0.00008),
    CASE WHEN transaction_type = 'rent' THEN 'Hợp đồng thuê chuẩn'
         WHEN (n % 3) = 0 THEN 'Sổ đỏ chính chủ'
         WHEN (n % 3) = 1 THEN 'Sở hữu lâu dài'
         ELSE 'Hợp đồng mua bán' END,
    CASE (n % 4) WHEN 0 THEN 'Đầy đủ' WHEN 1 THEN 'Cơ bản' WHEN 2 THEN 'Không nội thất' ELSE 'Nội thất cao cấp' END,
    'Dữ liệu mock quy mô lớn cho ' || lower(type_name) || ' tại ' || district || '. Mã mẫu #' || lpad(n::text, 7, '0') || ' dùng để kiểm thử tìm kiếm, bộ lọc, phân trang và tải hệ thống.',
    (2010 + (n % 17))::int,
    CASE (n % 8) WHEN 0 THEN 'Đông' WHEN 1 THEN 'Tây' WHEN 2 THEN 'Nam' WHEN 3 THEN 'Bắc'
         WHEN 4 THEN 'Đông Nam' WHEN 5 THEN 'Đông Bắc' WHEN 6 THEN 'Tây Nam' ELSE 'Tây Bắc' END,
    false,
    (n % 5) <> 0,
    (n % 4) = 0,
    false,
    (n % 500)::int,
    CASE WHEN (n % 5) <> 0 THEN CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval ELSE NULL END,
    CURRENT_TIMESTAMP + interval '365 days',
    CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval - ((n % 1440)::text || ' minutes')::interval,
    :agent_id,
    NULL,
    :owner_id,
    CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval,
    CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval
FROM priced
ON CONFLICT (slug) DO NOTHING
"""

_POSTGRES_MEDIA_INSERT = r"""
WITH source AS (
    SELECT
        gs AS n,
        md5('nestora-scale-property-' || gs::text) AS property_hash,
        md5('nestora-scale-media-' || gs::text) AS media_hash,
        CASE
            WHEN (gs % 100) < 40 THEN 'apartment'
            WHEN (gs % 100) < 65 THEN 'townhouse'
            WHEN (gs % 100) < 75 THEN 'villa'
            WHEN (gs % 100) < 85 THEN 'shophouse'
            WHEN (gs % 100) < 95 THEN 'studio'
            ELSE 'penthouse'
        END AS property_type
    FROM generate_series(:start_sequence, :end_sequence) AS gs
), image_data AS (
    SELECT
        *,
        CASE property_type WHEN 'apartment' THEN 15 WHEN 'townhouse' THEN 10 WHEN 'villa' THEN 10
             WHEN 'shophouse' THEN 8 WHEN 'studio' THEN 7 ELSE 10 END AS pool_size
    FROM source
)
INSERT INTO property_media (
    id, property_id, media_type, url, thumbnail_url, alt_text, sort_order, metadata_json, created_at, updated_at
)
SELECT
    substr(media_hash,1,8) || '-' || substr(media_hash,9,4) || '-' || substr(media_hash,13,4) || '-' || substr(media_hash,17,4) || '-' || substr(media_hash,21,12),
    substr(property_hash,1,8) || '-' || substr(property_hash,9,4) || '-' || substr(property_hash,13,4) || '-' || substr(property_hash,17,4) || '-' || substr(property_hash,21,12),
    'image',
    '/api/backend/demo-assets/images/' || property_type || '/' || (((n - 1) % pool_size) + 1)::text || '.svg',
    '/api/backend/demo-assets/images/' || property_type || '/' || (((n - 1) % pool_size) + 1)::text || '.svg',
    'Ảnh mock #' || lpad(n::text, 7, '0'),
    0,
    '{"mock": true, "scale": true}'::json,
    CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval,
    CURRENT_TIMESTAMP - interval '180 days' - ((n % 720)::text || ' days')::interval
FROM image_data
ON CONFLICT (id) DO NOTHING
"""


def reset_scale_properties(db: Session) -> int:
    count = int(db.scalar(select(func.count(Property.id)).where(Property.slug.like(f"{SCALE_PREFIX}%"))) or 0)
    if count:
        db.execute(
            delete(Property).where(Property.slug.like(f"{SCALE_PREFIX}%")),
            execution_options={"synchronize_session": False},
        )
        db.commit()
        cache.delete_prefix("properties:")
    return count


def _scale_count(db: Session) -> int:
    return int(db.scalar(select(func.count(Property.id)).where(Property.slug.like(f"{SCALE_PREFIX}%"))) or 0)


def _showcase_count(db: Session) -> int:
    return int(db.scalar(select(func.count(Property.id)).where(Property.slug.like("demo-%"))) or 0)


def _max_scale_sequence(db: Session) -> int:
    slug = db.scalar(select(func.max(Property.slug)).where(Property.slug.like(f"{SCALE_PREFIX}%")))
    if not slug:
        return 0
    try:
        return int(str(slug)[len(SCALE_PREFIX) :])
    except ValueError:
        return 0


def seed_scale_properties(
    db: Session,
    *,
    target_total: int = DEFAULT_TOTAL_PROPERTIES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress: ProgressCallback | None = None,
) -> dict[str, int | str]:
    if target_total <= 0:
        raise ValueError("target_total must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    showcase = _showcase_count(db)
    if target_total < showcase:
        raise ValueError(f"target_total={target_total} is smaller than showcase dataset ({showcase})")
    target_scale = target_total - showcase
    current = _scale_count(db)
    max_sequence = _max_scale_sequence(db)

    # A non-contiguous or oversized scale dataset is cheaper and safer to rebuild
    # than trying to infer missing sequence numbers across up to a million rows.
    if current > target_scale or (current and max_sequence != current):
        reset_scale_properties(db)
        current = 0
        max_sequence = 0

    if current == target_scale:
        return {
            "preset": "million",
            "properties": showcase + current,
            "showcase_properties": showcase,
            "scale_properties": current,
            "scale_created": 0,
            "batch_size": batch_size,
        }

    admin = db.scalar(select(User).where(User.email == "admin@nestora.vn"))
    if not admin:
        raise RuntimeError("Run the MVP seed first so admin@nestora.vn exists")
    agents = list(
        db.scalars(
            select(Agent)
            .where(Agent.email.like("demo.agent%@nestora.vn"))
            .order_by(Agent.email)
        )
    )
    if not agents:
        raise RuntimeError("Run the MVP seed first so demo agents exist")

    created = 0
    start_sequence = max_sequence + 1
    dialect = db.bind.dialect.name if db.bind is not None else "unknown"
    property_insert = insert(Property.__table__)
    media_insert = insert(PropertyMedia.__table__)

    while start_sequence <= target_scale:
        end_sequence = min(start_sequence + batch_size - 1, target_scale)
        agent = agents[((start_sequence - 1) // batch_size) % len(agents)]
        if dialect == "postgresql":
            params = {
                "start_sequence": start_sequence,
                "end_sequence": end_sequence,
                "agent_id": agent.id,
                "organization_id": agent.organization_id,
                "owner_id": admin.id,
            }
            result = db.execute(text(_POSTGRES_PROPERTY_INSERT), params)
            db.execute(text(_POSTGRES_MEDIA_INSERT), params)
            batch_created = max(0, int(result.rowcount or 0))
        else:
            property_rows, media_rows = _fallback_rows(
                start_sequence,
                end_sequence,
                agents=agents,
                admin=admin,
            )
            db.execute(property_insert, property_rows)
            db.execute(media_insert, media_rows)
            batch_created = len(property_rows)
        db.commit()
        created += batch_created
        current = end_sequence
        if progress:
            progress(showcase + current, target_total)
        start_sequence = end_sequence + 1

    if dialect == "postgresql":
        db.execute(text("ANALYZE properties"))
        db.execute(text("ANALYZE property_media"))
        db.commit()
    cache.delete_prefix("properties:")

    final_scale = _scale_count(db)
    return {
        "preset": "million",
        "properties": showcase + final_scale,
        "showcase_properties": showcase,
        "scale_properties": final_scale,
        "scale_created": created,
        "batch_size": batch_size,
    }
