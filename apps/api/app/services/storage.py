from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import BinaryIO

from ..config import get_settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/avif", "model/gltf-binary", "model/gltf+json", "application/octet-stream", "application/pdf", "video/mp4"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class StorageError(ValueError):
    pass


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-.")
    return stem[:180] or "upload.bin"


def validate_upload(filename: str, content_type: str | None, size: int) -> str:
    guessed = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if guessed not in ALLOWED_TYPES:
        raise StorageError(f"Unsupported content type: {guessed}")
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise StorageError("File must be between 1 byte and 50 MB")
    return guessed


def read_limited(file: BinaryIO) -> bytes:
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise StorageError("Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StorageError("File exceeds 50 MB")
    return data


def save_local_bytes(data: bytes, filename: str, namespace: str, content_type: str) -> tuple[str, int, str]:
    settings = get_settings(); root = settings.storage_path / namespace; root.mkdir(parents=True, exist_ok=True)
    clean = safe_filename(filename); target = root / clean; counter = 1
    while target.exists():
        target = root / f"{Path(clean).stem}-{counter}{Path(clean).suffix}"; counter += 1
    target.write_bytes(data)
    return f"{settings.public_base_url.rstrip('/')}/storage/{namespace}/{target.name}", len(data), content_type


def save_s3_bytes(data: bytes, filename: str, namespace: str, content_type: str) -> tuple[str, int, str]:
    try:
        import boto3
    except ImportError as exc:
        raise StorageError("boto3 is required for S3 storage") from exc
    settings = get_settings()
    client = boto3.client("s3", endpoint_url=settings.s3_endpoint, aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key, region_name="us-east-1")
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        client.create_bucket(Bucket=settings.s3_bucket)
    digest = hashlib.sha256(data).hexdigest()[:12]; key = f"{namespace}/{digest}-{safe_filename(filename)}"
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return f"{settings.s3_public_url.rstrip('/')}/{settings.s3_bucket}/{key}", len(data), content_type


def save_upload(file: BinaryIO, filename: str, content_type: str | None, namespace: str = "uploads") -> tuple[str, int, str]:
    data = read_limited(file); guessed = validate_upload(filename, content_type, len(data)); settings = get_settings()
    return save_s3_bytes(data, filename, namespace, guessed) if settings.storage_backend == "s3" else save_local_bytes(data, filename, namespace, guessed)


def delete_local(url: str) -> bool:
    settings = get_settings(); marker = "/storage/"
    if marker not in url:
        return False
    relative = url.split(marker, 1)[1]; target = (settings.storage_path / relative).resolve()
    if settings.storage_path not in target.parents:
        return False
    if target.exists():
        target.unlink(); return True
    return False
