"""
admin_panel/api_store.py
────────────────────────────────────────────────────────────────────────────────
Consulta estado en vivo de FastAPI ED NET PRO 3.0 (webhooks WhatsApp/Vapi, MCP).

Prioridad URL API:
  1. st.secrets["API_URL"] (Streamlit Cloud)
  2. API_URL (.env local)
  3. http://178.105.48.103:8000 (VPS ED NET PRO)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import streamlit as st

# Prioriza el secret de la nube; si no existe, usa la IP pública de tu VPS
API_URL = st.secrets.get("API_URL", os.getenv("API_URL", "http://178.105.48.103:8000"))

NoticeLevel = Literal["info", "warning", "none"]

DEFAULT_TIMEOUT = 8.0


def _api_base() -> str:
    return str(API_URL).rstrip("/")


def _public_base() -> str:
    return (os.getenv("PUBLIC_URL") or _api_base()).rstrip("/")


def _api_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = os.getenv("INTERNAL_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _fetch_json(path: str) -> tuple[dict[str, Any] | None, int, str]:
    url = f"{_api_base()}{path}"
    try:
        response = httpx.get(url, headers=_api_headers(), timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            return response.json(), response.status_code, ""
        return None, response.status_code, response.text[:200]
    except httpx.HTTPError as exc:
        return None, 0, str(exc)


def fetch_api_health() -> tuple[bool, str, dict[str, Any]]:
    """GET /health — comprueba si FastAPI responde."""
    data, status, err = _fetch_json("/health")
    if data:
        return True, "FastAPI en línea", data
    if status:
        return False, f"FastAPI respondió HTTP {status}", {}
    return False, f"FastAPI no alcanzable: {err}", {}


def fetch_channels_overview() -> tuple[dict[str, Any], NoticeLevel, str]:
    """
    GET /api/v1/metrics/overview — estado de canales WhatsApp, Vapi y MCP.
    Siempre devuelve dict (posiblemente vacío). Nunca lanza excepción.
    """
    data, status, err = _fetch_json("/api/v1/metrics/overview?ventas_limit=5")
    if data and data.get("ok"):
        return data, "none", ""

    if status == 401:
        return (
            {},
            "warning",
            "FastAPI rechazó la petición (401). Configura INTERNAL_API_KEY en .env del panel.",
        )
    if status:
        return (
            {},
            "warning",
            f"No se pudo leer métricas de canales (HTTP {status}).",
        )
    return (
        {},
        "warning",
        f"API ED NET PRO no disponible en {_api_base()}. Levanta: uvicorn app.main:app --port 8000",
    )


def build_channel_cards(overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza tarjetas de estado para WhatsApp, Vapi y MCP."""
    canales = overview.get("canales") or {}
    public = _public_base()
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    whatsapp = canales.get("whatsapp_evolution") or {}
    vapi = canales.get("vapi_voice") or {}
    mcp = canales.get("mcp_servidor_ventas") or {}

    wa_webhooks = whatsapp.get("webhooks") or ["/webhook/whatsapp", "/whatsapp/webhook"]
    vapi_webhooks = vapi.get("webhooks") or ["/vapi/webhook", "/vapi/tools/webhook"]

    return [
        {
            "id": "whatsapp",
            "icon": "💬",
            "title": "WhatsApp · Evolution API",
            "status_label": "CONFIGURADO" if whatsapp.get("configured") else "SIN CREDENCIALES",
            "status_ok": bool(whatsapp.get("configured")),
            "instance": whatsapp.get("instance") or os.getenv("EVOLUTION_INSTANCE", "—"),
            "webhooks": [f"{public}{p}" for p in wa_webhooks],
            "module": "app/routers/whatsapp_handler.py",
            "checked_at": now,
        },
        {
            "id": "vapi",
            "icon": "🎙️",
            "title": "Voz · Vapi",
            "status_label": "CONFIGURADO" if vapi.get("configured") else "REVISAR SECRET",
            "status_ok": bool(vapi.get("configured")),
            "instance": "tool-calls inventario + ventas",
            "webhooks": [f"{public}{p}" for p in vapi_webhooks],
            "module": "app/routers/vapi_handler.py + vapi_tools_service",
            "checked_at": now,
        },
        {
            "id": "mcp",
            "icon": "🔌",
            "title": "MCP · Servidor Ventas",
            "status_label": "ACTIVO (stdio)",
            "status_ok": True,
            "instance": mcp.get("entrypoint") or "servidor_ventas.py",
            "webhooks": ["Cursor / Claude Desktop — transporte stdio"],
            "module": "app/services/platform_tools_service.py",
            "checked_at": now,
        },
    ]


def fetch_live_channels_snapshot() -> dict[str, Any]:
    """Snapshot completo para el dashboard Streamlit."""
    api_ok, api_msg, health = fetch_api_health()
    overview, notice_level, notice_msg = fetch_channels_overview()

    cards = build_channel_cards(overview) if overview else build_channel_cards({})

    if not api_ok:
        for card in cards:
            if card["id"] != "mcp":
                card["status_ok"] = False
                card["status_label"] = "API OFFLINE"

    ventas_api = overview.get("ventas") or {}
    catalogo = overview.get("catalogo") or {}

    return {
        "api_ok": api_ok,
        "api_msg": api_msg,
        "api_base": _api_base(),
        "public_base": _public_base(),
        "health": health,
        "overview": overview,
        "cards": cards,
        "ventas_api_total": int(ventas_api.get("total_registros") or 0),
        "ventas_api_ingresos": float(ventas_api.get("ingresos_totales_cop") or 0),
        "catalogo_productos": int(catalogo.get("total_muestra") or 0),
        "notice_level": notice_level if api_ok else "warning",
        "notice_msg": notice_msg if api_ok else api_msg,
        "platform_version": overview.get("version") or health.get("version") or "3.0.0",
    }
