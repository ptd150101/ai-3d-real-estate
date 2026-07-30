"""P1 engagement, notifications, messaging, CRM, experience, trust and analytics.

Revision ID: 0002_p1_platform
Revises: 0001_initial
"""
from alembic import op
from app.database import Base
from app import models  # noqa: F401

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


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for name in reversed(P1_TABLES):
        table = Base.metadata.tables.get(name)
        if table is not None:
            table.drop(bind=bind, checkfirst=True)
