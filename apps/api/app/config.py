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

    # Provider policy. Fixture providers are never permitted in production.
    allow_fixture_providers: bool = True
    provider_http_timeout_seconds: int = 20
    payment_webhook_secret: str = ""

    stripe_api_base: str = "https://api.stripe.com"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_webhook_tolerance_seconds: int = 300

    vnpay_tmn_code: str = ""
    vnpay_hash_secret: str = ""
    vnpay_webhook_secret: str = ""  # backwards-compatible alias
    vnpay_payment_url: str = "https://sandbox.vnpayment.vn/paymentv2/vpcpay.html"
    vnpay_api_url: str = "https://sandbox.vnpayment.vn/merchant_webapi/api/transaction"
    vnpay_return_url: str = ""

    signature_provider: str = "local"
    signature_webhook_secret: str = ""
    docusign_base_url: str = "https://demo.docusign.net/restapi"
    docusign_account_id: str = ""
    docusign_access_token: str = ""
    docusign_webhook_hmac_secret: str = ""
    docusign_return_url: str = ""

    mobile_refresh_days: int = 30
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_access_token: str = ""

    gpu_worker_capabilities: str = "mesh,gaussian_splat,glb"
    gpu_hourly_cost: float = 0.0
    reconstruction_backend: str = "fixture"  # fixture | colmap | nerfstudio
    reconstruction_command_timeout_seconds: int = 7200
    reconstruction_work_root: str = "./storage/reconstruction-work"
    colmap_binary: str = "colmap"
    nerfstudio_process_binary: str = "ns-process-data"
    nerfstudio_train_binary: str = "ns-train"
    nerfstudio_export_binary: str = "ns-export"
    gltf_converter_binary: str = ""
    usdz_converter_binary: str = ""

    ml_inference_timeout_seconds: int = 15
    ml_require_live_endpoint_in_production: bool = True
    ml_max_error_rate: float = 0.05

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root).resolve()

    @property
    def reconstruction_work_path(self) -> Path:
        return Path(self.reconstruction_work_root).resolve()

    @property
    def fixtures_allowed(self) -> bool:
        return self.environment.lower() not in {"production", "prod"} and self.allow_fixture_providers

    def validate_production(self) -> None:
        if self.environment.lower() not in {"production", "prod"}:
            return
        errors: list[str] = []
        if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
            errors.append("SECRET_KEY must be at least 32 characters")
        if self.allow_fixture_providers:
            errors.append("ALLOW_FIXTURE_PROVIDERS must be false")
        if self.reconstruction_backend == "fixture":
            errors.append("RECONSTRUCTION_BACKEND cannot be fixture")
        if self.reconstruction_backend not in {"colmap", "nerfstudio"}:
            errors.append("RECONSTRUCTION_BACKEND must be colmap or nerfstudio")
        if self.signature_provider == "local":
            errors.append("SIGNATURE_PROVIDER cannot be local")
        if self.signature_provider in {"external", "docusign"}:
            if not self.docusign_account_id or not self.docusign_access_token:
                errors.append("DocuSign account id and access token are required")
            if not self.docusign_webhook_hmac_secret:
                errors.append("DOCUSIGN_WEBHOOK_HMAC_SECRET is required")
        if self.storage_backend == "s3" and (not self.s3_access_key or not self.s3_secret_key):
            errors.append("S3 credentials are required")
        if not self.site_url.lower().startswith("https://"):
            errors.append("SITE_URL must use HTTPS")
        if errors:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


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
        if annotation is bool or "bool" in str(annotation):
            values[field] = raw.lower() in {"1", "true", "yes", "on"}
        elif annotation is int:
            values[field] = int(raw)
        elif annotation is float:
            values[field] = float(raw)
        else:
            values[field] = raw
    return Settings(**values)
