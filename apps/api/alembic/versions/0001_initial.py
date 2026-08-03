"""Initial Nestora schema with PostGIS and pgvector support.

Revision ID: 0001_initial
Revises: None

The historical P0 table set is explicit. Columns are copied only after checking the
frozen P0 snapshot so later ORM changes cannot silently add fields to this migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.sql.schema import CheckConstraint, UniqueConstraint

from app.database import Base
from app import models  # noqa: F401 -- populate metadata

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

T = ("created_at", "updated_at")
P0_SCHEMA: dict[str, tuple[str, ...]] = {
    "users": ("id", "email", "full_name", "password_hash", "role", "is_active", "phone", "avatar_url", *T),
    "agencies": ("id", "name", "slug", "logo_url", "description", "verified", *T),
    "agents": ("id", "user_id", "agency_id", "display_name", "phone", "email", "bio", "license_number", "verified", "rating", *T),
    "projects": ("id", "name", "slug", "developer", "description", "city", "district", "address", "latitude", "longitude", "status", "cover_url", *T),
    "properties": (
        "id", "slug", "title", "transaction_type", "property_type", "status", "price", "currency",
        "area_m2", "bedrooms", "bathrooms", "floors_count", "parking_spaces", "address", "ward",
        "district", "city", "latitude", "longitude", "legal_status", "furnishing", "description",
        "year_built", "direction", "is_featured", "is_verified", "is_owner_listing", "has_3d",
        "view_count", "verified_at", "expires_at", "published_at", "agent_id", "project_id", "owner_id", *T,
    ),
    "property_features": ("id", "property_id", "name", "category", "value"),
    "property_media": ("id", "property_id", "media_type", "url", "thumbnail_url", "alt_text", "sort_order", "metadata_json", *T),
    "property_models_3d": (
        "id", "property_id", "model_url", "poster_url", "format", "file_size_bytes", "draco_compressed",
        "meshopt_compressed", "ktx2_textures", "default_camera", "quality_presets", "processing_status", *T,
    ),
    "property_floors": ("id", "model_id", "name", "sort_order", "object_names", "furniture_object_names", "camera"),
    "property_hotspots": ("id", "model_id", "floor_id", "label", "description", "position", "camera_position", "room_type", "metadata_json"),
    "property_documents": ("id", "property_id", "document_type", "title", "url", "verified", "valid_from", "valid_until", *T),
    "nearby_places": ("id", "property_id", "name", "category", "latitude", "longitude", "distance_m"),
    "appointments": ("id", "property_id", "user_id", "agent_id", "full_name", "phone", "email", "scheduled_at", "note", "status", "source", *T),
    "leads": ("id", "property_id", "user_id", "full_name", "phone", "email", "message", "source", "status", "assigned_agent_id", *T),
    "favorites": ("id", "user_id", "property_id", "created_at"),
    "saved_searches": ("id", "user_id", "name", "filters_json", "notify", *T),
    "property_comparisons": ("id", "user_id", "session_key", "property_ids", *T),
    "chat_sessions": ("id", "user_id", "current_property_id", "current_floor_id", "selected_hotspot_id", "filters_json", "status", "handoff_requested", *T),
    "chat_messages": ("id", "session_id", "role", "content", "tool_name", "tool_payload", "citations", "created_at"),
    "knowledge_documents": ("id", "property_id", "project_id", "document_type", "title", "source_url", "content", "verified", "valid_from", "valid_until", *T),
    "knowledge_chunks": ("id", "document_id", "chunk_index", "content", "embedding_json", "metadata_json"),
    "audit_logs": ("id", "actor_user_id", "action", "entity_type", "entity_id", "before_json", "after_json", "ip_address", "created_at"),
    "background_jobs": ("id", "job_type", "payload_json", "status", "progress", "result_json", "error", *T),
}


def _copy_table(name: str, expected_columns: tuple[str, ...]) -> None:
    source = Base.metadata.tables[name]
    expected = set(expected_columns)
    actual = set(source.columns.keys())
    allowed_extra = {"organization_id"} if name in {"agencies", "agents", "projects", "properties", "appointments", "leads"} else set()
    if expected - actual or actual - expected - allowed_extra:
        raise RuntimeError(
            f"Historical P0 schema drift for {name}: "
            f"missing={sorted(expected-actual)}, extra={sorted(actual-expected-allowed_extra)}"
        )

    columns = [column._copy() for column in source.columns if column.name in expected]
    constraints: list[sa.Constraint] = []
    for constraint in source.constraints:
        constrained = {column.name for column in getattr(constraint, "columns", ())}
        if constrained and not constrained.issubset(expected):
            continue
        if isinstance(constraint, UniqueConstraint):
            constraints.append(sa.UniqueConstraint(*constrained, name=constraint.name))
        elif isinstance(constraint, CheckConstraint):
            constraints.append(sa.CheckConstraint(str(constraint.sqltext), name=constraint.name))

    op.create_table(name, *columns, *constraints)
    for index in sorted(source.indexes, key=lambda item: item.name or ""):
        names = [getattr(expression, "name", None) for expression in index.expressions]
        if not (index.name and all(names) and set(names).issubset(expected)):
            continue
        if len(names) == 1 and source.columns[names[0]].index:
            continue
        op.create_index(index.name, name, names, unique=index.unique)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    existing = set(inspect(bind).get_table_names())
    for name, columns in P0_SCHEMA.items():
        if name not in existing:
            _copy_table(name, columns)

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_properties_geo ON properties USING gist "
            "((ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography)) "
            "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
        )
        op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector(256)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw "
            "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for name in reversed(tuple(P0_SCHEMA)):
        if name in existing:
            op.drop_table(name)
