from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceRead(ORMModel):
    email_enabled: bool
    zalo_enabled: bool
    in_app_enabled: bool
    categories_json: dict[str, bool]
    timezone: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None


class NotificationPreferenceUpdate(BaseModel):
    email_enabled: bool | None = None
    zalo_enabled: bool | None = None
    in_app_enabled: bool | None = None
    categories_json: dict[str, bool] | None = None
    timezone: str | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None


class NotificationRead(BaseModel):
    id: str
    event_type: str
    channel: str
    subject: str | None
    body: str
    status: str
    read_at: datetime | None
    created_at: datetime


class NotificationWebhook(BaseModel):
    provider_message_id: str
    status: Literal["sent", "delivered", "failed"]
    error: str | None = None


class SavedSearchSubscriptionUpdate(BaseModel):
    frequency: Literal["immediate", "daily", "weekly", "off"] = "daily"
    is_active: bool = True
    notify_price_drop: bool = True


class SavedSearchSubscriptionRead(SavedSearchSubscriptionUpdate, ORMModel):
    id: str
    saved_search_id: str
    last_checked_at: datetime | None
    last_notified_at: datetime | None


class SavedSearchMatchRead(BaseModel):
    id: str
    saved_search_id: str
    property_id: str
    match_score: int
    current_price: int | None
    matched_at: datetime
    notified_at: datetime | None
    property: dict[str, Any] | None = None


class AvailabilityRuleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)
    slot_minutes: int = Field(default=60, ge=15, le=240)
    buffer_minutes: int = Field(default=15, ge=0, le=120)
    timezone: str = "Asia/Ho_Chi_Minh"
    active: bool = True

    @field_validator("end_minute")
    @classmethod
    def valid_end(cls, value: int, info):
        start = info.data.get("start_minute")
        if start is not None and value <= start:
            raise ValueError("end_minute must be after start_minute")
        return value


class AvailabilityRuleRead(AvailabilityRuleCreate, ORMModel):
    id: str
    agent_id: str


class AvailabilityExceptionCreate(BaseModel):
    start_at: datetime
    end_at: datetime
    available: bool = False
    reason: str | None = None


class AvailabilityExceptionRead(AvailabilityExceptionCreate, ORMModel):
    id: str
    agent_id: str


class SlotRead(BaseModel):
    id: str | None = None
    agent_id: str
    start_at: datetime
    end_at: datetime
    available: bool
    status: str = "available"


class SlotBookingCreate(BaseModel):
    property_id: str
    agent_id: str
    start_at: datetime
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=8, max_length=32)
    email: EmailStr | None = None
    note: str | None = Field(default=None, max_length=1000)


class AppointmentStatusUpdate(BaseModel):
    status: Literal[
        "pending", "confirmed", "rejected", "cancelled_by_buyer",
        "cancelled_by_agent", "completed", "no_show"
    ]
    reason: str | None = None


class AppointmentReschedule(BaseModel):
    start_at: datetime
    reason: str | None = Field(default=None, max_length=500)


class ReviewCreate(BaseModel):
    appointment_id: str
    rating: int = Field(ge=1, le=5)
    communication_rating: int = Field(ge=1, le=5)
    knowledge_rating: int = Field(ge=1, le=5)
    responsiveness_rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=3000)


class ReviewUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    communication_rating: int | None = Field(default=None, ge=1, le=5)
    knowledge_rating: int | None = Field(default=None, ge=1, le=5)
    responsiveness_rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=3000)


class ReviewResponseCreate(BaseModel):
    content: str = Field(min_length=2, max_length=3000)


class ReviewReportCreate(BaseModel):
    reason: str = Field(min_length=2, max_length=120)
    details: str | None = Field(default=None, max_length=2000)


class ReviewRead(ORMModel):
    id: str
    agent_id: str
    user_id: str
    appointment_id: str
    rating: int
    communication_rating: int
    knowledge_rating: int
    responsiveness_rating: int
    comment: str | None
    verified: bool
    status: str
    created_at: datetime
    updated_at: datetime
    response: dict[str, Any] | None = None


class ThreadCreate(BaseModel):
    property_id: str | None = None
    agent_id: str | None = None
    subject: str | None = Field(default=None, max_length=300)
    ai_session_id: str | None = None
    share_ai_transcript: bool = False


class MessageCreate(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=120)
    content: str = Field(min_length=1, max_length=10000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class MessageRead(BaseModel):
    id: str
    thread_id: str
    sender_user_id: str
    client_message_id: str
    content: str
    metadata_json: dict[str, Any]
    created_at: datetime
    edited_at: datetime | None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ThreadRead(BaseModel):
    id: str
    property_id: str | None
    created_by_user_id: str
    assigned_agent_id: str | None
    subject: str | None
    status: str
    last_message_at: datetime | None
    unread_count: int = 0
    participants: list[dict[str, Any]] = Field(default_factory=list)
    last_message: MessageRead | None = None


class CRMConnectionCreate(BaseModel):
    agency_id: str | None = None
    provider: str = "webhook"
    base_url: str | None = None
    api_key: str | None = None
    webhook_secret: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class CRMConnectionRead(ORMModel):
    id: str
    agency_id: str | None
    provider: str
    base_url: str | None
    config_json: dict[str, Any]
    active: bool
    created_at: datetime
    updated_at: datetime


class RoutingRuleCreate(BaseModel):
    agency_id: str | None = None
    name: str
    priority: int = 100
    conditions_json: dict[str, Any] = Field(default_factory=dict)
    strategy: Literal["owner", "round_robin", "least_loaded", "priority"] = "round_robin"
    target_agent_id: str | None = None
    active: bool = True


class RoutingRuleRead(RoutingRuleCreate, ORMModel):
    id: str


class CRMSyncRead(ORMModel):
    id: str
    connection_id: str
    entity_type: str
    local_id: str
    action: str
    status: str
    attempts: int
    payload_json: dict[str, Any]
    response_json: dict[str, Any] | None
    error: str | None
    synced_at: datetime | None


class PanoramaSceneCreate(BaseModel):
    property_id: str
    floor_id: str | None = None
    name: str
    image_url: str
    thumbnail_url: str | None = None
    initial_yaw: float = 0
    initial_pitch: float = 0
    initial_fov: float = 75
    sort_order: int = 0
    published: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PanoramaLinkCreate(BaseModel):
    source_scene_id: str
    target_scene_id: str
    yaw: float
    pitch: float
    label: str | None = None


class PanoramaHotspotCreate(BaseModel):
    scene_id: str
    yaw: float
    pitch: float
    label: str
    description: str | None = None
    hotspot_type: str = "info"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class NavigationZoneCreate(BaseModel):
    property_id: str
    floor_id: str | None = None
    name: str
    zone_type: str = "walkable"
    points_json: list[list[float]]
    min_y: float = 0
    max_y: float = 6
    active: bool = True


class PanoramaGraph(BaseModel):
    scenes: list[dict[str, Any]]
    links: list[dict[str, Any]]
    hotspots: list[dict[str, Any]]
    navigation_zones: list[dict[str, Any]]


class BrochureRequest(BaseModel):
    template_version: str = "v1"
    force: bool = False


class BrochureRead(BaseModel):
    id: str
    property_id: str
    storage_url: str
    checksum: str
    template_version: str
    status: str
    generated_at: datetime


class LegalVersionCreate(BaseModel):
    property_document_id: str
    storage_key: str
    source_url: str | None = None
    checksum_sha256: str
    content_type: str = "application/pdf"
    size_bytes: int = Field(gt=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class LegalReviewCreate(BaseModel):
    decision: Literal["approved", "rejected", "needs_changes"]
    notes: str | None = Field(default=None, max_length=3000)


class LegalGrantCreate(BaseModel):
    version_id: str
    user_id: str | None = None
    agent_id: str | None = None
    expires_minutes: int = Field(default=15, ge=1, le=1440)
    max_downloads: int = Field(default=1, ge=1, le=20)


class LegalVersionRead(ORMModel):
    id: str
    property_document_id: str
    version_number: int
    storage_key: str
    source_url: str | None
    checksum_sha256: str
    content_type: str
    size_bytes: int
    status: str
    active: bool
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime


class AnalyticsEventCreate(BaseModel):
    anonymous_id: str = Field(min_length=8, max_length=128)
    session_id: str | None = None
    event_name: str = Field(min_length=2, max_length=120)
    event_version: int = 1
    property_id: str | None = None
    agent_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, max_length=220)
    consent: Literal["essential", "analytics"] = "essential"
    device_class: str | None = None
    occurred_at: datetime | None = None


class AnalyticsDashboard(BaseModel):
    start_date: date
    end_date: date
    funnel: dict[str, int]
    property_metrics: list[dict[str, Any]]
    agent_metrics: list[dict[str, Any]]
    ai_quality: dict[str, Any]
    notification_health: dict[str, int]
    crm_health: dict[str, int]


class AIQualityCreate(BaseModel):
    chat_session_id: str | None = None
    answer_helpful: int | None = Field(default=None, ge=0, le=1)
    citation_coverage: float = Field(default=0, ge=0, le=1)
    handoff_required: bool = False
    unanswered: bool = False
    notes: str | None = Field(default=None, max_length=1000)

class CalendarConnectionCreate(BaseModel):
    provider: Literal["ics", "google", "outlook"] = "ics"
    account_email: EmailStr | None = None
    external_calendar_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


class CalendarConnectionRead(ORMModel):
    id: str
    agent_id: str
    provider: str
    account_email: str | None
    external_calendar_id: str | None
    config_json: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
