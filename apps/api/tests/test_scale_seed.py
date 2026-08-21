from __future__ import annotations

from sqlalchemy import func, select

from app.models import Property, PropertyMedia
from app.seed import seed_database
from app.services.scale_seed import SCALE_PREFIX, reset_scale_properties, seed_scale_properties
from conftest import TestingSessionLocal


def test_scale_seed_reaches_target_and_is_idempotent():
    with TestingSessionLocal() as db:
        reset_scale_properties(db)
        try:
            result = seed_scale_properties(db, target_total=272, batch_size=50)
            assert result["properties"] == 272
            assert result["showcase_properties"] == 72
            assert result["scale_properties"] == 200
            assert result["scale_created"] == 200

            scale_count = int(
                db.scalar(
                    select(func.count(Property.id)).where(
                        Property.slug.like(f"{SCALE_PREFIX}%")
                    )
                )
                or 0
            )
            media_count = int(
                db.scalar(
                    select(func.count(PropertyMedia.id))
                    .join(Property, Property.id == PropertyMedia.property_id)
                    .where(Property.slug.like(f"{SCALE_PREFIX}%"))
                )
                or 0
            )
            assert scale_count == media_count == 200

            types = set(
                db.scalars(
                    select(Property.property_type).where(
                        Property.slug.like(f"{SCALE_PREFIX}%")
                    )
                )
            )
            districts = set(
                db.scalars(
                    select(Property.district).where(
                        Property.slug.like(f"{SCALE_PREFIX}%")
                    )
                )
            )
            assert types == {"apartment", "townhouse", "villa", "shophouse", "studio", "penthouse"}
            assert len(districts) == 14

            rerun = seed_scale_properties(db, target_total=272, batch_size=50)
            assert rerun["properties"] == 272
            assert rerun["scale_created"] == 0
        finally:
            removed = reset_scale_properties(db)
            assert removed == 200


def test_scale_seed_can_resume_to_a_larger_target():
    with TestingSessionLocal() as db:
        reset_scale_properties(db)
        try:
            first = seed_scale_properties(db, target_total=122, batch_size=25)
            assert first["scale_properties"] == 50
            assert first["scale_created"] == 50

            second = seed_scale_properties(db, target_total=172, batch_size=25)
            assert second["scale_properties"] == 100
            assert second["scale_created"] == 50
            assert int(db.scalar(select(func.count(Property.id))) or 0) == 172
        finally:
            reset_scale_properties(db)


def test_normal_startup_seed_preserves_scale_dataset():
    with TestingSessionLocal() as db:
        reset_scale_properties(db)
        try:
            seed_scale_properties(db, target_total=92, batch_size=20)
            seed_database(db)
            assert int(
                db.scalar(
                    select(func.count(Property.id)).where(
                        Property.slug.like(f"{SCALE_PREFIX}%")
                    )
                )
                or 0
            ) == 20
            assert int(db.scalar(select(func.count(Property.id))) or 0) == 92
        finally:
            reset_scale_properties(db)


def test_scale_rows_are_older_than_showcase_and_have_local_cover_assets():
    with TestingSessionLocal() as db:
        reset_scale_properties(db)
        try:
            seed_scale_properties(db, target_total=92, batch_size=20)
            item = db.scalar(
                select(Property)
                .where(Property.slug.like(f"{SCALE_PREFIX}%"))
                .order_by(Property.slug)
                .limit(1)
            )
            assert item is not None
            assert item.is_featured is False
            assert item.has_3d is False
            assert item.city == "Hà Nội"
            assert item.media[0].url.startswith("/api/backend/demo-assets/images/")
            assert (item.media[0].metadata_json or {}).get("scale") is True
        finally:
            reset_scale_properties(db)
