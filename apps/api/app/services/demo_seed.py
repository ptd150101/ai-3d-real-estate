from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..demo_assets import (
    FIXTURE_ROOT,
    build_demo_glb,
    demo_model_url,
    demo_poster_url,
    get_model_template,
    select_model_template,
    template_floor_payload,
    template_hotspot_payload,
)
from ..models import (
    Agency,
    Agent,
    KnowledgeChunk,
    KnowledgeDocument,
    ListingQuota,
    NearbyPlace,
    Organization,
    OrganizationMember,
    Project,
    Property,
    PropertyDocument,
    PropertyFeature,
    PropertyFloor,
    PropertyHotspot,
    PropertyMedia,
    PropertyModel3D,
    User,
)
from ..security import hash_password
from .p2_tenant import initialize_organization
from .rag import index_document

DEMO_DATASET_VERSION = 2
DEMO_PREFIX = "demo-"
_IMAGE_POOL = {
    "apartment": 15,
    "townhouse": 10,
    "villa": 10,
    "shophouse": 8,
    "studio": 7,
    "penthouse": 10,
}
_ROOM_LABELS = ["Mặt ngoài", "Phòng khách", "Phòng bếp", "Phòng ngủ", "Tiện ích"]

_PROPERTY_TYPE_NAMES = {
    "studio": "Studio",
    "apartment": "Căn hộ",
    "penthouse": "Penthouse",
    "townhouse": "Nhà phố",
    "villa": "Biệt thự",
    "shophouse": "Shophouse",
}
_TITLE_SUFFIXES = [
    "thiết kế hiện đại",
    "nhiều ánh sáng",
    "gần tiện ích",
    "view thoáng",
    "nội thất đẹp",
    "vị trí trung tâm",
]


def _enrich_property_spec(raw: dict[str, Any], feature_catalog: list[str]) -> dict[str, Any]:
    spec = dict(raw)
    seed = int(spec.get("image_seed", 1))
    property_type = str(spec["property_type"])
    label = _PROPERTY_TYPE_NAMES.get(property_type, property_type.title())
    suffix = _TITLE_SUFFIXES[(seed - 1) % len(_TITLE_SUFFIXES)]
    bedrooms = int(spec["bedrooms"])
    spec["title"] = (
        f"{label} {bedrooms}PN {suffix} tại {spec['district']}"
        if property_type not in {"studio", "shophouse"}
        else f"{label} {suffix} tại {spec['district']}"
    )
    count = 5 + seed % 5
    start = (seed * 3) % len(feature_catalog)
    spec["features"] = [
        feature_catalog[(start + index * 5) % len(feature_catalog)] for index in range(count)
    ]
    transaction = "an cư lâu dài" if spec["transaction_type"] == "sale" else "thuê ở ổn định"
    spec["description"] = (
        f"{spec['title']} có diện tích {spec['area_m2']} m², bố trí {bedrooms} phòng ngủ "
        f"và {spec['bathrooms']} phòng tắm. Không gian được tổ chức hợp lý, ưu tiên ánh sáng "
        f"tự nhiên, thông gió và khả năng sử dụng linh hoạt. Vị trí tại {spec['address']}, "
        f"{spec['ward']}, {spec['district']} thuận tiện kết nối trường học, siêu thị và các "
        f"trục giao thông chính. Sản phẩm phù hợp cho nhu cầu {transaction}, đồng thời có dữ "
        f"liệu pháp lý và lịch xem nhà được quản lý trên Nestora."
    )
    return spec

_NEARBY_CATALOG = [
    ("Siêu thị tiện lợi", "supermarket", 220, -0.0010, 0.0010),
    ("Trường học gần nhất", "school", 350, 0.0020, 0.0010),
    ("Bệnh viện/Phòng khám", "hospital", 780, 0.0040, -0.0020),
    ("Công viên khu vực", "park", 520, -0.0025, -0.0015),
]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _demo_password(env_name: str) -> str:
    return os.getenv(env_name) or secrets.token_urlsafe(24)


def _ensure_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    role: str,
    phone: str | None,
    avatar_url: str | None = None,
    password_env: str,
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(_demo_password(password_env)),
            role=role,
            phone=phone,
            avatar_url=avatar_url,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.full_name = full_name
        user.role = role
        user.phone = phone
        user.avatar_url = avatar_url
        user.is_active = True
    return user


def _ensure_org_and_agency(db: Session, row: dict[str, Any], admin: User) -> tuple[Organization, Agency]:
    org = db.scalar(select(Organization).where(Organization.slug == row["slug"]))
    if not org:
        org = Organization(
            name=row["name"],
            slug=row["slug"],
            status="active",
            verified=bool(row.get("verified")),
            settings_json={"demo": True, "dataset_version": DEMO_DATASET_VERSION},
        )
        db.add(org)
        db.flush()
    else:
        org.name = row["name"]
        org.status = "active"
        org.verified = bool(row.get("verified"))
        org.settings_json = {"demo": True, "dataset_version": DEMO_DATASET_VERSION}
    initialize_organization(db, org, owner_user_id=admin.id, plan_code="pro")

    agency = db.scalar(select(Agency).where(Agency.slug == row["slug"]))
    if not agency:
        agency = Agency(slug=row["slug"], name=row["name"])
        db.add(agency)
        db.flush()
    agency.organization_id = org.id
    agency.name = row["name"]
    agency.logo_url = row.get("logo_url")
    agency.description = row.get("description")
    agency.verified = bool(row.get("verified"))
    return org, agency


def _ensure_agent_membership(db: Session, organization_id: str, user_id: str) -> None:
    membership = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if not membership:
        db.add(
            OrganizationMember(
                organization_id=organization_id,
                user_id=user_id,
                role="agent",
                status="active",
            )
        )
    else:
        membership.role = "agent"
        membership.status = "active"


def _property_media(spec: dict[str, Any]) -> list[PropertyMedia]:
    category = str(spec["property_type"])
    pool = _IMAGE_POOL.get(category, 10)
    cover = (int(spec.get("image_seed", 1)) - 1) % pool + 1
    result: list[PropertyMedia] = []
    for index, label in enumerate(_ROOM_LABELS):
        asset_index = ((cover - 1 + index * 3) % pool) + 1
        url = f"/api/backend/demo-assets/images/{category}/{asset_index}.svg"
        result.append(
            PropertyMedia(
                media_type="image",
                url=url,
                thumbnail_url=url,
                alt_text=f"{label} - {spec['title']}",
                sort_order=index,
                metadata_json={
                    "demo": True,
                    "dataset_version": DEMO_DATASET_VERSION,
                    "category": category,
                    "asset_index": asset_index,
                },
            )
        )
    return result


def _model_for_property(spec: dict[str, Any]) -> PropertyModel3D | None:
    if not spec.get("has_3d"):
        return None
    template_id = str(
        spec.get("model_template_id")
        or select_model_template(
            str(spec["property_type"]), int(spec["bedrooms"]), int(spec["floors_count"])
        )
    )
    template = get_model_template(template_id)
    model = PropertyModel3D(
        model_url=demo_model_url(template_id),
        poster_url=demo_poster_url(template_id),
        format="glb",
        file_size_bytes=len(build_demo_glb(template_id)),
        processing_status="ready",
        default_camera=dict(template.get("camera") or {}),
        quality_presets={
            "low": {"dpr": 1},
            "medium": {"dpr": 1.5},
            "high": {"dpr": 2},
            "template_id": template_id,
            "demo": True,
            "dataset_version": DEMO_DATASET_VERSION,
        },
    )
    floor_rows = template_floor_payload(template_id)
    floors: list[PropertyFloor] = []
    for row in floor_rows:
        floor = PropertyFloor(
            name=row["name"],
            sort_order=int(row["sort_order"]),
            object_names=list(row["object_names"]),
            furniture_object_names=list(row["furniture_object_names"]),
            camera=dict(row["camera"]),
        )
        model.floors.append(floor)
        floors.append(floor)
    for row in template_hotspot_payload(template_id):
        floor_index = min(int(row.pop("floor_index")), len(floors) - 1)
        hotspot = PropertyHotspot(
            floor_id=None,
            label=row["label"],
            description=row.get("description"),
            position=list(row["position"]),
            camera_position=list(row["camera_position"]),
            room_type=row.get("room_type"),
            metadata_json=dict(row.get("metadata_json") or {}),
        )
        # The relationship gets an id after flush; floor assignment is completed by caller.
        hotspot.metadata_json = {**hotspot.metadata_json, "floor_index": floor_index}
        model.hotspots.append(hotspot)
    return model


def _rebuild_property_assets(db: Session, item: Property, spec: dict[str, Any]) -> None:
    item.features.clear()
    item.media.clear()
    item.documents.clear()
    item.model_3d = None
    for place in db.scalars(select(NearbyPlace).where(NearbyPlace.property_id == item.id)):
        db.delete(place)
    db.flush()

    item.features = [
        PropertyFeature(name=name, category="amenity") for name in list(spec.get("features") or [])
    ]
    item.media = _property_media(spec)
    item.documents = [
        PropertyDocument(
            document_type="legal",
            title="Thông tin pháp lý đã kiểm tra" if spec.get("is_verified") else "Thông tin pháp lý",
            url="/documents/demo-legal.pdf",
            verified=bool(spec.get("is_verified")),
        )
    ]
    model = _model_for_property(spec)
    if model:
        item.model_3d = model
        db.flush()
        floors = list(model.floors)
        for hotspot in model.hotspots:
            floor_index = int((hotspot.metadata_json or {}).pop("floor_index", 0))
            hotspot.floor_id = floors[min(floor_index, len(floors) - 1)].id if floors else None
    latitude = float(item.latitude or 21.028)
    longitude = float(item.longitude or 105.834)
    for name, category, distance, lat_delta, lon_delta in _NEARBY_CATALOG:
        db.add(
            NearbyPlace(
                property_id=item.id,
                name=name,
                category=category,
                latitude=latitude + lat_delta,
                longitude=longitude + lon_delta,
                distance_m=distance,
            )
        )


def _assets_are_current(item: Property) -> bool:
    if not item.media:
        return False
    metadata = item.media[0].metadata_json or {}
    if metadata.get("dataset_version") != DEMO_DATASET_VERSION:
        return False
    if item.has_3d:
        return bool(
            item.model_3d
            and (item.model_3d.quality_presets or {}).get("dataset_version")
            == DEMO_DATASET_VERSION
        )
    return item.model_3d is None


def _knowledge_content(spec: dict[str, Any]) -> str:
    transaction = "bán" if spec["transaction_type"] == "sale" else "cho thuê"
    return (
        f"{spec['title']}. Tin {transaction} tại {spec['district']}, Hà Nội. "
        f"Giá {spec['price']} VND, diện tích {spec['area_m2']} m², "
        f"{spec['bedrooms']} phòng ngủ, {spec['bathrooms']} phòng tắm. "
        f"Địa chỉ {spec['address']}, {spec['ward']}, {spec['district']}. "
        f"Pháp lý: {spec['legal_status']}. Nội thất: {spec['furnishing']}. "
        f"Tiện ích: {', '.join(spec.get('features') or [])}. {spec['description']}"
    )


def reset_demo_data(db: Session) -> None:
    documents = list(
        db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.source_url.like("demo://%"))
        )
    )
    document_ids = [document.id for document in documents]
    if document_ids:
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id.in_(document_ids)).delete(
            synchronize_session=False
        )
    for document in documents:
        db.delete(document)

    properties = list(
        db.scalars(select(Property).where(Property.slug.like(f"{DEMO_PREFIX}%")))
    )
    property_ids = [item.id for item in properties]
    if property_ids:
        db.query(NearbyPlace).filter(NearbyPlace.property_id.in_(property_ids)).delete(
            synchronize_session=False
        )
    for item in properties:
        db.delete(item)
    for item in db.scalars(select(Project).where(Project.slug.like(f"{DEMO_PREFIX}%"))):
        db.delete(item)
    demo_users = list(db.scalars(select(User).where(User.email.like("demo.agent%@nestora.vn"))))
    demo_user_ids = [user.id for user in demo_users]
    if demo_user_ids:
        for item in db.scalars(select(Agent).where(Agent.user_id.in_(demo_user_ids))):
            db.delete(item)
    db.flush()
    for user in demo_users:
        db.delete(user)
    for item in db.scalars(select(Agency).where(Agency.slug.like(f"{DEMO_PREFIX}%"))):
        db.delete(item)
    db.flush()
    for item in db.scalars(select(Organization).where(Organization.slug.like(f"{DEMO_PREFIX}%"))):
        db.delete(item)
    db.commit()


def seed_demo_data(
    db: Session,
    *,
    admin: User,
    preset: str = "mvp",
    force_assets: bool = False,
) -> dict[str, int]:
    if preset != "mvp":
        raise ValueError(f"Unsupported demo preset: {preset}")

    agency_rows = _load_fixture("agencies.json")
    agent_rows = _load_fixture("agents.json")
    project_rows = _load_fixture("projects.json")
    property_rows = _load_fixture("properties.json")
    feature_catalog = json.loads((FIXTURE_ROOT / "feature_catalog.json").read_text(encoding="utf-8"))

    orgs: dict[str, Organization] = {}
    agencies: dict[str, Agency] = {}
    for row in agency_rows:
        org, agency = _ensure_org_and_agency(db, row, admin)
        orgs[row["slug"]] = org
        agencies[row["slug"]] = agency
    db.flush()

    agents_by_email: dict[str, Agent] = {}
    agents_by_org: dict[str, list[Agent]] = {}
    for row in agent_rows:
        user = _ensure_user(
            db,
            email=row["email"],
            full_name=row["full_name"],
            role="agent",
            phone=row.get("phone"),
            avatar_url=row.get("avatar_url"),
            password_env="SEED_AGENT_PASSWORD",
        )
        agency = agencies[row["agency_slug"]]
        org = orgs[row["agency_slug"]]
        agent = db.scalar(select(Agent).where(Agent.user_id == user.id))
        if not agent:
            agent = Agent(user_id=user.id, display_name=row["display_name"], phone=row["phone"])
            db.add(agent)
            db.flush()
        agent.organization_id = org.id
        agent.agency_id = agency.id
        agent.display_name = row["display_name"]
        agent.phone = row["phone"]
        agent.email = row.get("email")
        agent.bio = row.get("bio")
        agent.license_number = row.get("license_number")
        agent.verified = bool(row.get("verified"))
        agent.rating = float(row.get("rating", 0))
        _ensure_agent_membership(db, org.id, user.id)
        agents_by_email[row["email"]] = agent
        agents_by_org.setdefault(org.id, []).append(agent)
    db.flush()

    projects: dict[str, Project] = {}
    agency_slugs = [row["slug"] for row in agency_rows]
    for index, row in enumerate(project_rows):
        org = orgs[agency_slugs[index % len(agency_slugs)]]
        item = db.scalar(select(Project).where(Project.slug == row["slug"]))
        if not item:
            item = Project(slug=row["slug"], name=row["name"], city=row["city"], district=row["district"], address=row["address"])
            db.add(item)
            db.flush()
        item.organization_id = org.id
        item.name = row["name"]
        item.developer = row.get("developer")
        item.description = row.get("description")
        item.city = row["city"]
        item.district = row["district"]
        item.address = row["address"]
        item.latitude = row.get("latitude")
        item.longitude = row.get("longitude")
        item.status = row.get("status", "selling")
        item.cover_url = row.get("cover_url")
        projects[row["slug"]] = item
    db.flush()

    now = datetime.now(timezone.utc)
    created = 0
    rebuilt = 0
    for index, raw_spec in enumerate(property_rows):
        spec = _enrich_property_spec(raw_spec, feature_catalog)
        project = projects.get(spec.get("project_slug"))
        requested_agent = agents_by_email[spec["agent_email"]]
        organization_id = project.organization_id if project else requested_agent.organization_id
        candidates = agents_by_org.get(str(organization_id), [])
        agent = candidates[index % len(candidates)] if candidates else requested_agent

        item = db.scalar(select(Property).where(Property.slug == spec["slug"]))
        is_new = item is None
        if is_new:
            item = Property(slug=spec["slug"], title=spec["title"], property_type=spec["property_type"], price=spec["price"], area_m2=spec["area_m2"], address=spec["address"], district=spec["district"], city=spec["city"], description=spec["description"])
            db.add(item)
            db.flush()
            created += 1

        item.organization_id = organization_id
        item.slug = spec["slug"]
        item.title = spec["title"]
        item.transaction_type = spec["transaction_type"]
        item.property_type = spec["property_type"]
        item.status = "published"
        item.price = int(spec["price"])
        item.currency = "VND"
        item.area_m2 = float(spec["area_m2"])
        item.bedrooms = int(spec["bedrooms"])
        item.bathrooms = int(spec["bathrooms"])
        item.floors_count = int(spec["floors_count"])
        item.parking_spaces = int(spec["parking_spaces"])
        item.address = spec["address"]
        item.ward = spec.get("ward")
        item.district = spec["district"]
        item.city = spec["city"]
        item.latitude = float(spec["latitude"])
        item.longitude = float(spec["longitude"])
        item.legal_status = spec.get("legal_status")
        item.furnishing = spec.get("furnishing")
        item.description = spec["description"]
        item.year_built = int(spec["year_built"])
        item.direction = spec.get("direction")
        item.is_featured = bool(spec.get("is_featured"))
        item.is_verified = bool(spec.get("is_verified"))
        item.is_owner_listing = bool(spec.get("is_owner_listing"))
        item.has_3d = bool(spec.get("has_3d"))
        item.agent_id = agent.id
        item.project_id = project.id if project else None
        item.owner_id = admin.id
        item.expires_at = now + timedelta(days=90 + index)
        if is_new or not item.published_at:
            item.published_at = now - timedelta(hours=index * 6)
        item.verified_at = now - timedelta(days=index % 30) if item.is_verified else None

        if force_assets or is_new or not _assets_are_current(item):
            _rebuild_property_assets(db, item, spec)
            rebuilt += 1
        db.flush()

        source_url = f"demo://{item.slug}"
        content = _knowledge_content(spec)
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.source_url == source_url)
        )
        if not document:
            document = KnowledgeDocument(
                property_id=item.id,
                project_id=item.project_id,
                document_type="listing",
                title=f"Dữ liệu xác minh - {item.title}",
                source_url=source_url,
                content=content,
                verified=item.is_verified,
            )
            db.add(document)
            db.flush()
            index_document(db, document)
        else:
            document.property_id = item.id
            document.project_id = item.project_id
            document.title = f"Dữ liệu xác minh - {item.title}"
            document.content = content
            document.verified = item.is_verified

    db.flush()
    for org in orgs.values():
        quota = db.scalar(
            select(ListingQuota).where(
                ListingQuota.organization_id == org.id,
                ListingQuota.key == "published_listings",
            )
        )
        if quota:
            quota.used_value = int(
                db.scalar(
                    select(func.count(Property.id)).where(
                        Property.organization_id == org.id,
                        Property.status == "published",
                    )
                )
                or 0
            )
    db.commit()

    return {
        "agencies": len(agency_rows),
        "agents": len(agent_rows),
        "projects": len(project_rows),
        "properties": len(property_rows),
        "properties_3d": sum(bool(row.get("has_3d")) for row in property_rows),
        "created": created,
        "assets_rebuilt": rebuilt,
    }
