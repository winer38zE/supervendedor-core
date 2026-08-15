"""
app/routers/whatsapp_handler.py — Webhook WhatsApp Evolution + routing inventario/ventas vía MCP.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Request

from app.config import settings
from app.security import verify_evolution_webhook

logger = logging.getLogger(__name__)

router = APIRouter()

_KEYWORDS_INVENTARIO = {
    "producto",
    "productos",
    "inventario",
    "precio",
    "precios",
    "stock",
    "catalogo",
    "catálogo",
    "enterizo",
    "enterizos",
    "vestido",
    "vestidos",
    "jumpsuit",
    "disponible",
    "disponibilidad",
    "cuanto",
    "cuánto",
    "cuesta",
    "reventa",
    "shein",
    "talla",
    "modelo",
}

_KEYWORDS_VENTAS = {
    "venta",
    "ventas",
    "vendido",
    "vendimos",
    "ingreso",
    "ingresos",
    "facturacion",
    "facturación",
    "ticket",
    "cierre",
    "cerrado",
    "metricas",
    "métricas",
    "reporte",
    "comercial",
}


async def enviar_mensaje_evolution(remote_jid: str, text: str) -> bool:
    """Envía texto vía Evolution API (async httpx)."""
    numero = remote_jid.split("@")[0].replace("+", "").strip()
    url = settings.EVOLUTION_API_URL
    api_key = settings.EVOLUTION_API_KEY
    instance = settings.EVOLUTION_INSTANCE

    if not url or not api_key:
        logger.info("[WhatsApp MOCK] → %s: %s", numero, text[:120])
        return True

    endpoint = f"{url.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": numero, "text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
        logger.info("[WhatsApp] → %s | HTTP %s", numero, response.status_code)
        return response.status_code < 400
    except Exception as exc:
        logger.error("[WhatsApp ERROR] %s", exc)
        return False


def _normalize_words(message: str) -> set[str]:
    normalized = (
        message.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    return set(normalized.split())


def _detect_route(message: str) -> str | None:
    """Devuelve 'inventario', 'ventas' o None según palabras clave."""
    words = _normalize_words(message)
    if words & _KEYWORDS_VENTAS:
        return "ventas"
    if words & _KEYWORDS_INVENTARIO:
        return "inventario"
    return None


def _format_inventario(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"No pude consultar el inventario. {result.get('error', '')}".strip()

    productos = result.get("productos") or []
    if not productos:
        return result.get("aviso") or "No encontré productos con esa búsqueda."

    lines = [f"Encontré {len(productos)} producto(s):"]
    for index, producto in enumerate(productos[:5], start=1):
        titulo = str(producto.get("titulo", "Producto"))[:70]
        precio = float(producto.get("precio_reventa_cop") or producto.get("precio_cop") or 0)
        stock = producto.get("stock_estimado", "consultar")
        lines.append(f"{index}. *{titulo}* — ${precio:,.0f} COP | Stock: {stock}")
    return "\n".join(lines)


def _format_ventas(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"No pude consultar las ventas. {result.get('error', '')}".strip()

    total = int(result.get("total_registros") or 0)
    if total == 0:
        return "Aún no hay ventas registradas en el sistema."

    ingresos = float(result.get("ingresos_totales_cop") or 0)
    ticket = float(result.get("ticket_promedio_cop") or 0)
    lines = [
        f"*Reporte de ventas* ({total} registros)",
        f"Ingresos totales: ${ingresos:,.0f} COP",
        f"Ticket promedio: ${ticket:,.0f} COP",
    ]
    for venta in (result.get("ventas") or [])[:3]:
        lines.append(
            f"• {venta.get('producto', '—')} — "
            f"${float(venta.get('monto') or 0):,.0f} ({venta.get('estado', '—')})"
        )
    return "\n".join(lines)


def procesar_mensaje_ia(user_message: str) -> str | None:
    """Routing inventario/ventas vía platform_tools_service."""
    from app.services.platform_tools_service import call_tool_sync

    route = _detect_route(user_message)
    if route == "inventario":
        result = call_tool_sync(
            "buscar_productos_inventario",
            {"query": user_message.strip(), "limit": 5},
        )
        return _format_inventario(result)

    if route == "ventas":
        result = call_tool_sync(
            "consultar_ventas_pocketbase",
            {"limit": 5},
        )
        return _format_ventas(result)

    return None


async def _process_incoming(
    remote_jid: str,
    user_message: str,
    event_id: str | None,
) -> None:
    from app.services.processed_events import mark_processed

    try:
        response = procesar_mensaje_ia(user_message)
        if response:
            await enviar_mensaje_evolution(remote_jid, response)
    except Exception as exc:
        logger.exception("[WhatsApp] Error procesando mensaje: %s", exc)
    finally:
        if event_id:
            mark_processed("whatsapp", event_id)


@router.post("/webhook/whatsapp")
async def handle_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    verify_evolution_webhook(request)

    data = await request.json()

    from app.services.processed_events import extract_whatsapp_event_id, is_processed

    event_id = extract_whatsapp_event_id(data)
    if event_id and is_processed("whatsapp", event_id):
        return {"status": "ok", "duplicate": True}

    if data.get("event") == "messages.upsert":
        msg_data = data.get("data", {})
        remote_jid = msg_data.get("key", {}).get("remoteJid", "")
        from_me = msg_data.get("key", {}).get("fromMe", False)
        user_message = (
            msg_data.get("message", {}).get("conversation")
            or msg_data.get("message", {}).get("extendedTextMessage", {}).get("text")
        )

        if user_message and not from_me and remote_jid:
            route = _detect_route(user_message)
            if route:
                background_tasks.add_task(
                    _process_incoming,
                    remote_jid,
                    user_message,
                    event_id,
                )
                return {"status": "ok", "routed": route}

    if event_id:
        from app.services.processed_events import mark_processed

        mark_processed("whatsapp", event_id)

    return {"status": "ok"}
