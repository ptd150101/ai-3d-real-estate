from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base
from .common import TimestampMixin, new_id
from .identity import Agent, Project

class Property(Base, TimestampMixin):
    __tablename__ = "properties"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    transaction_type: Mapped[str] = mapped_column(String(16), default="sale", index=True)
    property_type: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    price: Mapped[int] = mapped_column(Integer, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    area_m2: Mapped[float] = mapped_column(Float, index=True)
    bedrooms: Mapped[int] = mapped_column(Integer, default=0, index=True)
    bathrooms: Mapped[int] = mapped_column(Integer, default=0)
    floors_count: Mapped[int] = mapped_column(Integer, default=1)
    parking_spaces: Mapped[int] = mapped_column(Integer, default=0)
    address: Mapped[str] = mapped_column(String(500))
    ward: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str] = mapped_column(String(120), index=True)
    city: Mapped[str] = mapped_column(String(120), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    legal_status: Mapped[str | None] = mapped_column(String(120), index=True)
    furnishing: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    year_built: Mapped[int | None] = mapped_column(Integer)
    direction: Mapped[str | None] = mapped_column(String(48))
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_owner_listing: Mapped[bool] = mapped_column(Boolean, default=False)
    has_3d: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    agent: Mapped[Agent | None] = relationship()
    project: Mapped[Project | None] = relationship()
    features: Mapped[list[PropertyFeature]] = relationship(cascade="all, delete-orphan", back_populates="property")
    media: Mapped[list[PropertyMedia]] = relationship(cascade="all, delete-orphan", back_populates="property", order_by="PropertyMedia.sort_order")
    model_3d: Mapped[PropertyModel3D | None] = relationship(cascade="all, delete-orphan", back_populates="property", uselist=False)
    documents: Mapped[list[PropertyDocument]] = relationship(cascade="all, delete-orphan", back_populates="property")

    __table_args__ = (
        Index("ix_properties_search", "city", "district", "transaction_type", "status"),
        Index("ix_properties_price_area", "price", "area_m2"),
    )

class PropertyFeature(Base):
    __tablename__ = "property_features"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(80), default="amenity")
    value: Mapped[str | None] = mapped_column(String(300))
    property: Mapped[Property] = relationship(back_populates="features")
    __table_args__ = (UniqueConstraint("property_id", "name", name="uq_property_feature"),)

class PropertyMedia(Base, TimestampMixin):
    __tablename__ = "property_media"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    media_type: Mapped[str] = mapped_column(String(32), default="image")
    url: Mapped[str] = mapped_column(String(1024))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024))
    alt_text: Mapped[str | None] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    property: Mapped[Property] = relationship(back_populates="media")

class PropertyModel3D(Base, TimestampMixin):
    __tablename__ = "property_models_3d"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), unique=True)
    model_url: Mapped[str] = mapped_column(String(1024))
    poster_url: Mapped[str | None] = mapped_column(String(1024))
    format: Mapped[str] = mapped_column(String(16), default="glb")
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    draco_compressed: Mapped[bool] = mapped_column(Boolean, default=False)
    meshopt_compressed: Mapped[bool] = mapped_column(Boolean, default=False)
    ktx2_textures: Mapped[bool] = mapped_column(Boolean, default=False)
    default_camera: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {"position": [8, 5, 8], "target": [0, 1, 0]})
    quality_presets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processing_status: Mapped[str] = mapped_column(String(32), default="ready")
    property: Mapped[Property] = relationship(back_populates="model_3d")
    floors: Mapped[list[PropertyFloor]] = relationship(cascade="all, delete-orphan", back_populates="model", order_by="PropertyFloor.sort_order")
    hotspots: Mapped[list[PropertyHotspot]] = relationship(cascade="all, delete-orphan", back_populates="model")

class PropertyFloor(Base):
    __tablename__ = "property_floors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("property_models_3d.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    object_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    furniture_object_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    camera: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[PropertyModel3D] = relationship(back_populates="floors")

class PropertyHotspot(Base):
    __tablename__ = "property_hotspots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("property_models_3d.id", ondelete="CASCADE"), index=True)
    floor_id: Mapped[str | None] = mapped_column(ForeignKey("property_floors.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[list[float]] = mapped_column(JSON)
    camera_position: Mapped[list[float] | None] = mapped_column(JSON)
    room_type: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[PropertyModel3D] = relationship(back_populates="hotspots")

class PropertyDocument(Base, TimestampMixin):
    __tablename__ = "property_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1024))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    property: Mapped[Property] = relationship(back_populates="documents")

class NearbyPlace(Base):
    __tablename__ = "nearby_places"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(220))
    category: Mapped[str] = mapped_column(String(80), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    distance_m: Mapped[int | None] = mapped_column(Integer)
