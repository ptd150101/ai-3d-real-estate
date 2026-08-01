from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Nestora API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 60 * 24
    database_url: str = "sqlite:///./nestora.db"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:3000"
    storage_backend: str = "local"
    storage_root: str = "./storage"
    public_base_url: str = "http://localhost:8000"
    site_url: str = "http://localhost:3000"
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "local-access-key"
    s3_secret_key: str = "local-secret-key-change-me"
    s3_bucket: str = "nestora"
    s3_private_bucket: str = "nestora-private"
    s3_public_url: str = "http://localhost:9000"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    enable_llm: bool = False
    enable_ar: bool = False
    rate_limit_per_minute: int = 60
    log_level: str = "INFO"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Nestora <no-reply@localhost>"
    smtp_starttls: bool = True
    zalo_endpoint: str | None = None
    zalo_token: str | None = None
    notification_webhook_secret: str = ""
    document_signing_ttl_minutes: int = 15
    analytics_retention_days: int = 365
    worker_poll_seconds: int = 2
    payment_webhook_secret: str = ""
    vnpay_webhook_secret: str = ""
    stripe_webhook_secret: str = ""
    signature_webhook_secret: str = ""
    mobile_refresh_days: int = 30
    gpu_worker_capabilities: str = "mesh,gaussian_splat,glb"
    gpu_hourly_cost: float = 0.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()


@lru_cache
def get_settings() -> Settings:
    import os
    values: dict[str, object] = {}
    for field in Settings.model_fields:
        env_key = field.upper()
        if env_key not in os.environ:
            continue
        raw = os.environ[env_key]
        annotation = Settings.model_fields[field].annotation
        if annotation is bool or "bool" in str(annotation): values[field] = raw.lower() in {"1", "true", "yes", "on"}
        elif annotation is int: values[field] = int(raw)
        elif annotation is float: values[field] = float(raw)
        else: values[field] = raw
    return Settings(**values)
