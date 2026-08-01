from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(220))
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OrganizationMember(Base, TimestampMixin):
    __tablename__ = "organization_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(48), default="agent", index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_member"),)


class OrganizationInvitation(Base, TimestampMixin):
    __tablename__ = "organization_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(48), default="agent")
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationRole(Base, TimestampMixin):
    __tablename__ = "organization_roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    permissions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_org_role"),)


class OrganizationFeatureFlag(Base, TimestampMixin):
    __tablename__ = "organization_feature_flags"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_org_flag"),)


class MarketplacePlan(Base, TimestampMixin):
    __tablename__ = "marketplace_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    monthly_price: Mapped[int] = mapped_column(BigInteger, default=0)
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrganizationSubscription(Base, TimestampMixin):
    __tablename__ = "organization_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), unique=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("marketplace_plans.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(32), default="active")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListingQuota(Base, TimestampMixin):
    __tablename__ = "listing_quotas"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80), default="published_listings")
    limit_value: Mapped[int] = mapped_column(Integer, default=50)
    used_value: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_org_quota"),)


class AgencyVerificationCase(Base, TimestampMixin):
    __tablename__ = "agency_verification_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    documents_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)


class TenantAuditExport(Base, TimestampMixin):
    __tablename__ = "tenant_audit_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    object_url: Mapped[str | None] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(128))


class PaymentProviderAccount(Base, TimestampMixin):
    __tablename__ = "payment_provider_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    config_encrypted: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("organization_id", "provider", name="uq_org_payment_provider"),)


class ReservationOrder(Base, TimestampMixin):
    __tablename__ = "reservation_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), index=True)
    buyer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="awaiting_payment", index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaymentIntent(Base, TimestampMixin):
    __tablename__ = "payment_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("reservation_orders.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    provider_intent_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    checkout_url: Mapped[str | None] = mapped_column(String(2048))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    provider_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaymentTransaction(Base, TimestampMixin):
    __tablename__ = "payment_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    intent_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id", ondelete="CASCADE"), index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    provider_event_id: Mapped[str | None] = mapped_column(String(180), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(48), index=True)
    event_id: Mapped[str] = mapped_column(String(180))
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="received")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_webhook"),)


class RefundRequest(Base, TimestampMixin):
    __tablename__ = "refund_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("reservation_orders.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PaymentDispute(Base, TimestampMixin):
    __tablename__ = "payment_disputes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("reservation_orders.id", ondelete="CASCADE"), index=True)
    provider_dispute_id: Mapped[str | None] = mapped_column(String(180), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(500))


class LedgerAccount(Base, TimestampMixin):
    __tablename__ = "ledger_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    account_type: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_ledger_account"),)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("payment_transactions.id", ondelete="RESTRICT"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    reference_type: Mapped[str] = mapped_column(String(64))
    reference_id: Mapped[str] = mapped_column(String(64), index=True)
    immutable_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SettlementBatch(Base, TimestampMixin):
    __tablename__ = "settlement_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    gross_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    fee_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    net_amount: Mapped[int] = mapped_column(BigInteger, default=0)


class ReconciliationRun(Base, TimestampMixin):
    __tablename__ = "reconciliation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    mismatch_count: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LegalDocumentPolicy(Base, TimestampMixin):
    __tablename__ = "legal_document_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_type: Mapped[str] = mapped_column(String(120), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(80), default="VN")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("document_type", "jurisdiction", name="uq_legal_policy"),)


class ContractTemplate(Base, TimestampMixin):
    __tablename__ = "contract_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(220))
    document_type: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_html: Mapped[str] = mapped_column(Text)
    allowed_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("organization_id", "name", "version", name="uq_contract_template_version"),)


class ContractEnvelope(Base, TimestampMixin):
    __tablename__ = "contract_envelopes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("contract_templates.id", ondelete="RESTRICT"))
    reservation_order_id: Mapped[str | None] = mapped_column(ForeignKey("reservation_orders.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    provider: Mapped[str] = mapped_column(String(48), default="local")
    document_url: Mapped[str | None] = mapped_column(String(1024))
    document_checksum: Mapped[str | None] = mapped_column(String(128))
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContractParticipant(Base, TimestampMixin):
    __tablename__ = "contract_participants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    envelope_id: Mapped[str] = mapped_column(ForeignKey("contract_envelopes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(80))
    signing_order: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignatureEvent(Base):
    __tablename__ = "signature_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    envelope_id: Mapped[str] = mapped_column(ForeignKey("contract_envelopes.id", ondelete="CASCADE"), index=True)
    participant_id: Mapped[str | None] = mapped_column(ForeignKey("contract_participants.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(180), unique=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SignatureEvidence(Base, TimestampMixin):
    __tablename__ = "signature_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    envelope_id: Mapped[str] = mapped_column(ForeignKey("contract_envelopes.id", ondelete="CASCADE"), unique=True)
    checksum: Mapped[str] = mapped_column(String(128), unique=True)
    object_url: Mapped[str | None] = mapped_column(String(1024))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ValuationModelVersion(Base, TimestampMixin):
    __tablename__ = "valuation_model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    feature_version: Mapped[str] = mapped_column(String(80), default="v1")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    baseline_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("organization_id", "name", "version", name="uq_valuation_model_version"),)


class ValuationEvaluation(Base, TimestampMixin):
    __tablename__ = "valuation_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("valuation_model_versions.id", ondelete="CASCADE"), index=True)
    split_type: Mapped[str] = mapped_column(String(48), default="time_holdout")
    segment: Mapped[str] = mapped_column(String(160), default="all")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)


class ValuationRequest(Base, TimestampMixin):
    __tablename__ = "valuation_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="completed")


class ValuationResult(Base, TimestampMixin):
    __tablename__ = "valuation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("valuation_requests.id", ondelete="CASCADE"), unique=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("valuation_model_versions.id", ondelete="SET NULL"))
    estimate: Mapped[int | None] = mapped_column(BigInteger)
    lower_bound: Mapped[int | None] = mapped_column(BigInteger)
    upper_bound: Mapped[int | None] = mapped_column(BigInteger)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(48), default="completed")
    feature_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    override_value: Mapped[int | None] = mapped_column(BigInteger)
    override_reason: Mapped[str | None] = mapped_column(Text)


class ValuationComparable(Base):
    __tablename__ = "valuation_comparables"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    result_id: Mapped[str] = mapped_column(ForeignKey("valuation_results.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"))
    similarity: Mapped[float] = mapped_column(Float)
    adjustments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("result_id", "property_id", name="uq_valuation_comparable"),)


class ValuationDriftMetric(Base, TimestampMixin):
    __tablename__ = "valuation_drift_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("valuation_model_versions.id", ondelete="CASCADE"), index=True)
    segment: Mapped[str] = mapped_column(String(160), default="all")
    metric: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="healthy")


class RecommendationProfile(Base, TimestampMixin):
    __tablename__ = "recommendation_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationExperiment(Base, TimestampMixin):
    __tablename__ = "recommendation_experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    variants_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RecommendationAssignment(Base):
    __tablename__ = "recommendation_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("recommendation_experiments.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    variant: Mapped[str] = mapped_column(String(80))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("experiment_id", "user_id", name="uq_recommendation_assignment"),)


class RecommendationImpression(Base):
    __tablename__ = "recommendation_impressions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(300))
    experiment_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GPUWorkerPool(Base, TimestampMixin):
    __tablename__ = "gpu_worker_pools"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    hourly_cost: Mapped[float] = mapped_column(Float, default=0)


class CaptureSession(Base, TimestampMixin):
    __tablename__ = "capture_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="collecting", index=True)
    capture_type: Mapped[str] = mapped_column(String(48), default="images")
    requirements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CaptureFile(Base, TimestampMixin):
    __tablename__ = "capture_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(128))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("session_id", "sha256", name="uq_capture_file_hash"),)


class ReconstructionJob(Base, TimestampMixin):
    __tablename__ = "reconstruction_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id", ondelete="CASCADE"), index=True)
    representation: Mapped[str] = mapped_column(String(48), default="mesh")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(80), default="quality_check")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    worker_pool_id: Mapped[str | None] = mapped_column(ForeignKey("gpu_worker_pools.id", ondelete="SET NULL"))
    cost_amount: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ReconstructionArtifact(Base, TimestampMixin):
    __tablename__ = "reconstruction_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("reconstruction_jobs.id", ondelete="CASCADE"), index=True)
    asset_type: Mapped[str] = mapped_column(String(48))
    url: Mapped[str] = mapped_column(String(1024))
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class GeneratedAssetReview(Base, TimestampMixin):
    __tablename__ = "generated_asset_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("reconstruction_artifacts.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("artifact_id", name="uq_generated_asset_review"),)


class ARAsset(Base, TimestampMixin):
    __tablename__ = "ar_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    source_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("reconstruction_artifacts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    variants_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    placement_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scale_meters: Mapped[float] = mapped_column(Float, default=1)


class ARSession(Base):
    __tablename__ = "ar_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("ar_assets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    device_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VRTourConfig(Base, TimestampMixin):
    __tablename__ = "vr_tour_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), unique=True)
    source_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("reconstruction_artifacts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    navigation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comfort_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fallback_url: Mapped[str | None] = mapped_column(String(1024))


class VRSession(Base):
    __tablename__ = "vr_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tour_id: Mapped[str] = mapped_column(ForeignKey("vr_tour_configs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    device_profile: Mapped[str] = mapped_column(String(160), default="unknown")
    performance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MobileDevice(Base, TimestampMixin):
    __tablename__ = "mobile_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(180))
    platform: Mapped[str] = mapped_column(String(24))
    push_token: Mapped[str | None] = mapped_column(String(512))
    app_version: Mapped[str | None] = mapped_column(String(80))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_mobile_device"),)


class MobileRefreshToken(Base):
    __tablename__ = "mobile_refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(180), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MobileMutation(Base, TimestampMixin):
    __tablename__ = "mobile_mutations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(180))
    client_mutation_id: Mapped[str] = mapped_column(String(180))
    mutation_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="applied")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "device_id", "client_mutation_id", name="uq_mobile_mutation"),)


class MLArtifact(Base, TimestampMixin):
    __tablename__ = "ml_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    uri: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(128), unique=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MLModelVersion(Base, TimestampMixin):
    __tablename__ = "ml_model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    task: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("ml_artifacts.id", ondelete="SET NULL"))
    feature_version: Mapped[str] = mapped_column(String(80), default="v1")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("organization_id", "name", "version", name="uq_ml_model_version"),)


class MLEvaluation(Base, TimestampMixin):
    __tablename__ = "ml_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("ml_model_versions.id", ondelete="CASCADE"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(120))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MLDeployment(Base, TimestampMixin):
    __tablename__ = "ml_deployments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_version_id: Mapped[str] = mapped_column(ForeignKey("ml_model_versions.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(48), default="staging")
    status: Mapped[str] = mapped_column(String(32), default="active")
    traffic_percent: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MLUsageRecord(Base):
    __tablename__ = "ml_usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), index=True)
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    units: Mapped[float] = mapped_column(Float, default=0)
    cost_amount: Mapped[float] = mapped_column(Float, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class FeatureKillSwitch(Base, TimestampMixin):
    __tablename__ = "feature_kill_switches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_feature_kill_switch"),)


Index("ix_ledger_reference", LedgerEntry.organization_id, LedgerEntry.reference_type, LedgerEntry.reference_id)
Index("ix_recommendation_feedback_user_action", RecommendationFeedback.user_id, RecommendationFeedback.action)
