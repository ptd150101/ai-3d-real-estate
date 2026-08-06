from __future__ import annotations

import re
import struct
from collections import Counter

from sqlalchemy import func, select

from app.demo_assets import model_templates
from app.models import Agency, Agent, Project, Property
from app.seed import seed_database
from app.services.demo_seed import reset_demo_data
from conftest import TestingSessionLocal

_LEGACY_PROPERTY_SLUGS = [
    "nha-pho-hien-dai-cau-giay",
    "can-ho-3pn-view-ho-tay",
    "biet-thu-san-vuon-long-bien",
    "chung-cu-2pn-nam-tu-liem",
    "shophouse-ha-dong",
    "nha-thue-tay-ho-co-3d",
]


def test_demo_dataset_counts_and_idempotency():
    with TestingSessionLocal() as db:
        before = int(db.scalar(select(func.count(Property.id))) or 0)
        seed_database(db)
        after = int(db.scalar(select(func.count(Property.id))) or 0)
        rows = list(db.scalars(select(Property).where(Property.slug.like("demo-%"))))
        slugs = [item.slug for item in rows]
        assert before == after == 72
        assert len(rows) == 72
        assert len(set(slugs)) == 72
        assert all(re.fullmatch(r"[a-z0-9-]+", slug) for slug in slugs)
        assert sum(item.has_3d for item in rows) == 24
        assert sum(item.is_verified for item in rows) == 48
        assert sum(item.is_owner_listing for item in rows) == 20
        assert sum(item.is_featured for item in rows) == 12
        assert sum(item.project_id is not None for item in rows) == 18
        assert Counter(item.transaction_type for item in rows) == {"sale": 48, "rent": 24}
        assert Counter(item.property_type for item in rows) == {
            "apartment": 28,
            "townhouse": 16,
            "villa": 10,
            "shophouse": 8,
            "studio": 6,
            "penthouse": 4,
        }
        assert int(db.scalar(select(func.count(Agency.id)).where(Agency.slug.like("demo-%"))) or 0) == 4
        assert int(db.scalar(select(func.count(Agent.id)).where(Agent.email.like("demo.agent%@nestora.vn"))) or 0) == 12
        assert int(db.scalar(select(func.count(Project.id)).where(Project.slug.like("demo-%"))) or 0) == 6


def test_seed_replaces_stale_unicode_fixture_revision():
    with TestingSessionLocal() as db:
        item = db.scalar(
            select(Property).where(Property.slug.like("demo-%")).order_by(Property.slug).limit(1)
        )
        assert item is not None
        canonical_slug = item.slug
        item.slug = "demo-legacy-dông-anh"
        db.commit()
        seed_database(db)
        assert db.scalar(select(Property).where(Property.slug == "demo-legacy-dông-anh")) is None
        assert db.scalar(select(Property).where(Property.slug == canonical_slug)) is not None
        assert int(db.scalar(select(func.count(Property.id)).where(Property.slug.like("demo-%"))) or 0) == 72


def test_seed_adopts_legacy_agency_name_after_reset():
    with TestingSessionLocal() as db:
        reset_demo_data(db)
        legacy = Agency(name="Nestora Prime", slug="nestora-prime")
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id

        seed_database(db)

        canonical = db.scalar(select(Agency).where(Agency.slug == "demo-nestora-prime"))
        assert canonical is not None
        assert canonical.id == legacy_id
        assert int(
            db.scalar(select(func.count(Agency.id)).where(Agency.name == "Nestora Prime")) or 0
        ) == 1
        assert int(
            db.scalar(select(func.count(Agency.id)).where(Agency.slug.like("demo-%"))) or 0
        ) == 4


def test_seed_removes_pre_catalog_properties_and_project():
    with TestingSessionLocal() as db:
        rows = list(
            db.scalars(
                select(Property)
                .where(Property.slug.like("demo-%"))
                .order_by(Property.slug)
                .limit(len(_LEGACY_PROPERTY_SLUGS))
            )
        )
        assert len(rows) == len(_LEGACY_PROPERTY_SLUGS)
        for item, legacy_slug in zip(rows, _LEGACY_PROPERTY_SLUGS, strict=True):
            item.slug = legacy_slug
        db.add(
            Project(
                name="Westlake Residence",
                slug="westlake-residence",
                city="Hà Nội",
                district="Tây Hồ",
                address="Đường Võ Chí Công, Tây Hồ, Hà Nội",
            )
        )
        db.commit()

        seed_database(db)

        assert int(db.scalar(select(func.count(Property.id))) or 0) == 72
        assert int(
            db.scalar(
                select(func.count(Property.id)).where(
                    Property.slug.in_(_LEGACY_PROPERTY_SLUGS)
                )
            )
            or 0
        ) == 0
        assert db.scalar(select(Project).where(Project.slug == "westlake-residence")) is None
        assert int(
            db.scalar(select(func.count(Property.id)).where(Property.slug.like("demo-%"))) or 0
        ) == 72


def test_property_search_has_enough_data(client):
    response = client.get("/api/v1/properties", params={"page": 1, "page_size": 48})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 72
    assert payload["pages"] == 2
    assert len(payload["items"]) == 48
    three_d = client.get("/api/v1/properties", params={"has_3d": True, "page_size": 48})
    assert three_d.status_code == 200, three_d.text
    assert three_d.json()["total"] == 24
    rent = client.get("/api/v1/properties", params={"transaction_type": "rent", "page_size": 48})
    assert rent.status_code == 200, rent.text
    assert rent.json()["total"] == 24


def test_legacy_property_url_resolves_to_current_catalog(client):
    response = client.get("/api/v1/properties/nha-pho-hien-dai-cau-giay")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["slug"].startswith("demo-")
    assert payload["district"] == "Cầu Giấy"
    assert payload["has_3d"] is True


def test_demo_property_has_complete_related_data(client):
    search = client.get("/api/v1/properties", params={"has_3d": True, "page_size": 1})
    slug = search.json()["items"][0]["slug"]
    response = client.get(f"/api/v1/properties/{slug}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["media"]) == 5
    assert 5 <= len(payload["features"]) <= 9
    assert len(payload["nearby_places"]) == 4
    assert payload["model_3d"]["model_url"].endswith(".glb")
    assert payload["model_3d"]["floors"]
    assert payload["model_3d"]["hotspots"]


def test_generated_demo_assets_are_valid(client):
    response = client.get("/api/v1/demo-assets/models/apartment-3br.glb")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("model/gltf-binary")
    assert response.content[:4] == b"glTF"
    version, total_length = struct.unpack("<II", response.content[4:12])
    assert version == 2
    assert total_length == len(response.content)
    assert len(response.content) > 2_000
    payloads: list[bytes] = []
    for template_id in model_templates():
        asset = client.get(f"/api/v1/demo-assets/models/{template_id}.glb")
        assert asset.status_code == 200, asset.text
        assert asset.content[:4] == b"glTF"
        payloads.append(asset.content)
    assert len(payloads) == 8
    assert len(set(payloads)) == 8
    image = client.get("/api/v1/demo-assets/images/apartment/1.svg")
    assert image.status_code == 200, image.text
    assert image.headers["content-type"].startswith("image/svg+xml")
    assert image.content.startswith(b"<svg")
