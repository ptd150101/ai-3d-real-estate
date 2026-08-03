from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    DocumentAccessGrant,
    KnowledgeDocument,
    LegalDocumentVersion,
    PanoramaScene,
)
from .legal import watermark_pdf
from .rag import index_document
from .storage import (
    StorageError,
    read_private_bytes,
    save_local_bytes,
    save_private_bytes,
    save_s3_bytes,
)


class MediaProcessingError(RuntimeError):
    pass


MAX_MEDIA_BYTES = 500 * 1024 * 1024


def _read_source(value: str) -> bytes:
    settings = get_settings()
    if value.startswith("private://"):
        return read_private_bytes(value.removeprefix("private://"))

    marker = "/storage/"
    if marker in value:
        relative = value.split(marker, 1)[1]
        path = (settings.storage_path / relative).resolve()
        root = settings.storage_path.resolve()
        if path != root and root not in path.parents:
            raise MediaProcessingError("Storage path escapes configured root")
        data = path.read_bytes()
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaProcessingError("Media source exceeds 500 MB")
        return data

    path = Path(value)
    if path.is_absolute():
        resolved = path.resolve()
        root = settings.storage_path.resolve()
        if resolved != root and root not in resolved.parents:
            raise MediaProcessingError("Absolute media path is outside storage root")
        data = resolved.read_bytes()
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaProcessingError("Media source exceeds 500 MB")
        return data

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        try:
            with httpx.stream(
                "GET",
                value,
                timeout=settings.provider_http_timeout_seconds,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                buffer = io.BytesIO()
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_MEDIA_BYTES:
                        raise MediaProcessingError("Downloaded media exceeds 500 MB")
                    buffer.write(chunk)
                return buffer.getvalue()
        except httpx.HTTPError as exc:
            raise MediaProcessingError(f"Unable to download media source: {exc}") from exc

    if settings.storage_backend == "s3" and parsed.scheme == "":
        try:
            return read_private_bytes(value)
        except (OSError, StorageError) as exc:
            raise MediaProcessingError("Unable to read private object") from exc
    raise MediaProcessingError(f"Unsupported media source: {value}")


def _publish(data: bytes, filename: str, content_type: str, namespace: str) -> str:
    settings = get_settings()
    if settings.storage_backend == "s3":
        url, _, _ = save_s3_bytes(data, filename, namespace, content_type)
    else:
        url, _, _ = save_local_bytes(data, filename, namespace, content_type)
    return url


def _validate_model(data: bytes, suffix: str) -> dict[str, Any]:
    normalized = suffix.lower()
    if normalized == ".glb":
        if len(data) < 12 or data[:4] != b"glTF":
            raise MediaProcessingError("Invalid GLB header")
        version = int.from_bytes(data[4:8], "little")
        declared_length = int.from_bytes(data[8:12], "little")
        if version != 2 or declared_length != len(data):
            raise MediaProcessingError("Invalid GLB version or declared length")
        return {"format": "glb", "version": version}
    if normalized == ".gltf":
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MediaProcessingError("Invalid glTF JSON") from exc
        version = str((payload.get("asset") or {}).get("version") or "")
        if not version.startswith("2"):
            raise MediaProcessingError("Only glTF 2.x is supported")
        return {"format": "gltf", "version": version}
    if normalized == ".ply":
        if not data.startswith(b"ply\n") and not data.startswith(b"ply\r\n"):
            raise MediaProcessingError("Invalid PLY header")
        return {"format": "ply"}
    raise MediaProcessingError(f"Unsupported 3D model format: {normalized or 'unknown'}")


def optimize_3d_model(payload: dict[str, Any]) -> dict[str, Any]:
    source_url = str(payload.get("url") or "")
    if not source_url:
        raise MediaProcessingError("process_3d_model requires url")
    filename = str(payload.get("filename") or Path(urlparse(source_url).path).name or "model.glb")
    suffix = Path(filename).suffix.lower()
    data = _read_source(source_url)
    validation = _validate_model(data, suffix)
    output = data
    optimized = False
    optimizer = shutil.which("gltf-transform")
    if optimizer and suffix in {".glb", ".gltf"}:
        with tempfile.TemporaryDirectory(prefix="nestora-model-") as work:
            source = Path(work) / f"source{suffix}"
            target = Path(work) / "optimized.glb"
            source.write_bytes(data)
            completed = subprocess.run(
                [optimizer, "optimize", str(source), str(target), "--compress", "draco"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=get_settings().reconstruction_command_timeout_seconds,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                raise MediaProcessingError(
                    f"gltf-transform failed ({completed.returncode}): {completed.stdout[-1500:]}"
                )
            output = target.read_bytes()
            _validate_model(output, ".glb")
            suffix = ".glb"
            optimized = True
    content_type = "model/gltf-binary" if suffix == ".glb" else mimetypes.guess_type(filename)[0] or "application/octet-stream"
    output_name = f"{Path(filename).stem}-optimized{suffix}"
    url = _publish(output, output_name, content_type, "generated/models")
    return {
        "optimized_url": url,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "source_size": len(data),
        "output_size": len(output),
        "optimized": optimized,
        "validation": validation,
        "compression": "draco" if optimized else "validated-copy",
    }


def generate_thumbnail(payload: dict[str, Any]) -> dict[str, Any]:
    source_url = str(payload.get("url") or "")
    if not source_url:
        raise MediaProcessingError("generate_thumbnail requires url")
    data = _read_source(source_url)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = image.convert("RGB")
            image.thumbnail((960, 540), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (960, 540), "white")
            left = (960 - image.width) // 2
            top = (540 - image.height) // 2
            canvas.paste(image, (left, top))
            output = io.BytesIO()
            canvas.save(output, format="JPEG", quality=86, optimize=True, progressive=True)
            result = output.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaProcessingError("Thumbnail source is not a supported image") from exc
    filename = str(payload.get("filename") or "thumbnail.jpg")
    target_name = f"{Path(filename).stem}-thumb.jpg"
    url = _publish(result, target_name, "image/jpeg", "generated/thumbnails")
    return {
        "status": "ready",
        "thumbnail_url": url,
        "sha256": hashlib.sha256(result).hexdigest(),
        "width": 960,
        "height": 540,
        "size_bytes": len(result),
    }


def index_knowledge_document(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    document_id = str(payload.get("document_id") or payload.get("id") or "")
    if not document_id:
        raise MediaProcessingError("index_knowledge requires document_id")
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise MediaProcessingError("Knowledge document not found")
    chunk_count = index_document(db, document)
    db.commit()
    return {
        "status": "indexed",
        "document_id": document.id,
        "chunk_count": chunk_count,
        "content_sha256": hashlib.sha256(document.content.encode()).hexdigest(),
    }


def validate_panorama_scene(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    scene_id = str(payload.get("scene_id") or "")
    scene = db.get(PanoramaScene, scene_id) if scene_id else None
    if not scene:
        raise MediaProcessingError("Panorama scene not found")
    data = _read_source(scene.image_url)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            fmt = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaProcessingError("Panorama image is unreadable") from exc
    ratio = width / max(height, 1)
    checks = {
        "minimum_width": width >= 2048,
        "equirectangular_ratio": 1.8 <= ratio <= 2.2,
        "non_empty": len(data) > 0,
    }
    passed = all(checks.values())
    scene.metadata_json = {
        **(scene.metadata_json or {}),
        "validation": {
            "passed": passed,
            "checks": checks,
            "width": width,
            "height": height,
            "format": fmt,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    if payload.get("publish") and passed:
        scene.published = True
    db.commit()
    return {"status": "validated" if passed else "rejected", "scene_id": scene.id, **scene.metadata_json["validation"]}


def watermark_grant_document(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    grant_id = str(payload.get("grant_id") or "")
    grant = db.get(DocumentAccessGrant, grant_id) if grant_id else None
    version = db.get(LegalDocumentVersion, grant.version_id) if grant else None
    if not grant or not version:
        raise MediaProcessingError("Document grant not found")
    source = version.storage_key or version.source_url
    if not source:
        raise MediaProcessingError("Document version has no source object")
    data = _read_source(source)
    label = str(
        payload.get("label")
        or f"Nestora · grant {grant.id} · recipient {grant.user_id or grant.agent_id or 'external'}"
    )
    output, applied = watermark_pdf(data, label)
    if not applied:
        raise MediaProcessingError("Document is not a readable PDF")
    storage_key, size, content_type = save_private_bytes(
        output,
        f"grant-{grant.id}.pdf",
        "legal-watermarks",
        "application/pdf",
    )
    return {
        "status": "ready",
        "grant_id": grant.id,
        "storage_key": storage_key,
        "sha256": hashlib.sha256(output).hexdigest(),
        "size_bytes": size,
        "content_type": content_type,
        "watermarked": True,
    }
