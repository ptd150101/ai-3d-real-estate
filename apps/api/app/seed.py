from __future__ import annotations

import json
import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Agency,
    Agent,
    KnowledgeChunk,
    KnowledgeDocument,
    NearbyPlace,
    Project,
    Property,
    User,
)
from .security import hash_password
from .services.demo_seed import FIXTURE_ROOT, reset_demo_data, seed_demo_data
from .services.p2_intelligence import DISTRICT_PRICE_M2, TYPE_FACTOR
from .services.p2_tenant import ensure_default_tenant

_DEMO_DISTRICT_PRICE_M2 = {
    "Tây Hồ": 95_000_000,
    "Cầu Giấy": 88_000_000,
    "Long Biên": 70_000_000,
    "Nam Từ Liêm": 72_000_000,
    "Hà Đông": 62_000_000,
    "Ba Đình": 105_000_000,
    "Thanh Xuân": 78_000_000,
    "Hai Bà Trưng": 92_000_000,
    "Hoàng Mai": 60_000_000,
    "Gia Lâm": 58_000_000,
    "Đông Anh": 52_000_000,
}
_DEMO_TYPE_FACTORS = {
    "apartment": 1.0,
    "townhouse": 1.12,
    "villa": 1.25,
    "shophouse": 1.18,
    "studio": 0.92,
    "penthouse": 1.32,
}
_LEGACY_PROPERTY_SLUGS = {
    "nha-pho-hien-dai-cau-giay",
    "can-ho-3pn-view-ho-tay",
    "biet-thu-san-vuon-long-bien",
    "chung-cu-2pn-nam-tu-liem",
    "shophouse-ha-dong",
    "nha-thue-tay-ho-co-3d",
}


def _ensure_core_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    role: str,
    phone: str,
    password_env: str,
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        user.full_name = full_name
        user.role = role
        user.phone = phone
        user.is_active = True
        return user
    password = os.getenv(password_env) or secrets.token_urlsafe(32)
    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        phone=phone,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _ensure_compatibility_agent(db: Session, user: User) -> Agent:
    """Preserve the original local agent login used by P1 flows and tests."""
    first_property = db.scalar(
        select(Property)
        .where(Property.slug.like("demo-%"), Property.status == "published")
        .order_by(
            Property.is_featured.desc(),
            Property.published_at.desc(),
            Property.created_at.desc(),
        )
        .limit(1)
    )
    agency = None
    if first_property and first_property.organization_id:
        agency = db.scalar(
            select(Agency)
            .where(Agency.organization_id == first_property.organization_id)
            .order_by(Agency.name)
            .limit(1)
        )

    agent = db.scalar(select(Agent).where(Agent.user_id == user.id))
    if not agent:
        agent = Agent(user_id=user.id, display_name="Trần Hoàng Nam", phone="0987654321")
        db.add(agent)
        db.flush()
    agent.organization_id = first_property.organization_id if first_property else None
    agent.agency_id = agency.id if agency else None
    agent.display_name = "Trần Hoàng Nam"
    agent.phone = "0987654321"
    agent.email = user.email
    agent.bio = "Chuyên nhà phố và căn hộ cao cấp Hà Nội."
    agent.license_number = "HN-REA-2026-001"
    agent.verified = True
    agent.rating = 5.0
    if first_property:
        first_property.agent_id = agent.id
    return agent


def _install_demo_valuation_baseline() -> None:
    """Cover every district and property type represented by the demo catalog."""
    DISTRICT_PRICE_M2.update(_DEMO_DISTRICT_PRICE_M2)
    TYPE_FACTOR.update(_DEMO_TYPE_FACTORS)


def _remove_legacy_seed_records(db: Session) -> None:
    """Remove the six pre-catalog listings without touching user-created data."""
    properties = list(
        db.scalars(select(Property).where(Property.slug.in_(_LEGACY_PROPERTY_SLUGS)))
    )
    property_ids = [item.id for item in properties]
    if property_ids:
        documents = list(
            db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.property_id.in_(property_ids)
                )
            )
        )
        document_ids = [document.id for document in documents]
        if document_ids:
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.document_id.in_(document_ids)
            ).delete(synchronize_session=False)
        for document in documents:
            db.delete(document)
        db.query(NearbyPlace).filter(NearbyPlace.property_id.in_(property_ids)).delete(
            synchronize_session=False
        )
        for item in properties:
            db.delete(item)
        db.flush()

    legacy_project = db.scalar(
        select(Project).where(
            Project.slug == "westlake-residence",
            Project.name == "Westlake Residence",
        )
    )
    if legacy_project:
        db.delete(legacy_project)
        db.flush()


def _reset_stale_demo_catalog(db: Session) -> None:
    # Replace older fixture revisions instead of accumulating duplicate listings.
    rows = json.loads((FIXTURE_ROOT / "properties.json").read_text(encoding="utf-8"))
    desired_slugs = {str(row["slug"]) for row in rows}
    current_slugs = set(
        db.scalars(select(Property.slug).where(Property.slug.like("demo-%")))
    )
    if current_slugs and current_slugs != desired_slugs:
        reset_demo_data(db)


def _adopt_legacy_demo_agencies(db: Session) -> None:
    """Reuse pre-catalog agencies whose unique name matches a demo fixture.

    Older seed revisions created agencies such as ``Nestora Prime`` under a
    non-demo slug. The current catalog uses canonical ``demo-*`` slugs, while
    ``agencies.name`` is unique. Migrating the existing row avoids a duplicate
    name INSERT and preserves foreign-key references.
    """
    rows = json.loads((FIXTURE_ROOT / "agencies.json").read_text(encoding="utf-8"))
    for row in rows:
        canonical_slug = str(row["slug"])
        if db.scalar(select(Agency.id).where(Agency.slug == canonical_slug)):
            continue
        legacy = db.scalar(select(Agency).where(Agency.name == str(row["name"])))
        if legacy:
            legacy.slug = canonical_slug
    db.flush()


def seed_database(db: Session) -> dict[str, int]:
    """Upsert deterministic local demo data without duplicating existing records."""
    _install_demo_valuation_baseline()
    admin = _ensure_core_user(
        db,
        email="admin@nestora.vn",
        full_name="Nestora Admin",
        role="admin",
        phone="0900000000",
        password_env="SEED_ADMIN_PASSWORD",
    )
    _ensure_core_user(
        db,
        email="buyer@nestora.vn",
        full_name="Nguyễn Minh Anh",
        role="buyer",
        phone="0912345678",
        password_env="SEED_BUYER_PASSWORD",
    )
    compatibility_agent_user = _ensure_core_user(
        db,
        email="agent@nestora.vn",
        full_name="Trần Hoàng Nam",
        role="agent",
        phone="0987654321",
        password_env="SEED_AGENT_PASSWORD",
    )
    db.flush()
    _remove_legacy_seed_records(db)
    _reset_stale_demo_catalog(db)
    _adopt_legacy_demo_agencies(db)
    result = seed_demo_data(db, admin=admin, preset="mvp")
    _ensure_compatibility_agent(db, compatibility_agent_user)
    ensure_default_tenant(db)
    db.commit()
    return result
