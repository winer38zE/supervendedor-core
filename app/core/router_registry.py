"""
app/core/router_registry.py — Registro centralizado de routers ED NET PRO 3.0
"""

from __future__ import annotations

from fastapi import FastAPI

from app import api_bridge
from app.routers import (
    ads_router,
    agents_router,
    avatares,
    centinela_router,
    chat,
    cierre_router,
    content_router,
    gupshup_handler,
    hunter_router,
    metrics_router,
    saas_router,
    vapi_handler,
    whatsapp_handler,
)


def register_platform_routers(app: FastAPI) -> None:
    """
    Monta todos los routers agrupados por dominio funcional.

    Canales (webhooks):
      - WhatsApp Evolution: /webhook/whatsapp + /whatsapp/webhook (legacy funnel)
      - Vapi Voice: /vapi/webhook + /vapi/tools/webhook

    Agentes & catálogo:
      - /agents/* — Catalog Bridge, ZOPA, followup
      - /api/v1/agents/* — Hermes Bridge

    Marketing & contenido:
      - /ads/* — Meta Ads
      - /api/v1/content/* — Outliers + pipeline

    Métricas & operaciones:
      - /api/v1/metrics/* — Dashboard unificado
      - /api/v1/chat — Orquestador n8n
    """
    # ── Canales de comunicación ───────────────────────────────────────────────
    app.include_router(vapi_handler.router, tags=["Canales — Vapi Voice"])
    app.include_router(gupshup_handler.router, prefix="/whatsapp", tags=["Canales — WhatsApp Legacy"])
    app.include_router(whatsapp_handler.router, tags=["Canales — WhatsApp MCP"])

    # ── Ventas & prospección ────────────────────────────────────────────────
    app.include_router(hunter_router.router, prefix="/hunter", tags=["Ventas — Hunter B2B"])
    app.include_router(cierre_router.router, prefix="/cierre", tags=["Ventas — Cierre"])
    app.include_router(centinela_router.router, prefix="/centinela", tags=["Ventas — Centinela"])
    app.include_router(agents_router.router, prefix="/agents", tags=["Agentes — Catálogo & CRM"])

    # ── Marketing digital ───────────────────────────────────────────────────
    app.include_router(ads_router.router, tags=["Marketing — Meta Ads"])
    app.include_router(content_router.router, prefix="/api/v1/content", tags=["Marketing — Content"])

    # ── Plataforma API v1 ───────────────────────────────────────────────────
    app.include_router(metrics_router.router, prefix="/api/v1/metrics", tags=["Plataforma — Métricas"])
    app.include_router(chat.router, prefix="/api/v1", tags=["Plataforma — Chat"])
    app.include_router(api_bridge.router, prefix="/api/v1", tags=["Plataforma — Hermes Bridge"])
    app.include_router(avatares.router, prefix="/api/v1/avatares", tags=["Plataforma — Avatares"])

    # ── SAAS admin (multi-tenant legacy) ────────────────────────────────────
    app.include_router(saas_router.router, prefix="/saas", tags=["SAAS — Admin"])
