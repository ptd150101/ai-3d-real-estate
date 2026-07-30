from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .common import TimestampMixin, new_id, utcnow


class PanoramaScene(Base, TimestampMixin):
    __tablename__ = "panorama_scenes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[str | None] = mapped_column(ForeignKey("property_floors.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    image_url: Mapped[str] = mapped_column(String(1024))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    initial_yaw: Mapped[float] = mapped_column(Float, default=0)
    initial_pitch: Mapped[float] = mapped_column(Float, default=0)
    initial_fov: Mapped[float] = mapped_column(Float, default=75)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PanoramaLink(Base, TimestampMixin):
    __tablename__ = "panorama_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_scene_id: Mapped[str] = mapped_column(ForeignKey("panorama_scenes.id", ondelete="CASCADE"), index=True)
    target_scene_id: Mapped[str] = mapped_column(ForeignKey("panorama_scenes.id", ondelete="CASCADE"), index=True)
    yaw: Mapped[float] = mapped_column(Float)
    pitch: Mapped[float] = mapped_column(Float, default=0)
    label: Mapped[str | None] = mapped_column(String(160))
    __table_args__ = (UniqueConstraint("source_scene_id", "target_scene_id", name="uq_panorama_link"),)


class PanoramaHotspot(Base, TimestampMixin):
    __tablename__ = "panorama_hotspots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scene_id: Mapped[str] = mapped_column(ForeignKey("panorama_scenes.id", ondelete="CASCADE"), index=True)
    yaw: Mapped[float] = mapped_column(Float)
    pitch: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    hotspot_type: Mapped[str] = mapped_column(String(32), default="info")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelNavigationZone(Base, TimestampMixin):
    __tablename__ = "model_navigation_zones"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[str | None] = mapped_column(ForeignKey("property_floors.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    zone_type: Mapped[str] = mapped_column(String(32), default="walkable")
    points_json: Mapped[list[list[float]]] = mapped_column(JSON)
    min_y: Mapped[float] = mapped_column(Float, default=0)
    max_y: Mapped[float] = mapped_column(Float, default=6)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class BrochureAsset(Base, TimestampMixin):
    __tablename__ = "brochure_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    storage_url: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    template_version: Mapped[str] = mapped_column(String(32), default="v1")
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("property_id", "checksum", "template_version", name="uq_brochure_cache"),)
