from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
class UserRegister(BaseModel):
    email: EmailStr; full_name: str = Field(min_length=2, max_length=160); password: str = Field(min_length=8, max_length=128); phone: str | None = None
class UserLogin(BaseModel):
    email: EmailStr; password: str
class UserRead(ORMModel):
    id: str; email: EmailStr; full_name: str; role: str; phone: str | None; avatar_url: str | None; is_active: bool
class TokenResponse(BaseModel):
    access_token: str; token_type: str = "bearer"; expires_in: int; user: UserRead
class AgencyRead(ORMModel):
    id: str; name: str; slug: str; logo_url: str | None; description: str | None; verified: bool
class AgentRead(ORMModel):
    id: str; display_name: str; phone: str; email: str | None; bio: str | None; license_number: str | None; verified: bool; rating: float; agency: AgencyRead | None = None
class ProjectCreate(BaseModel):
    name: str; slug: str; developer: str | None = None; description: str | None = None; city: str; district: str; address: str; latitude: float | None = None; longitude: float | None = None; status: str = "selling"; cover_url: str | None = None
class ProjectRead(ProjectCreate, ORMModel):
    id: str; created_at: datetime; updated_at: datetime
class FeatureInput(BaseModel):
    name: str; category: str = "amenity"; value: str | None = None
class FeatureRead(FeatureInput, ORMModel): id: str
class MediaInput(BaseModel):
    media_type: Literal["image", "video", "floor_plan", "panorama"] = "image"; url: str; thumbnail_url: str | None = None; alt_text: str | None = None; sort_order: int = 0; metadata_json: dict[str, Any] = Field(default_factory=dict)
class MediaRead(MediaInput, ORMModel): id: str
class FloorInput(BaseModel):
    name: str; sort_order: int = 0; object_names: list[str] = Field(default_factory=list); furniture_object_names: list[str] = Field(default_factory=list); camera: dict[str, Any] = Field(default_factory=dict)
class FloorRead(FloorInput, ORMModel): id: str
class HotspotInput(BaseModel):
    floor_id: str | None = None; label: str; description: str | None = None; position: list[float] = Field(min_length=3, max_length=3); camera_position: list[float] | None = None; room_type: str | None = None; metadata_json: dict[str, Any] = Field(default_factory=dict)
class HotspotRead(HotspotInput, ORMModel): id: str
class Model3DInput(BaseModel):
    model_url: str; poster_url: str | None = None; format: str = "glb"; file_size_bytes: int | None = None; draco_compressed: bool = False; meshopt_compressed: bool = False; ktx2_textures: bool = False; default_camera: dict[str, Any] = Field(default_factory=lambda: {"position": [8,5,8], "target": [0,1,0]}); quality_presets: dict[str, Any] = Field(default_factory=dict); processing_status: str = "ready"; floors: list[FloorInput] = Field(default_factory=list); hotspots: list[HotspotInput] = Field(default_factory=list)
class Model3DRead(Model3DInput, ORMModel):
    id: str; floors: list[FloorRead] = Field(default_factory=list); hotspots: list[HotspotRead] = Field(default_factory=list)
class DocumentInput(BaseModel):
    document_type: str; title: str; url: str; verified: bool = False; valid_from: datetime | None = None; valid_until: datetime | None = None
class DocumentRead(DocumentInput, ORMModel): id: str
class NearbyPlaceRead(ORMModel):
    id: str; name: str; category: str; latitude: float; longitude: float; distance_m: int | None
class PropertyBase(BaseModel):
    slug: str; title: str; transaction_type: Literal["sale","rent"] = "sale"; property_type: str; status: Literal["draft","pending","published","sold","rented","expired","archived"] = "draft"; price: int = Field(ge=0); currency: str = "VND"; area_m2: float = Field(gt=0); bedrooms: int = Field(ge=0, default=0); bathrooms: int = Field(ge=0, default=0); floors_count: int = Field(ge=1, default=1); parking_spaces: int = Field(ge=0, default=0); address: str; ward: str | None = None; district: str; city: str; latitude: float | None = None; longitude: float | None = None; legal_status: str | None = None; furnishing: str | None = None; description: str; year_built: int | None = None; direction: str | None = None; is_featured: bool = False; is_verified: bool = False; is_owner_listing: bool = False; has_3d: bool = False; expires_at: datetime | None = None; agent_id: str | None = None; project_id: str | None = None
class PropertyCreate(PropertyBase):
    features: list[FeatureInput] = Field(default_factory=list); media: list[MediaInput] = Field(default_factory=list); model_3d: Model3DInput | None = None; documents: list[DocumentInput] = Field(default_factory=list)
class PropertyUpdate(BaseModel):
    slug: str | None = None; title: str | None = None; transaction_type: Literal["sale","rent"] | None = None; property_type: str | None = None; status: str | None = None; price: int | None = Field(default=None, ge=0); currency: str | None = None; area_m2: float | None = Field(default=None, gt=0); bedrooms: int | None = Field(default=None, ge=0); bathrooms: int | None = Field(default=None, ge=0); floors_count: int | None = Field(default=None, ge=1); parking_spaces: int | None = Field(default=None, ge=0); address: str | None = None; ward: str | None = None; district: str | None = None; city: str | None = None; latitude: float | None = None; longitude: float | None = None; legal_status: str | None = None; furnishing: str | None = None; description: str | None = None; year_built: int | None = None; direction: str | None = None; is_featured: bool | None = None; is_verified: bool | None = None; is_owner_listing: bool | None = None; has_3d: bool | None = None; expires_at: datetime | None = None; agent_id: str | None = None; project_id: str | None = None; features: list[FeatureInput] | None = None; media: list[MediaInput] | None = None; model_3d: Model3DInput | None = None; documents: list[DocumentInput] | None = None
class PropertySummary(ORMModel):
    id: str; slug: str; title: str; transaction_type: str; property_type: str; status: str; price: int; currency: str; area_m2: float; bedrooms: int; bathrooms: int; address: str; ward: str | None; district: str; city: str; latitude: float | None; longitude: float | None; legal_status: str | None; is_featured: bool; is_verified: bool; has_3d: bool; media: list[MediaRead] = Field(default_factory=list); published_at: datetime | None; updated_at: datetime
    @property
    def cover_url(self) -> str | None: return self.media[0].thumbnail_url or self.media[0].url if self.media else None
class PropertyDetail(PropertySummary):
    floors_count: int; parking_spaces: int; furnishing: str | None; description: str; year_built: int | None; direction: str | None; is_owner_listing: bool; view_count: int; verified_at: datetime | None; expires_at: datetime | None; features: list[FeatureRead] = Field(default_factory=list); model_3d: Model3DRead | None = None; documents: list[DocumentRead] = Field(default_factory=list); agent: AgentRead | None = None; project: ProjectRead | None = None; nearby_places: list[NearbyPlaceRead] = Field(default_factory=list)
class PaginatedProperties(BaseModel):
    items: list[PropertySummary]; total: int; page: int; page_size: int; pages: int; facets: dict[str, Any] = Field(default_factory=dict)
class NaturalSearchRequest(BaseModel): query: str = Field(min_length=2, max_length=500)
class SearchFilters(BaseModel):
    q: str | None = None; transaction_type: str | None = None; property_type: list[str] = Field(default_factory=list); city: str | None = None; district: list[str] = Field(default_factory=list); min_price: int | None = None; max_price: int | None = None; min_area: float | None = None; max_area: float | None = None; bedrooms: int | None = None; bathrooms: int | None = None; legal_status: list[str] = Field(default_factory=list); furnishing: list[str] = Field(default_factory=list); has_3d: bool | None = None; is_owner_listing: bool | None = None; radius_km: float | None = None; latitude: float | None = None; longitude: float | None = None; sort: str = "newest"
class NaturalSearchResponse(BaseModel): filters: SearchFilters; explanation: str
class AppointmentCreate(BaseModel):
    property_id: str; full_name: str = Field(min_length=2,max_length=160); phone: str = Field(min_length=8,max_length=32); email: EmailStr | None = None; scheduled_at: datetime; note: str | None = Field(default=None,max_length=1000); source: str = "web"
    @field_validator("scheduled_at")
    @classmethod
    def future_date(cls,value:datetime)->datetime:
        from datetime import timezone
        now=datetime.now(timezone.utc); comparable=value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if comparable<=now: raise ValueError("scheduled_at must be in the future")
        return value
class AppointmentUpdate(BaseModel): scheduled_at: datetime | None = None; note: str | None = None; status: Literal["pending","confirmed","completed","cancelled","no_show"] | None = None
class AppointmentRead(AppointmentCreate, ORMModel): id: str; user_id: str | None; agent_id: str | None; status: str; created_at: datetime; updated_at: datetime
class LeadCreate(BaseModel): property_id: str | None = None; full_name: str; phone: str; email: EmailStr | None = None; message: str | None = None; source: str = "web"
class LeadUpdate(BaseModel): status: str | None = None; assigned_agent_id: str | None = None
class LeadRead(LeadCreate, ORMModel): id: str; status: str; assigned_agent_id: str | None; created_at: datetime; updated_at: datetime
class MortgageRequest(BaseModel): property_price: int = Field(gt=0); down_payment_percent: float = Field(ge=0,le=100,default=30); annual_interest_percent: float = Field(ge=0,le=100,default=9); term_years: int = Field(gt=0,le=50,default=20); repayment_method: Literal["annuity","declining"] = "annuity"
class MortgageResponse(BaseModel): principal: int; monthly_payment: int; first_month_payment: int | None = None; total_payment: int; total_interest: int; disclaimer: str; schedule_preview: list[dict[str,int]]
class FavoriteRead(BaseModel): property: PropertySummary; created_at: datetime
class SavedSearchCreate(BaseModel): name: str; filters_json: dict[str,Any]; notify: bool = True
class SavedSearchRead(SavedSearchCreate, ORMModel): id: str; created_at: datetime; updated_at: datetime
class CompareRequest(BaseModel): property_ids: list[str] = Field(min_length=2,max_length=4)
class CompareResponse(BaseModel): properties: list[PropertyDetail]; highlights: list[str]
class ChatContext(BaseModel): current_property_id: str | None = None; current_floor_id: str | None = None; selected_hotspot_id: str | None = None; filters: dict[str,Any] = Field(default_factory=dict)
class ChatRequest(BaseModel): session_id: str | None = None; message: str = Field(min_length=1,max_length=4000); context: ChatContext = Field(default_factory=ChatContext)
class ToolResult(BaseModel): tool: str; data: Any
class Citation(BaseModel): label: str; source_url: str | None = None; document_id: str | None = None; property_id: str | None = None
class ChatResponse(BaseModel): session_id: str; message: str; tool_results: list[ToolResult] = Field(default_factory=list); citations: list[Citation] = Field(default_factory=list); suggested_questions: list[str] = Field(default_factory=list); requires_confirmation: bool = False; disclaimer: str | None = None
class KnowledgeDocumentCreate(BaseModel): property_id: str | None = None; project_id: str | None = None; document_type: str; title: str; source_url: str | None = None; content: str; verified: bool = False; valid_from: datetime | None = None; valid_until: datetime | None = None
class KnowledgeDocumentRead(KnowledgeDocumentCreate, ORMModel): id: str; created_at: datetime; updated_at: datetime
class UploadResponse(BaseModel): url: str; filename: str; content_type: str; size: int; job_id: str | None = None
class DashboardMetrics(BaseModel): properties_total: int; properties_published: int; appointments_pending: int; leads_new: int; chat_sessions_active: int; views_total: int
class AuditLogRead(ORMModel): id: str; actor_user_id: str | None; action: str; entity_type: str; entity_id: str | None; before_json: dict[str,Any] | None; after_json: dict[str,Any] | None; ip_address: str | None; created_at: datetime
