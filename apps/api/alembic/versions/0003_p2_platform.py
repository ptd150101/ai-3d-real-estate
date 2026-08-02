"""P2 marketplace, payments, contracts, intelligence, spatial, mobile and ML operations.

Revision ID: 0003_p2_platform
Revises: 0002_p1_platform

This migration uses a frozen table/column snapshot and Alembic operations. It deliberately
refuses to run if the current ORM metadata no longer matches the historical P2 snapshot,
preventing later model edits from silently changing an old migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.sql.schema import CheckConstraint, UniqueConstraint

from app.database import Base
from app import models  # noqa: F401 -- populate metadata

revision = "0003_p2_platform"
down_revision = "0002_p1_platform"
branch_labels = None
depends_on = None

T = ("created_at", "updated_at")
P2_SCHEMA: dict[str, tuple[str, ...]] = {
    "organizations": ("id", "name", "slug", "status", "verified", "settings_json", *T),
    "organization_members": ("id", "organization_id", "user_id", "role", "status", "invited_by_user_id", *T),
    "organization_invitations": ("id", "organization_id", "email", "role", "token_hash", "status", "expires_at", "accepted_at", *T),
    "organization_roles": ("id", "organization_id", "name", "permissions_json", "system", *T),
    "organization_feature_flags": ("id", "organization_id", "key", "enabled", "config_json", *T),
    "marketplace_plans": ("id", "code", "name", "monthly_price", "entitlements_json", "active", *T),
    "organization_subscriptions": ("id", "organization_id", "plan_id", "status", "current_period_end", *T),
    "listing_quotas": ("id", "organization_id", "key", "limit_value", "used_value", "reset_at", *T),
    "agency_verification_cases": ("id", "organization_id", "status", "documents_json", "reviewer_user_id", "notes", *T),
    "tenant_audit_exports": ("id", "organization_id", "requested_by_user_id", "status", "object_url", "checksum", *T),
    "payment_provider_accounts": ("id", "organization_id", "provider", "status", "config_encrypted", *T),
    "reservation_orders": ("id", "organization_id", "property_id", "buyer_user_id", "status", "amount", "currency", "idempotency_key", "expires_at", "confirmed_at", "metadata_json", *T),
    "payment_intents": ("id", "order_id", "provider", "provider_intent_id", "status", "amount", "checkout_url", "idempotency_key", "provider_payload_json", *T),
    "payment_transactions": ("id", "intent_id", "transaction_type", "status", "amount", "provider_event_id", "occurred_at", "raw_json", *T),
    "payment_webhook_events": ("id", "provider", "event_id", "signature_valid", "status", "payload_json", "received_at"),
    "refund_requests": ("id", "order_id", "amount", "reason", "status", "requested_by_user_id", "approved_by_user_id", *T),
    "payment_disputes": ("id", "order_id", "provider_dispute_id", "status", "amount", "reason", *T),
    "ledger_accounts": ("id", "organization_id", "code", "name", "account_type", "currency", *T),
    "ledger_entries": ("id", "organization_id", "transaction_id", "account_id", "direction", "amount", "currency", "reference_type", "reference_id", "immutable_hash", "created_at"),
    "settlement_batches": ("id", "organization_id", "provider", "status", "gross_amount", "fee_amount", "net_amount", *T),
    "reconciliation_runs": ("id", "organization_id", "provider", "status", "matched_count", "mismatch_count", "report_json", *T),
    "legal_document_policies": ("id", "document_type", "jurisdiction", "approved", "approved_by_user_id", "approved_at", "notes", *T),
    "contract_templates": ("id", "organization_id", "name", "document_type", "version", "content_html", "allowed_fields_json", "active", *T),
    "contract_envelopes": ("id", "organization_id", "template_id", "reservation_order_id", "status", "provider", "document_url", "document_checksum", "data_json", "expires_at", "completed_at", *T),
    "contract_participants": ("id", "envelope_id", "user_id", "email", "role", "signing_order", "status", "signed_at", *T),
    "signature_events": ("id", "envelope_id", "participant_id", "event_type", "provider_event_id", "event_at", "metadata_json"),
    "signature_evidence": ("id", "envelope_id", "checksum", "object_url", "evidence_json", *T),
    "valuation_model_versions": ("id", "organization_id", "name", "version", "status", "feature_version", "metrics_json", "baseline_metrics_json", "trained_at", *T),
    "valuation_evaluations": ("id", "model_version_id", "split_type", "segment", "metrics_json", "passed", *T),
    "valuation_requests": ("id", "organization_id", "user_id", "property_id", "input_json", "status", *T),
    "valuation_results": ("id", "request_id", "model_version_id", "estimate", "lower_bound", "upper_bound", "confidence", "status", "feature_snapshot_json", "explanation_json", "override_value", "override_reason", *T),
    "valuation_comparables": ("id", "result_id", "property_id", "similarity", "adjustments_json"),
    "valuation_drift_metrics": ("id", "model_version_id", "segment", "metric", "value", "threshold", "status", *T),
    "recommendation_profiles": ("id", "user_id", "organization_id", "enabled", "signals_json", "reset_at", *T),
    "recommendation_experiments": ("id", "key", "status", "variants_json", *T),
    "recommendation_assignments": ("id", "experiment_id", "user_id", "variant", "assigned_at"),
    "recommendation_impressions": ("id", "user_id", "property_id", "source", "score", "reason", "experiment_key", "created_at"),
    "recommendation_feedback": ("id", "user_id", "property_id", "action", "metadata_json", "created_at"),
    "gpu_worker_pools": ("id", "organization_id", "name", "capabilities_json", "status", "max_concurrency", "hourly_cost", *T),
    "capture_sessions": ("id", "organization_id", "property_id", "created_by_user_id", "status", "capture_type", "requirements_json", "quality_report_json", *T),
    "capture_files": ("id", "session_id", "url", "sha256", "mime_type", "size_bytes", "metadata_json", *T),
    "reconstruction_jobs": ("id", "session_id", "representation", "status", "stage", "progress", "checkpoint_json", "worker_pool_id", "cost_amount", "error", *T),
    "reconstruction_artifacts": ("id", "job_id", "asset_type", "url", "version", "metadata_json", "published", *T),
    "generated_asset_reviews": ("id", "artifact_id", "reviewer_user_id", "status", "notes", *T),
    "ar_assets": ("id", "organization_id", "property_id", "source_artifact_id", "status", "variants_json", "placement_profile_json", "scale_meters", *T),
    "ar_sessions": ("id", "asset_id", "user_id", "device_json", "status", "created_at"),
    "vr_tour_configs": ("id", "organization_id", "property_id", "source_artifact_id", "status", "navigation_json", "comfort_json", "fallback_url", *T),
    "vr_sessions": ("id", "tour_id", "user_id", "device_profile", "performance_json", "status", "created_at"),
    "mobile_devices": ("id", "user_id", "device_id", "platform", "push_token", "app_version", "last_seen_at", *T),
    "mobile_refresh_tokens": ("id", "user_id", "device_id", "token_hash", "expires_at", "revoked_at", "replaced_by_id", "created_at"),
    "mobile_mutations": ("id", "user_id", "device_id", "client_mutation_id", "mutation_type", "payload_json", "status", "result_json", *T),
    "ml_artifacts": ("id", "organization_id", "kind", "uri", "sha256", "metadata_json", *T),
    "ml_model_versions": ("id", "organization_id", "name", "task", "version", "status", "artifact_id", "feature_version", "metrics_json", *T),
    "ml_evaluations": ("id", "model_version_id", "dataset_version", "metrics_json", "passed", "gate_json", *T),
    "ml_deployments": ("id", "model_version_id", "environment", "status", "traffic_percent", "started_at", "ended_at", *T),
    "ml_usage_records": ("id", "organization_id", "job_type", "units", "cost_amount", "metadata_json", "created_at"),
    "feature_kill_switches": ("id", "organization_id", "key", "enabled", "reason", *T),
}

CORE_COLUMNS = {
    "agencies": "organization_id",
    "agents": "organization_id",
    "projects": "organization_id",
    "properties": "organization_id",
    "appointments": "organization_id",
    "leads": "organization_id",
}


def _copy_table(name: str) -> None:
    source = Base.metadata.tables[name]
    actual = set(source.columns.keys())
    expected = set(P2_SCHEMA[name])
    if actual != expected:
        raise RuntimeError(
            f"Historical P2 schema drift for {name}: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}"
        )
    columns = [column._copy() for column in source.columns]
    constraints: list[sa.Constraint] = []
    for constraint in source.constraints:
        if isinstance(constraint, UniqueConstraint):
            constraints.append(
                sa.UniqueConstraint(
                    *(column.name for column in constraint.columns),
                    name=constraint.name,
                )
            )
        elif isinstance(constraint, CheckConstraint):
            constraints.append(sa.CheckConstraint(str(constraint.sqltext), name=constraint.name))
    op.create_table(name, *columns, *constraints)
    for index in sorted(source.indexes, key=lambda item: item.name or ""):
        names = [getattr(expression, "name", None) for expression in index.expressions]
        if not (index.name and all(names)):
            continue
        if len(names) == 1 and source.columns[names[0]].index:
            continue
        op.create_index(index.name, name, names, unique=index.unique)


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(inspect(bind).get_table_names())
    for name in P2_SCHEMA:
        if name not in existing_tables:
            _copy_table(name)
    for table, column in CORE_COLUMNS.items():
        inspector = inspect(bind)
        existing = {item["name"] for item in inspector.get_columns(table)}
        if column not in existing:
            op.add_column(table, sa.Column(column, sa.String(36), nullable=True))

        inspector = inspect(bind)
        index_name = f"ix_{table}_{column}"
        index_names = {item["name"] for item in inspector.get_indexes(table)}
        if index_name not in index_names:
            op.create_index(index_name, table, [column], unique=False)

        if bind.dialect.name != "sqlite":
            foreign_keys = inspector.get_foreign_keys(table)
            has_org_fk = any(
                item.get("constrained_columns") == [column]
                and item.get("referred_table") == "organizations"
                for item in foreign_keys
            )
            if not has_org_fk:
                op.create_foreign_key(
                    f"fk_{table}_{column}_organizations",
                    table,
                    "organizations",
                    [column],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column in reversed(tuple(CORE_COLUMNS.items())):
        existing = {item["name"] for item in inspect(bind).get_columns(table)}
        if column not in existing:
            continue
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_column(column)
        else:
            # PostgreSQL drops dependent indexes and foreign-key constraints with the column.
            op.drop_column(table, column)
    for name in reversed(tuple(P2_SCHEMA)):
        if name in set(inspect(bind).get_table_names()):
            op.drop_table(name)
