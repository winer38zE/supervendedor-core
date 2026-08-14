"""
app/routers/ads_router.py
────────────────────────────────────────────────────────────────────────────────
Capa 5 — Endpoints HTTP para orquestación Meta Ads (cron n8n / manual).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.security import verify_api_key

router = APIRouter(
    prefix="/ads",
    tags=["Meta Ads"],
    dependencies=[Depends(verify_api_key)],
)


class RunCycleRequest(BaseModel):
    """Parámetros opcionales para sobreescribir .env en una ejecución."""

    launch_new_campaign: Optional[bool] = Field(
        None,
        description="Si true, intenta lanzar campaña PAUSED desde trend top. None = ADS_AUTO_LAUNCH_ENABLED",
    )
    min_priority_score: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Score mínimo para lanzar (default ADS_MIN_PRIORITY_SCORE=70)",
    )
    incluir_trends: bool = Field(True, description="Ejecutar Capa 1 trend_scout")
    evaluar_reglas: bool = Field(True, description="Ejecutar Capa 4 evaluar_campanas")
    notificar_whatsapp: Optional[bool] = Field(
        None,
        description="Enviar resumen consolidado a ADS_NOTIFY_WHATSAPP",
    )


@router.post("/run-cycle")
async def ads_run_cycle(body: RunCycleRequest | None = None) -> dict[str, Any]:
    """
    Ciclo autónomo Meta Ads — invocar cada 4–6 h desde n8n.

    Secuencia: trends → armar_campana (si aplica) → evaluar_campanas → WhatsApp.
    """
    opts = body or RunCycleRequest()
    from app.marketing.ads_orchestrator import run_ads_cycle

    return await run_ads_cycle(
        launch_new_campaign=opts.launch_new_campaign,
        min_priority_score=opts.min_priority_score,
        incluir_trends=opts.incluir_trends,
        evaluar_reglas=opts.evaluar_reglas,
        notificar_whatsapp=opts.notificar_whatsapp,
    )


@router.get("/status")
def ads_status() -> dict[str, Any]:
    """Estado de configuración Meta Ads (sin llamar APIs externas)."""
    token_ok = bool(os.environ.get("META_ACCESS_TOKEN", "").strip())
    account_ok = bool(os.environ.get("META_AD_ACCOUNT_ID", "").strip())
    page_ok = bool(os.environ.get("META_PAGE_ID", "").strip())
    notify = os.environ.get("ADS_NOTIFY_WHATSAPP", os.environ.get("OWNER_WHATSAPP", ""))

    return {
        "meta_configured": token_ok and account_ok,
        "meta_page_configured": page_ok,
        "ads_auto_launch": os.environ.get("ADS_AUTO_LAUNCH_ENABLED", "true"),
        "ads_min_priority_score": os.environ.get("ADS_MIN_PRIORITY_SCORE", "70"),
        "ads_notify_whatsapp": bool(notify),
        "endpoints": {
            "run_cycle": "POST /ads/run-cycle",
            "status": "GET /ads/status",
        },
    }
