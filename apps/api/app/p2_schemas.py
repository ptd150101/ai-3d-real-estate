from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    slug: str = Field(pattern=r"^[a-z0-9-]+$", max_length=240)


class OrganizationInviteCreate(BaseModel):
    email: EmailStr
    role: Literal["owner", "manager", "agent", "reviewer", "finance", "analyst"] = "agent"


class OrganizationInvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class OrganizationMemberUpdate(BaseModel):
    role: Literal["owner", "manager", "agent", "reviewer", "finance", "analyst"] | None = None
    status: Literal["active", "suspended"] | None = None


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    config_json: dict[str, Any] = Field(default_factory=dict)


class ReservationCreate(BaseModel):
    property_id: str
    amount: int = Field(gt=0)
    provider: Literal["local", "vnpay", "stripe"] = "local"
    idempotency_key: str = Field(min_length=8, max_length=128)


class PaymentWebhookPayload(BaseModel):
    event_id: str
    intent_id: str | None = None
    provider_intent_id: str | None = None
    status: str = "paid"
    amount: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefundCreate(BaseModel):
    amount: int = Field(gt=0)
    reason: str = Field(min_length=2, max_length=500)


class LegalPolicyCreate(BaseModel):
    document_type: str = Field(min_length=2, max_length=120)
    jurisdiction: str = "VN"
    approved: bool = True
    notes: str | None = None


class ContractTemplateCreate(BaseModel):
    name: str
    document_type: str
    content_html: str
    allowed_fields: list[str] = Field(default_factory=list)
    version: int = 1


class ContractEnvelopeCreate(BaseModel):
    template_id: str
    reservation_order_id: str | None = None
    provider: Literal["local", "external", "docusign"] = "local"
    data: dict[str, Any] = Field(default_factory=dict)
    participants: list[dict[str, Any]] = Field(min_length=1)


class ContractSignCreate(BaseModel):
    participant_id: str
    signing_token: str | None = Field(default=None, min_length=32)
    provider_event_id: str | None = None
    consent: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValuationCreate(BaseModel):
    property_id: str | None = None
    district: str | None = None
    property_type: str | None = None
    area_m2: float | None = Field(default=None, gt=0)
    bedrooms: int | None = Field(default=None, ge=0)
    legal_status: str | None = None


class ValuationOverrideCreate(BaseModel):
    value: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class RecommendationFeedbackCreate(BaseModel):
    property_id: str
    action: Literal["click", "save", "hide", "appointment", "not_relevant"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationProfileUpdate(BaseModel):
    enabled: bool | None = None
    reset: bool = False


class ValuationModelCreate(BaseModel):
    name: str = "nestora-avm"
    version: str
    feature_version: str = "p2-v1"
    metrics: dict[str, float]
    baseline_metrics: dict[str, float]


class ModelEvaluationCreate(BaseModel):
    split_type: str = "time_holdout"
    segment: str = "all"
    metrics: dict[str, float]
    passed: bool


class DriftCreate(BaseModel):
    segment: str = "all"
    value: float
    threshold: float


class CaptureSessionCreate(BaseModel):
    property_id: str
    capture_type: Literal["images", "video"] = "images"
    requirements: dict[str, Any] = Field(default_factory=dict)


class CaptureFileCreate(BaseModel):
    url: str
    sha256: str = Field(min_length=16, max_length=128)
    mime_type: str
    size_bytes: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReconstructionStartCreate(BaseModel):
    representation: Literal["mesh", "gaussian_splat", "glb"] = "mesh"


class AssetReviewCreate(BaseModel):
    status: Literal["approved", "rejected"]
    notes: str | None = None


class ARSessionCreate(BaseModel):
    device: dict[str, Any] = Field(default_factory=dict)


class VRSessionCreate(BaseModel):
    device_profile: str = "browser"
    performance: dict[str, Any] = Field(default_factory=dict)


class MLArtifactCreate(BaseModel):
    kind: str
    uri: str
    sha256: str = Field(min_length=32, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MLModelCreate(BaseModel):
    name: str
    task: str
    version: str
    artifact_id: str | None = None
    feature_version: str = "v1"
    metrics: dict[str, Any] = Field(default_factory=dict)


class MLEvaluationCreate(BaseModel):
    dataset_version: str
    metrics: dict[str, Any]
    passed: bool
    gate: dict[str, Any] = Field(default_factory=dict)


class MLPromoteCreate(BaseModel):
    environment: str = "production"
    traffic_percent: int = Field(default=100, ge=0, le=100)


class MobileLoginCreate(BaseModel):
    email: EmailStr
    password: str
    device_id: str = Field(min_length=4, max_length=180)


class MobileRefreshCreate(BaseModel):
    refresh_token: str
    device_id: str


class MobileLogoutCreate(BaseModel):
    refresh_token: str | None = None
    device_id: str


class MobileDeviceCreate(BaseModel):
    device_id: str
    platform: Literal["ios", "android", "web"]
    push_token: str | None = Field(default=None, max_length=512)
    app_version: str | None = Field(default=None, max_length=80)


class MobileMutationCreate(BaseModel):
    device_id: str
    client_mutation_id: str = Field(min_length=6, max_length=180)
    mutation_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MobilePushCreate(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)
