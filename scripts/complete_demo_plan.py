from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    content = target.read_text(encoding="utf-8")
    if old not in content:
        raise RuntimeError(f"Expected text not found in {path}: {old[:80]!r}")
    target.write_text(content.replace(old, new, 1), encoding="utf-8")


def ascii_slug(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()


properties_path = ROOT / "apps/api/app/fixtures/demo/properties.json"
properties = json.loads(properties_path.read_text(encoding="utf-8"))
for row in properties:
    row["slug"] = ascii_slug(str(row["slug"]))
assert len(properties) == 72
assert len({row["slug"] for row in properties}) == 72
assert all(re.fullmatch(r"[a-z0-9-]+", row["slug"]) for row in properties)
properties_path.write_text(
    json.dumps(properties, ensure_ascii=False, separators=(",", ":")) + "\n",
    encoding="utf-8",
)

replace_once(
    "apps/api/app/services/demo_seed.py",
    "DEMO_DATASET_VERSION = 2",
    "DEMO_DATASET_VERSION = 3",
)
replace_once(
    "apps/api/app/seed.py",
    "from __future__ import annotations\n\nimport os",
    "from __future__ import annotations\n\nimport json\nimport os",
)
replace_once(
    "apps/api/app/seed.py",
    "from .services.demo_seed import seed_demo_data",
    "from .services.demo_seed import FIXTURE_ROOT, reset_demo_data, seed_demo_data",
)
replace_once(
    "apps/api/app/seed.py",
    "\ndef seed_database(db: Session) -> dict[str, int]:",
    '''

def _reset_stale_demo_catalog(db: Session) -> None:
    # Replace older fixture revisions instead of accumulating duplicate listings.
    rows = json.loads((FIXTURE_ROOT / "properties.json").read_text(encoding="utf-8"))
    desired_slugs = {str(row["slug"]) for row in rows}
    current_slugs = set(
        db.scalars(select(Property.slug).where(Property.slug.like("demo-%")))
    )
    if current_slugs and current_slugs != desired_slugs:
        reset_demo_data(db)


def seed_database(db: Session) -> dict[str, int]:''',
)
replace_once(
    "apps/api/app/seed.py",
    "    db.flush()\n    result = seed_demo_data(db, admin=admin, preset=\"mvp\")",
    "    db.flush()\n    _reset_stale_demo_catalog(db)\n    result = seed_demo_data(db, admin=admin, preset=\"mvp\")",
)

write(
    "apps/api/app/routers/properties.py",
    '''
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Property
from ..schemas import (
    NaturalSearchRequest,
    NaturalSearchResponse,
    PaginatedProperties,
    PropertyDetail,
    SearchFilters,
)
from ..services.search import (
    get_facets,
    parse_natural_query,
    property_query_options,
    search_properties,
)
from ..services.serializers import property_detail, property_summary

router = APIRouter(prefix="/properties", tags=["properties"])
_LEGACY_PROPERTY_IDENTIFIER = "nha-pho-hien-dai-cau-giay"


def _property_statement(identifier: str, *, details: bool):
    stmt = select(Property).where(
        (Property.id == identifier) | (Property.slug == identifier)
    )
    return stmt.options(*property_query_options()) if details else stmt


def _find_property(
    db: Session,
    identifier: str,
    *,
    details: bool = False,
) -> Property | None:
    item = db.scalar(_property_statement(identifier, details=details))
    if item or identifier != _LEGACY_PROPERTY_IDENTIFIER:
        return item

    stmt = (
        select(Property)
        .where(
            Property.slug.like("demo-%"),
            Property.status == "published",
            Property.district == "Cầu Giấy",
            Property.has_3d.is_(True),
        )
        .order_by(
            (Property.property_type == "townhouse").desc(),
            Property.is_featured.desc(),
            Property.published_at.desc(),
            Property.created_at.desc(),
        )
        .limit(1)
    )
    if details:
        stmt = stmt.options(*property_query_options())
    return db.scalar(stmt)


@router.get("", response_model=PaginatedProperties)
def list_properties(
    q: str | None = None,
    transaction_type: str | None = None,
    property_type: list[str] = Query(default=[]),
    city: str | None = None,
    district: list[str] = Query(default=[]),
    min_price: int | None = None,
    max_price: int | None = None,
    min_area: float | None = None,
    max_area: float | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    legal_status: list[str] = Query(default=[]),
    furnishing: list[str] = Query(default=[]),
    has_3d: bool | None = None,
    is_owner_listing: bool | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    sort: str = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=48),
    db: Session = Depends(get_db),
) -> PaginatedProperties:
    filters = SearchFilters(**locals())
    items, total = search_properties(db, filters, page, page_size)
    return PaginatedProperties(
        items=[property_summary(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
        facets=get_facets(db),
    )


@router.post("/parse-search", response_model=NaturalSearchResponse)
def natural_search(payload: NaturalSearchRequest) -> NaturalSearchResponse:
    filters, explanation = parse_natural_query(payload.query)
    return NaturalSearchResponse(filters=filters, explanation=explanation)


@router.get("/{identifier}", response_model=PropertyDetail)
def get_property(identifier: str, db: Session = Depends(get_db)) -> PropertyDetail:
    item = _find_property(db, identifier, details=True)
    if not item or item.status not in {"published", "sold", "rented"}:
        raise HTTPException(status_code=404, detail="Property not found")
    item.view_count += 1
    db.commit()
    return property_detail(db, item)


@router.get("/{identifier}/similar", response_model=list[PropertyDetail])
def similar_properties(
    identifier: str,
    limit: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
) -> list[PropertyDetail]:
    current = _find_property(db, identifier)
    if not current:
        raise HTTPException(status_code=404, detail="Property not found")
    price_margin = max(500_000_000, int(current.price * 0.3))
    stmt = (
        select(Property)
        .where(
            Property.id != current.id,
            Property.status == "published",
            Property.city == current.city,
            Property.price.between(
                current.price - price_margin,
                current.price + price_margin,
            ),
        )
        .options(*property_query_options())
        .order_by(
            (Property.district == current.district).desc(),
            Property.is_featured.desc(),
        )
        .limit(limit)
    )
    return [property_detail(db, item) for item in db.scalars(stmt).unique()]
''',
)

write(
    "apps/web/app/api/backend/[...path]/route.ts",
    '''
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { API_URL } from "@/lib/api";

function encodePathSegment(segment: string): string {
  try {
    return encodeURIComponent(decodeURIComponent(segment));
  } catch {
    return encodeURIComponent(segment);
  }
}

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const cookieStore = await cookies();
  const token = cookieStore.get("nestora_token")?.value;
  const organizationId = cookieStore.get("nestora_org")?.value;
  const target = new URL(`${API_URL}/${path.map(encodePathSegment).join("/")}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value);
  });

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", request.headers.get("accept") || "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (organizationId) headers.set("x-organization-id", organizationId);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const body = hasBody ? await request.arrayBuffer() : undefined;
  const response = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = new Headers();
  const responseType = response.headers.get("content-type");
  if (responseType) responseHeaders.set("content-type", responseType);
  return new NextResponse(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
''',
)

write(
    "apps/api/tests/test_demo_dataset.py",
    '''
from __future__ import annotations

import re
import struct
from collections import Counter

from sqlalchemy import func, select

from app.demo_assets import model_templates
from app.models import Agency, Agent, Project, Property
from app.seed import seed_database
from conftest import TestingSessionLocal


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
''',
)

write(
    "apps/web/tests/e2e/helpers.ts",
    '''
import type { APIRequestContext } from "@playwright/test";

export type PropertySummary = {
  slug: string;
  title: string;
  property_type: string;
  has_3d: boolean;
};

type PropertyList = { items: PropertySummary[] };

export async function firstDemoProperty(
  request: APIRequestContext,
  query = "has_3d=true&page_size=1",
): Promise<PropertySummary> {
  const response = await request.get(`/api/backend/properties?${query}`);
  if (!response.ok()) throw new Error(`Property lookup failed: ${response.status()}`);
  const payload = (await response.json()) as PropertyList;
  const property = payload.items[0];
  if (!property) throw new Error("Demo property catalog is empty");
  return property;
}
''',
)

write(
    "apps/web/tests/e2e/smoke.spec.ts",
    '''
import { expect, test } from "@playwright/test";
import { firstDemoProperty } from "./helpers";

test("home and search flow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Tìm ngôi nhà/ })).toBeVisible();
  await page.getByLabel("Yêu cầu tìm kiếm").fill("Nhà Cầu Giấy dưới 13 tỷ có 3D");
  await page.getByRole("button", { name: "Tìm bất động sản" }).click();
  await expect(page).toHaveURL(/properties/);
  await expect(page.getByText(/kết quả/)).toBeVisible();
});

test("property detail exposes chatbot", async ({ page }) => {
  const property = await firstDemoProperty(page.request);
  await page.goto(`/properties/${property.slug}`);
  await expect(page.getByRole("heading", { name: property.title }).first()).toBeVisible();
  await expect(page.getByLabel("Trợ lý bất động sản AI").first()).toBeVisible();
});
''',
)

write(
    "apps/web/tests/e2e/p1.spec.ts",
    '''
import { expect, test } from "@playwright/test";
import { firstDemoProperty } from "./helpers";

test("P1 buyer account surfaces", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("buyer@nestora.vn");
  await page.getByLabel("Mật khẩu").fill(process.env.E2E_BUYER_PASSWORD || "ci-e2e-buyer-password");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/account/notifications");
  await expect(page.getByRole("heading", { name: "Thông báo" })).toBeVisible();
  await page.goto("/account/saved-searches");
  await expect(page.getByRole("heading", { name: "Tìm kiếm đã lưu" })).toBeVisible();
  await page.goto("/messages");
  await expect(page.getByRole("heading", { name: "Tin nhắn trực tiếp" })).toBeVisible();
});

test("P1 public experience remains progressively enhanced", async ({ page }) => {
  const property = await firstDemoProperty(page.request);
  await page.goto(`/properties/${property.slug}`);
  await expect(page.getByRole("heading", { name: property.title }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Di chuyển giữa các phòng" })).toBeVisible();
  await expect(page.getByRole("button", { name: /brochure/i })).toBeVisible();
});

test("legacy property URL remains compatible", async ({ page }) => {
  await page.goto("/properties/nha-pho-hien-dai-cau-giay");
  await expect(page.locator("h1")).toBeVisible();
  await expect(page.getByText("Property not found")).toHaveCount(0);
});
''',
)

write(
    "apps/web/tests/e2e/dollhouse.spec.ts",
    '''
import { expect, test } from "@playwright/test";
import { firstDemoProperty } from "./helpers";

test("dollhouse loads GLB and exposes its core controls", async ({ page }) => {
  const property = await firstDemoProperty(
    page.request,
    "has_3d=true&property_type=villa&page_size=1",
  );
  await page.goto(`/properties/${property.slug}`);
  const [assetResponse] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().endsWith(".glb") && response.status() === 200,
      { timeout: 20_000 },
    ),
    page.getByRole("button", { name: "Bắt đầu xem 3D" }).click(),
  ]);
  expect(assetResponse.headers()["content-type"]).toContain("model/gltf-binary");
  await expect(page.locator(".viewer-canvas canvas")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("● Live 3D")).toBeVisible();
  await expect(page.getByText("Không thể tải mô hình 3D")).toHaveCount(0);
  await page.getByRole("button", { name: "Xoay tự do" }).click();
  await expect(page.getByText("Orbit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dollhouse" }).click();
  await expect(page.getByText("Dollhouse", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "Ẩn nội thất" }).click();
  await expect(page.getByRole("button", { name: "Hiện nội thất" })).toBeVisible();
  await page.getByRole("button", { name: "Hiện mái" }).click();
  await expect(page.getByRole("button", { name: "Ẩn mái" })).toBeVisible();
  const floorToggle = page.getByRole("button", { name: /^(Ghép tầng|Tách tầng)$/ });
  await expect(floorToggle).toBeVisible();
  const before = await floorToggle.textContent();
  await floorToggle.click();
  await expect(floorToggle).not.toHaveText(before || "");
  await page.getByRole("button", { name: "Reset camera" }).click();
  const hotspot = page.getByRole("button", { name: /Mở thông tin/ }).first();
  await expect(hotspot).toBeVisible({ timeout: 15_000 });
  await hotspot.click();
  await expect(page.locator(".viewer-hotspot-card")).toBeVisible();
});
''',
)

readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme = readme.replace(
    "- 72 published properties across 11 Hà Nội districts.",
    "- 72 published properties across 11 Hà Nội districts, with ASCII-only canonical slugs and compatibility for the original public demo URL.",
)
readme_path.write_text(readme, encoding="utf-8")
