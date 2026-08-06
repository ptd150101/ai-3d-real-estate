from __future__ import annotations

import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Agency, Agent, Property, User
from .security import hash_password
from .services.demo_seed import seed_demo_data
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
    result = seed_demo_data(db, admin=admin, preset="mvp")
    _ensure_compatibility_agent(db, compatibility_agent_user)
    ensure_default_tenant(db)
    db.commit()
    return result
