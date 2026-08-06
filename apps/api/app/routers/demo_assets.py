from __future__ import annotations

import hashlib
import re

from fastapi import APIRouter, HTTPException, Response

from ..config import get_settings
from ..demo_assets import build_demo_glb, build_demo_svg, get_model_template

router = APIRouter(tags=["demo-assets"])
_SAFE_ASSET = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def _require_fixture_mode() -> None:
    if not get_settings().fixtures_allowed:
        raise HTTPException(status_code=404, detail="Not found")


def _cached_response(data: bytes, media_type: str) -> Response:
    etag = hashlib.sha256(data).hexdigest()
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "cache-control": "public, max-age=86400, immutable",
            "etag": f'"{etag}"',
            "x-content-type-options": "nosniff",
        },
    )


@router.get("/demo-assets/models/{template_id}.glb")
def demo_model(template_id: str) -> Response:
    _require_fixture_mode()
    if not _SAFE_ASSET.fullmatch(template_id):
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        get_model_template(template_id)
        data = build_demo_glb(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Model not found") from exc
    return _cached_response(data, "model/gltf-binary")


@router.get("/demo-assets/images/{category}/{asset_key}.svg")
def demo_image(category: str, asset_key: str) -> Response:
    _require_fixture_mode()
    if not _SAFE_ASSET.fullmatch(category) or not _SAFE_ASSET.fullmatch(asset_key):
        raise HTTPException(status_code=404, detail="Image not found")
    return _cached_response(build_demo_svg(category, asset_key), "image/svg+xml")
