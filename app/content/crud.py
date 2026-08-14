"""
app/content/crud.py
────────────────────────────────────────────────────────────────────────────────
Operaciones CRUD — Content & Outliers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.content.exceptions import ContentConflictError, ContentNotFoundError
from app.content.models import GeneratedScript, MonitoredProfile, SocialPlatform, ViralOutlier
from app.content.schemas import OutlierAnalyzeRequest, ProfileCreate, ScriptGenerateRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Perfiles ──────────────────────────────────────────────────────────────────

def get_profile(db: Session, profile_id: str) -> Optional[MonitoredProfile]:
    return db.get(MonitoredProfile, profile_id)


def get_profile_by_handle(
    db: Session,
    tenant_id: str,
    platform: SocialPlatform,
    handle: str,
) -> Optional[MonitoredProfile]:
    return (
        db.query(MonitoredProfile)
        .filter(
            MonitoredProfile.tenant_id == tenant_id,
            MonitoredProfile.platform == platform,
            MonitoredProfile.handle == handle,
        )
        .first()
    )


def create_profile(db: Session, payload: ProfileCreate) -> MonitoredProfile:
    existing = get_profile_by_handle(db, payload.tenant_id, payload.platform, payload.handle)
    if existing:
        raise ContentConflictError(
            f"El perfil @{payload.handle} ({payload.platform.value}) ya existe para tenant '{payload.tenant_id}'"
        )

    profile = MonitoredProfile(
        tenant_id=payload.tenant_id,
        platform=payload.platform,
        handle=payload.handle,
        profile_url=str(payload.profile_url) if payload.profile_url else None,
        display_name=payload.display_name,
        avg_views=payload.avg_views,
        notes=payload.notes,
        metadata_json=payload.metadata,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ── Outliers ──────────────────────────────────────────────────────────────────

def get_outlier(db: Session, outlier_id: str) -> Optional[ViralOutlier]:
    return db.get(ViralOutlier, outlier_id)


def get_outlier_for_tenant(db: Session, outlier_id: str, tenant_id: str) -> ViralOutlier:
    outlier = get_outlier(db, outlier_id)
    if not outlier or outlier.tenant_id != tenant_id:
        raise ContentNotFoundError(f"Outlier '{outlier_id}' no encontrado para tenant '{tenant_id}'")
    return outlier


def create_outlier(
    db: Session,
    payload: OutlierAnalyzeRequest,
    *,
    engagement_rate: float,
    outlier_score: float,
    structure_hook: str,
    structure_tension: str,
    structure_resolution: str,
    analysis_notes: Optional[str] = None,
) -> ViralOutlier:
    if payload.profile_id:
        profile = get_profile(db, payload.profile_id)
        if not profile or profile.tenant_id != payload.tenant_id:
            raise ContentNotFoundError(
                f"Perfil '{payload.profile_id}' no encontrado para tenant '{payload.tenant_id}'"
            )

    outlier = ViralOutlier(
        tenant_id=payload.tenant_id,
        profile_id=payload.profile_id,
        platform=payload.platform,
        video_url=str(payload.video_url) if payload.video_url else None,
        external_video_id=payload.external_video_id,
        caption=payload.caption,
        transcript=payload.transcript,
        views=payload.metrics.views,
        likes=payload.metrics.likes,
        comments=payload.metrics.comments,
        shares=payload.metrics.shares,
        engagement_rate=engagement_rate,
        outlier_score=outlier_score,
        structure_hook=structure_hook,
        structure_tension=structure_tension,
        structure_resolution=structure_resolution,
        analysis_notes=analysis_notes,
        raw_metrics=payload.metrics.model_dump(),
        analyzed_at=_utcnow(),
    )
    db.add(outlier)
    db.commit()
    db.refresh(outlier)
    return outlier


# ── Guiones ───────────────────────────────────────────────────────────────────

def create_generated_script(
    db: Session,
    payload: ScriptGenerateRequest,
    *,
    script_title: str,
    script_body: str,
    hook: str,
    tension: str,
    resolution: str,
    cta: str,
    llm_provider: str,
    llm_model: str,
    metadata: Optional[dict] = None,
) -> GeneratedScript:
    get_outlier_for_tenant(db, payload.outlier_id, payload.tenant_id)

    script = GeneratedScript(
        tenant_id=payload.tenant_id,
        outlier_id=payload.outlier_id,
        niche=payload.niche,
        brand_voice=payload.brand_voice,
        remix_level=payload.remix_level,
        script_title=script_title,
        script_body=script_body,
        hook=hook,
        tension=tension,
        resolution=resolution,
        cta=cta,
        llm_provider=llm_provider,
        llm_model=llm_model,
        metadata_json=metadata,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return script
