"""P2 marketplace, payments, contracts, intelligence, spatial, mobile and ML operations.

Revision ID: 0003_p2_platform
Revises: 0002_p1_platform
"""
from alembic import op
from sqlalchemy import inspect, text
from app.database import Base
from app import models  # noqa: F401

revision = "0003_p2_platform"
down_revision = "0002_p1_platform"
branch_labels = None
depends_on = None

P2_TABLES = [name for name in Base.metadata.tables if name in {
    "organizations","organization_members","organization_invitations","organization_roles","organization_feature_flags",
    "marketplace_plans","organization_subscriptions","listing_quotas","agency_verification_cases","tenant_audit_exports",
    "payment_provider_accounts","reservation_orders","payment_intents","payment_transactions","payment_webhook_events",
    "refund_requests","payment_disputes","ledger_accounts","ledger_entries","settlement_batches","reconciliation_runs",
    "legal_document_policies","contract_templates","contract_envelopes","contract_participants","signature_events","signature_evidence",
    "valuation_model_versions","valuation_evaluations","valuation_requests","valuation_results","valuation_comparables","valuation_drift_metrics",
    "recommendation_profiles","recommendation_experiments","recommendation_assignments","recommendation_impressions","recommendation_feedback",
    "gpu_worker_pools","capture_sessions","capture_files","reconstruction_jobs","reconstruction_artifacts","generated_asset_reviews",
    "ar_assets","ar_sessions","vr_tour_configs","vr_sessions","mobile_devices","mobile_refresh_tokens","mobile_mutations",
    "ml_artifacts","ml_model_versions","ml_evaluations","ml_deployments","ml_usage_records","feature_kill_switches"
}]
CORE_COLUMNS = {
    "agencies":"organization_id", "agents":"organization_id", "projects":"organization_id", "properties":"organization_id",
    "appointments":"organization_id", "leads":"organization_id",
}

def upgrade():
    bind=op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    inspector=inspect(bind)
    for table,column in CORE_COLUMNS.items():
        existing={c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(36)")
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})")

def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name
    for table, column in CORE_COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column in existing:
            op.execute(f"DROP INDEX IF EXISTS ix_{table}_{column}")
            if dialect == "sqlite":
                with op.batch_alter_table(table, recreate="always") as batch:
                    batch.drop_column(column)
            else:
                op.drop_column(table, column)
    for name in reversed(P2_TABLES):
        table = Base.metadata.tables.get(name)
        if table is not None:
            table.drop(bind=bind, checkfirst=True)
