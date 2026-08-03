from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.services.media_processing import generate_thumbnail, optimize_3d_model
from app.services.reconstruction_backends import ReconstructionInput, _materialize_inputs


def _admin_org(client, admin_headers):
    response = client.get("/api/v1/organizations/me", headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()[0]["id"]


def _property(client):
    response = client.get("/api/v1/properties?page_size=1")
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


def test_capture_multipart_upload_and_job_listing(client, admin_headers):
    organization_id = _admin_org(client, admin_headers)
    prop = _property(client)
    headers = {**admin_headers, "X-Organization-ID": organization_id}
    created = client.post(
        "/api/v1/captures",
        headers=headers,
        json={
            "property_id": prop["id"],
            "capture_type": "images",
            "requirements": {"source": "mobile", "minimum_images": 1},
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    uploaded = client.post(
        f"/api/v1/captures/{session_id}/upload",
        headers=headers,
        files={"file": ("capture.jpg", b"fixture-capture-bytes", "image/jpeg")},
        data={"metadata": json.dumps({"sequence": 1, "width": 1920, "height": 1080})},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["sha256"] == hashlib.sha256(b"fixture-capture-bytes").hexdigest()
    assert uploaded.json()["sequence"] == 1

    queued = client.post(
        f"/api/v1/captures/{session_id}/reconstruct",
        headers=headers,
        json={"representation": "glb"},
    )
    assert queued.status_code == 202, queued.text
    processed = client.post(
        f"/api/v1/reconstruction-jobs/{queued.json()['id']}/run-local",
        headers=headers,
    )
    assert processed.status_code == 200, processed.text

    jobs = client.get("/api/v1/reconstruction-jobs", headers=headers)
    assert jobs.status_code == 200, jobs.text
    selected = next(item for item in jobs.json() if item["id"] == queued.json()["id"])
    assert selected["artifact"]["id"] == processed.json()["artifact_id"]
    assert selected["status"] == "review"


def test_private_capture_materialization(monkeypatch, tmp_path):
    data = b"private-capture"
    monkeypatch.setattr(
        "app.services.reconstruction_backends.read_private_bytes",
        lambda key: data if key == "captures/example.jpg" else b"",
    )
    target = tmp_path / "inputs"
    paths = _materialize_inputs(
        [
            ReconstructionInput(
                url="private://captures/example.jpg",
                sha256=hashlib.sha256(data).hexdigest(),
                mime_type="image/jpeg",
                size_bytes=len(data),
            )
        ],
        target_dir=target,
        settings=get_settings(),
    )
    assert len(paths) == 1
    assert paths[0].read_bytes() == data


def test_media_jobs_perform_real_processing():
    settings = get_settings()
    source_dir = settings.storage_path / "private" / "completion-tests"
    source_dir.mkdir(parents=True, exist_ok=True)

    image_buffer = io.BytesIO()
    Image.new("RGB", (2048, 1024), "white").save(image_buffer, format="JPEG")
    image_path = source_dir / "panorama.jpg"
    image_path.write_bytes(image_buffer.getvalue())
    thumbnail = generate_thumbnail({"url": str(image_path), "filename": image_path.name})
    assert thumbnail["status"] == "ready"
    assert thumbnail["size_bytes"] > 0
    assert thumbnail["sha256"]

    body = bytes(116)
    glb = b"glTF" + (2).to_bytes(4, "little") + (128).to_bytes(4, "little") + body
    model_path = source_dir / "room.glb"
    model_path.write_bytes(glb)
    optimized = optimize_3d_model({"url": str(model_path), "filename": model_path.name})
    assert optimized["validation"]["format"] == "glb"
    assert optimized["output_sha256"]
    assert optimized["output_size"] > 0


def test_worker_has_no_success_stubs():
    source = (Path(__file__).parents[1] / "app" / "worker.py").read_text(encoding="utf-8")
    assert "production optimization adapter is ready" not in source
    assert 'return {"status": "validated"' not in source
    assert 'return {"status": "ready", "grant_id"' not in source
    assert "optimize_3d_model" in source
    assert "validate_panorama_scene" in source
    assert "watermark_grant_document" in source
