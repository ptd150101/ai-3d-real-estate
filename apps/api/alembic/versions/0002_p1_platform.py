"""P1 engagement, notifications, messaging, CRM, experience, trust and analytics.

Revision ID: 0002_p1_platform
Revises: 0001_initial

Only the explicit P1 table set is created. This prevents later P2 models from leaking into
an earlier migration while preserving the already-validated P1 ORM definitions.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.sql.schema import CheckConstraint, UniqueConstraint

from app.database import Base
from app import models  # noqa: F401 -- populate metadata

revision = "0002_p1_platform"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

P1_TABLES = [
    "notification_preferences", "notification_events", "notification_deliveries",
    "notification_templates", "notification_unsubscribes", "saved_search_subscriptions",
    "saved_search_matches", "agent_availability_rules", "agent_availability_exceptions",
    "appointment_slots", "calendar_connections", "calendar_sync_events", "agent_reviews",
    "review_responses", "review_reports", "conversation_threads", "conversation_participants",
    "direct_messages", "message_receipts", "message_attachments", "crm_connections",
    "crm_entity_mappings", "crm_sync_events", "agent_routing_rules", "agent_capacity_states",
    "lead_assignment_history", "panorama_scenes", "panorama_links", "panorama_hotspots",
    "model_navigation_zones", "brochure_assets", "legal_document_versions",
    "legal_document_reviews", "legal_document_review_events", "document_access_grants",
    "document_download_logs", "analytics_sessions", "analytics_events", "daily_funnel_metrics",
    "daily_property_metrics", "daily_agent_metrics", "ai_quality_evaluations", "durable_jobs",
]


def _copy_table(name: str) -> None:
    source = Base.metadata.tables[name]
    columns = [column._copy() for column in source.columns]
    constraints: list[sa.Constraint] = []
    for constraint in source.constraints:
        if isinstance(constraint, UniqueConstraint):
            constraints.append(
                sa.UniqueConstraint(*(column.name for column in constraint.columns), name=constraint.name)
            )
        elif isinstance(constraint, CheckConstraint):
            constraints.append(sa.CheckConstraint(str(constraint.sqltext), name=constraint.name))

    op.create_table(name, *columns, *constraints)
    for index in sorted(source.indexes, key=lambda item: item.name or ""):
        names = [getattr(expression, "name", None) for expression in index.expressions]
        if index.name and all(names):
            op.create_index(index.name, name, names, unique=index.unique)


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for name in P1_TABLES:
        if name not in existing:
            _copy_table(name)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for name in reversed(P1_TABLES):
        if name in existing:
            op.drop_table(name)
