from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from .config import get_settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _encode_token(payload: dict[str, Any]) -> str:
    settings = get_settings()
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}.{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(settings.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def hash_password(password: str, iterations: int = 310_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64decode(salt), int(iterations))
        return secrets.compare_digest(_b64url(digest), expected)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + 60 * (expires_minutes or settings.access_token_minutes),
        "jti": secrets.token_urlsafe(12),
    }
    return _encode_token(payload)


def create_scoped_token(scope: str, claims: dict[str, Any], expires_minutes: int) -> str:
    if expires_minutes <= 0:
        raise ValueError("expires_minutes must be positive")
    now = int(time.time())
    payload: dict[str, Any] = {
        **claims,
        "scope": scope,
        "iat": now,
        "exp": now + 60 * expires_minutes,
        "jti": claims.get("jti") or secrets.token_urlsafe(16),
    }
    return _encode_token(payload)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(settings.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not secrets.compare_digest(_b64url(expected), signature_b64):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        return payload
    except Exception as exc:
        raise ValueError("invalid token") from exc


def decode_scoped_token(token: str, expected_scope: str) -> dict[str, Any]:
    payload = decode_access_token(token)
    if payload.get("scope") != expected_scope:
        raise ValueError("invalid token scope")
    return payload
