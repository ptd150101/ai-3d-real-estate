from __future__ import annotations

import os
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .security import hash_password
from .services.demo_seed import seed_demo_data
from .services.p2_tenant import ensure_default_tenant


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


def seed_database(db: Session) -> dict[str, int]:
    """Upsert deterministic local demo data without duplicating existing records."""
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
    db.flush()
    result = seed_demo_data(db, admin=admin, preset="mvp")
    ensure_default_tenant(db)
    db.commit()
    return result
