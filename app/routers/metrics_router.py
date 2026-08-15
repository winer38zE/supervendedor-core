"""
app/routers/metrics_router.py — Métricas unificadas de negocio ED NET PRO 3.0
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.config import settings
from app.core.platform import platform_architecture_payload
from app.security import verify_api_key
from app.services.platform_tools_service import (
    buscar_productos_inventario,
    consultar_ventas_pocketbase,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(verify_api_key)],
)


def _channel_health() -> dict[str, Any]:
    return {
        "whatsapp_evolution": {
            "configured": bool(settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY),
            "instance": settings.EVOLUTION_INSTANCE,
            "webhooks": ["/webhook/whatsapp", "/whatsapp/webhook"],
        },
        "vapi_voice": {
            "configured": bool(settings.VAPI_WEBHOOK_SECRET or settings.ENV != "production"),
            "webhooks": ["/vapi/webhook", "/vapi/tools/webhook"],
        },
        "mcp_servidor_ventas": {
            "entrypoint": "servidor_ventas.py",
            "transport": "stdio",
        },
    }


@router.get("/architecture")
async def get_architecture() -> dict[str, Any]:
    """Mapa arquitectónico runtime de ED NET PRO 3.0."""
    payload = platform_architecture_payload()
    payload["runtime"] = {
        "env": settings.ENV,
        "owner_id": settings.OWNER_ID,
        "fastapi_port": settings.PORT,
        "public_url": settings.PUBLIC_URL or None,
    }
    return payload


@router.get("/overview")
async def metrics_overview(
    ventas_limit: int = Query(10, ge=1, le=100),
    catalog_query: str = Query("", description="Filtro opcional de catálogo"),
) -> dict[str, Any]:
    """
    Panel consolidado: ventas PocketBase + resumen catálogo + salud de canales.
    """
    ventas = await consultar_ventas_pocketbase(limit=ventas_limit)
    catalog = await buscar_productos_inventario(
        catalog_query or "jumpsuit",
        limit=5,
    )

    catalog_summary = catalog.get("resumen_catalogo")
    if not catalog_summary:
        try:
            from app.agents.catalog_bridge_agent import get_catalog_bridge

            catalog_summary = get_catalog_bridge().get_catalog_summary()
        except Exception as exc:
            logger.debug("Catalog summary fallback: %s", exc)
            catalog_summary = {}

    return {
        "ok": True,
        "platform": "ED NET PRO",
        "version": "3.0.0",
        "ventas": ventas,
        "catalogo": {
            "muestra": catalog.get("productos", [])[:5],
            "total_muestra": catalog.get("total_encontrados", len(catalog.get("productos", []))),
            "summary": catalog_summary,
        },
        "canales": _channel_health(),
        "marketing": {
            "meta_ads_configured": bool(settings.META_ACCESS_TOKEN.strip()),
            "endpoint_cycle": "POST /ads/run-cycle",
        },
    }


@router.get("/ventas")
async def metrics_ventas(
    limit: int = Query(20, ge=1, le=100),
    estado: str = Query(""),
    producto: str = Query(""),
) -> dict[str, Any]:
    """Atajo HTTP a consultar_ventas_pocketbase."""
    return await consultar_ventas_pocketbase(limit=limit, estado=estado, producto=producto)


@router.get("/inventario")
async def metrics_inventario(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Atajo HTTP a buscar_productos_inventario."""
    return await buscar_productos_inventario(q, limit=limit)
