"""
app/content/models.py
────────────────────────────────────────────────────────────────────────────────
Modelos SQLAlchemy — perfiles monitoreados, outliers virales y guiones generados.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.sqlalchemy_session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SocialPlatform(str, enum.Enum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class MonitoredProfile(Base):
    __tablename__ = "monitored_profiles"
    __table_args__ = (
        Index("ix_monitored_profiles_tenant_handle", "tenant_id", "platform", "handle", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[SocialPlatform] = mapped_column(Enum(SocialPlatform), nullable=False)
    handle: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    avg_views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    outliers: Mapped[list["ViralOutlier"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class ViralOutlier(Base):
    __tablename__ = "viral_outliers"
    __table_args__ = (
        Index("ix_viral_outliers_tenant_score", "tenant_id", "outlier_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("monitored_profiles.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[SocialPlatform] = mapped_column(Enum(SocialPlatform), nullable=False)
    video_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    external_video_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outlier_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    structure_hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structure_tension: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structure_resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_metrics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    profile: Mapped[Optional["MonitoredProfile"]] = relationship(back_populates="outliers")
    scripts: Mapped[list["GeneratedScript"]] = relationship(
        back_populates="outlier",
        cascade="all, delete-orphan",
    )


class GeneratedScript(Base):
    __tablename__ = "generated_scripts"
    __table_args__ = (
        Index("ix_generated_scripts_tenant_outlier", "tenant_id", "outlier_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outlier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("viral_outliers.id", ondelete="CASCADE"), nullable=False
    )
    niche: Mapped[str] = mapped_column(String(256), nullable=False)
    brand_voice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    remix_level: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    script_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    script_body: Mapped[str] = mapped_column(Text, nullable=False)
    hook: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tension: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    llm_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    outlier: Mapped["ViralOutlier"] = relationship(back_populates="scripts")
