"""
app/content/schemas.py
────────────────────────────────────────────────────────────────────────────────
Esquemas Pydantic v2 — Content & Outliers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.content.models import SocialPlatform


# ── Perfiles monitoreados ─────────────────────────────────────────────────────

class ProfileCreate(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    platform: SocialPlatform
    handle: str = Field(..., min_length=1, max_length=128, description="Usuario sin @")
    profile_url: Optional[HttpUrl] = None
    display_name: Optional[str] = Field(default=None, max_length=256)
    avg_views: int = Field(default=0, ge=0, description="Baseline de views para calcular outlier_score")
    notes: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("handle")
    @classmethod
    def strip_at(cls, value: str) -> str:
        return value.strip().lstrip("@")


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    platform: SocialPlatform
    handle: str
    profile_url: Optional[str] = None
    display_name: Optional[str] = None
    avg_views: int
    is_active: bool
    notes: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


# ── Análisis de outliers ──────────────────────────────────────────────────────

class VideoMetrics(BaseModel):
    views: int = Field(..., ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)


class OutlierAnalyzeRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    platform: SocialPlatform
    metrics: VideoMetrics
    profile_id: Optional[str] = Field(default=None, description="FK a MonitoredProfile para baseline")
    baseline_views: Optional[int] = Field(
        default=None,
        ge=1,
        description="Override manual del promedio del creador",
    )
    video_url: Optional[HttpUrl] = None
    external_video_id: Optional[str] = Field(default=None, max_length=128)
    caption: Optional[str] = Field(default=None, max_length=8000)
    transcript: Optional[str] = Field(
        default=None,
        max_length=20000,
        description="Transcripción del reel — mejora extracción de estructura",
    )
    simulate: bool = Field(
        default=False,
        description="Si True, genera estructura demo sin LLM (útil para pruebas)",
    )


class ContentStructure(BaseModel):
    hook: str
    tension: str
    resolution: str
    analysis_notes: Optional[str] = None


class OutlierAnalyzeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    profile_id: Optional[str] = None
    platform: SocialPlatform
    video_url: Optional[str] = None
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float
    outlier_score: float
    structure: ContentStructure
    analyzed_at: Optional[datetime] = None
    created_at: datetime


# ── Generación de guiones ─────────────────────────────────────────────────────

class ContentAdsProduct(BaseModel):
    titulo: str = Field(..., min_length=2, max_length=120)
    imagen_url: Optional[str] = Field(default=None, max_length=512)
    producto_url: Optional[str] = Field(default=None, max_length=512)
    precio_cop: Optional[float] = Field(default=None, ge=0)
    keyword: Optional[str] = Field(default=None, max_length=120)
    producto_id: Optional[str] = Field(default=None, max_length=64)
    nombre_campana: Optional[str] = Field(default=None, max_length=120)
    creative_format: str = Field(default="image", pattern="^(image|video)$")
    daily_budget_cop: Optional[float] = Field(default=None, ge=1000)


class ScriptGenerateRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    outlier_id: str = Field(..., min_length=1)
    niche: str = Field(..., min_length=2, max_length=256, description="Nicho del cliente")
    brand_voice: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Tono de marca: formal, cercano, agresivo, premium…",
    )
    remix_level: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0=solo voz de marca, 1=copia fiel de estructura viral",
    )
    product_focus: Optional[str] = Field(
        default=None,
        max_length=512,
        description="Producto/servicio a promover en el guion",
    )
    llm_preference: str = Field(
        default="openai",
        pattern="^(auto|openai|claude|gemini)$",
        description="openai es más rápido/barato para guiones",
    )
    target_duration_seconds: int = Field(default=45, ge=15, le=180)
    launch_ads: bool = Field(
        default=False,
        description="Encolar campaña Meta PAUSED en background (sin bloquear respuesta)",
    )
    auto_producto: bool = Field(
        default=True,
        description="Si launch_ads=true y no hay producto, usar top seller del catálogo Shein",
    )
    catalog_query: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Búsqueda en catálogo Shein (default: product_focus → niche)",
    )
    producto: Optional[ContentAdsProduct] = Field(
        default=None,
        description="Override manual — si vacío y auto_producto=true, se usa catálogo Shein",
    )
    skip_meta_create: bool = Field(
        default=False,
        description="Si true, solo genera creative+copy+compliance sin crear en Meta",
    )

    @model_validator(mode="after")
    def validate_ads_producto(self) -> "ScriptGenerateRequest":
        if self.launch_ads and self.producto is None and not self.auto_producto:
            raise ValueError(
                "Indica 'producto' manual o activa auto_producto=true para catálogo Shein"
            )
        return self


class ScriptGenerateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    outlier_id: str
    niche: str
    remix_level: float
    script_title: Optional[str] = None
    script_body: str
    hook: Optional[str] = None
    tension: Optional[str] = None
    resolution: Optional[str] = None
    cta: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: datetime
    ads_queued: bool = False


# ── Pipeline unificado (1 sola llamada HTTP) ───────────────────────────────────

class ContentPipelineRequest(BaseModel):
    """Flujo completo: analizar outlier → generar guion → (opcional) Meta Ads."""

    tenant_id: str = Field(..., min_length=1, max_length=64)
    platform: SocialPlatform
    metrics: VideoMetrics
    niche: str = Field(..., min_length=2, max_length=256)
    caption: Optional[str] = Field(default=None, max_length=8000)
    transcript: Optional[str] = None
    profile_id: Optional[str] = None
    baseline_views: Optional[int] = Field(default=None, ge=1)
    remix_level: float = Field(default=0.5, ge=0.0, le=1.0)
    brand_voice: Optional[str] = Field(default=None, max_length=2000)
    product_focus: Optional[str] = None
    simulate: bool = Field(default=False)
    launch_ads: bool = Field(default=False)
    single_pass: bool = Field(
        default=True,
        description="1 sola llamada LLM (50% más barato). false = analyze + generate separados",
    )
    force_process: bool = Field(
        default=False,
        description="Forzar LLM aunque el composite_score esté bajo el umbral",
    )
    target_duration_seconds: int = Field(default=45, ge=15, le=180)
    webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="POST al terminar (completed/skipped/ads_queued)",
    )
    use_trends: bool = Field(
        default=True,
        description="Priorizar producto catálogo alineado con Google Trends",
    )
    auto_producto: bool = Field(
        default=True,
        description="Rellenar producto desde catálogo Shein si launch_ads=true",
    )
    catalog_query: Optional[str] = Field(default=None, max_length=256)
    producto: Optional[ContentAdsProduct] = None
    skip_meta_create: bool = False
    llm_preference: str = Field(default="openai", pattern="^(auto|openai|claude|gemini)$")

    @model_validator(mode="after")
    def validate_pipeline_ads(self) -> "ContentPipelineRequest":
        if self.launch_ads and self.producto is None and not self.auto_producto:
            raise ValueError(
                "Indica 'producto' manual o activa auto_producto=true para catálogo Shein"
            )
        return self


class ContentPipelineResponse(BaseModel):
    outlier_id: str
    script_id: str = ""
    outlier_score: float
    engagement_rate: float
    composite_score: float = 0.0
    structure: ContentStructure
    script_title: Optional[str] = None
    script_preview: str = Field(default="", description="Primeros 280 chars del guion")
    ads_queued: bool = False
    skipped: bool = False
    skip_reason: Optional[str] = None
    llm_calls: int = 0
    mode: str = Field(default="single_pass", description="single_pass | dual_pass | skipped")
    producto: Optional[ContentAdsProduct] = None
    catalog_source: Optional[str] = Field(
        default=None,
        description="shein_catalog | shein_catalog+trends | manual",
    )
    trend_keyword: Optional[str] = None
    billing_mode: Optional[str] = Field(
        default=None,
        description="trial | activo | legacy — modo de cobro aplicado",
    )
