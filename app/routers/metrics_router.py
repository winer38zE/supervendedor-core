"""
app/routers/metrics_router.py — Métricas unificadas de negocio ED NET PRO 3.0
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
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

_OVERVIEW_TIMEOUT = 12.0
_PROBE_TIMEOUT = 5.0


async def _probe_evolution_connection() -> dict[str, Any]:
    """Comprueba conectividad con Evolution API (estado de instancia WhatsApp)."""
    base_url = (settings.EVOLUTION_API_URL or "").rstrip("/")
    api_key = (settings.EVOLUTION_API_KEY or "").strip()
    instance = settings.EVOLUTION_INSTANCE or "super_vendedor"

    if not base_url or not api_key:
        return {
            "reachable": False,
            "connection_state": "not_configured",
        }

    endpoint = f"{base_url}/instance/connectionState/{instance}"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            response = await client.get(endpoint, headers={"apikey": api_key})
        if response.status_code != 200:
            return {
                "reachable": False,
                "connection_state": f"http_{response.status_code}",
            }

        payload = response.json()
        instance_data = payload.get("instance") if isinstance(payload.get("instance"), dict) else payload
        state = str(
            instance_data.get("state")
            or payload.get("state")
            or "unknown"
        )
        return {
            "reachable": True,
            "connection_state": state,
            "online": state.lower() in {"open", "connected", "online"},
        }
    except Exception as exc:
        logger.debug("[Metrics] Evolution probe failed: %s", exc)
        return {
            "reachable": False,
            "connection_state": "unreachable",
            "error": str(exc)[:120],
        }


async def _channel_health() -> dict[str, Any]:
    """
    Estado de canales WhatsApp, Vapi y MCP.

    Estructura consumida por admin_panel/api_store.build_channel_cards().
    """
    whatsapp_configured = bool(settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY)
    vapi_configured = bool(settings.VAPI_WEBHOOK_SECRET or settings.ENV != "production")

    evolution_probe = await _probe_evolution_connection() if whatsapp_configured else {}

    whatsapp_online = bool(
        whatsapp_configured
        and evolution_probe.get("online") is True
    )

    return {
        "whatsapp_evolution": {
            "configured": whatsapp_configured,
            "online": whatsapp_online,
            "instance": settings.EVOLUTION_INSTANCE,
            "api_url": settings.EVOLUTION_API_URL or None,
            "connection_state": evolution_probe.get("connection_state", "not_checked"),
            "reachable": evolution_probe.get("reachable", False),
            "webhooks": ["/webhook/whatsapp", "/whatsapp/webhook"],
            "module": "app/routers/whatsapp_handler.py",
        },
        "vapi_voice": {
            "configured": vapi_configured,
            "online": vapi_configured,
            "webhook_secret_set": bool(settings.VAPI_WEBHOOK_SECRET.strip()),
            "public_url": settings.PUBLIC_URL or None,
            "webhooks": ["/vapi/webhook", "/vapi/tools/webhook"],
            "module": "app/routers/vapi_handler.py",
            "tools": ["buscar_productos_inventario", "consultar_ventas_pocketbase", "agendar_cita"],
        },
        "mcp_servidor_ventas": {
            "configured": True,
            "online": True,
            "entrypoint": "servidor_ventas.py",
            "transport": "stdio",
            "module": "app/services/platform_tools_service.py",
        },
    }


async def _safe_ventas(limit: int) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            consultar_ventas_pocketbase(limit=limit),
            timeout=_OVERVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[Metrics] consultar_ventas_pocketbase timeout")
        return {
            "ok": False,
            "error": "timeout",
            "total_registros": 0,
            "ingresos_totales_cop": 0,
            "ventas": [],
        }
    except Exception as exc:
        logger.exception("[Metrics] consultar_ventas_pocketbase")
        return {
            "ok": False,
            "error": str(exc),
            "total_registros": 0,
            "ingresos_totales_cop": 0,
            "ventas": [],
        }


async def _safe_catalog(query: str) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            buscar_productos_inventario(query or "jumpsuit", limit=5),
            timeout=_OVERVIEW_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("[Metrics] buscar_productos_inventario timeout")
        return {"ok": False, "error": "timeout", "productos": [], "total_encontrados": 0}
    except Exception as exc:
        logger.exception("[Metrics] buscar_productos_inventario")
        return {"ok": False, "error": str(exc), "productos": [], "total_encontrados": 0}


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
    Panel consolidado para Streamlit: ventas, catálogo y salud de canales.

    Siempre responde JSON con ``ok: true`` y la clave ``canales`` (WhatsApp, Vapi, MCP),
    aunque PocketBase o el catálogo no estén disponibles.
    """
    checked_at = datetime.now(timezone.utc).isoformat()

    canales_task = asyncio.create_task(_channel_health())
    ventas_task = asyncio.create_task(_safe_ventas(ventas_limit))
    catalog_task = asyncio.create_task(_safe_catalog(catalog_query))

    canales, ventas, catalog = await asyncio.gather(canales_task, ventas_task, catalog_task)

    catalog_summary = catalog.get("resumen_catalogo")
    if not catalog_summary:
        try:
            from app.agents.catalog_bridge_agent import get_catalog_bridge

            catalog_summary = get_catalog_bridge().get_catalog_summary()
        except Exception as exc:
            logger.debug("Catalog summary fallback: %s", exc)
            catalog_summary = {}

    productos = catalog.get("productos") or []
    total_muestra = catalog.get("total_encontrados", len(productos))

    return {
        "ok": True,
        "platform": "ED NET PRO",
        "version": "3.0.0",
        "checked_at": checked_at,
        "env": settings.ENV,
        "ventas": ventas,
        "catalogo": {
            "muestra": productos[:5],
            "total_muestra": total_muestra,
            "summary": catalog_summary,
        },
        "canales": canales,
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
