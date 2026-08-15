"""
app/routers/whatsapp_handler.py
────────────────────────────────────────────────────────────────────────────────
Webhook WhatsApp (Evolution API) — endpoint dedicado /webhook/whatsapp.

Flujo:
  Evolution POST → extrae remoteJid + texto → IA (catálogo/ventas vía MCP tools)
  → enviar_mensaje_evolution (httpx async)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request

from app.config import settings
from app.security import verify_evolution_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WhatsApp Webhook"])

_INVENTORY_HINTS = (
    "precio", "precios", "inventario", "catálogo", "catalogo", "producto",
    "productos", "tienen", "stock", "enterizo", "enterizos", "vestido",
    "jumpsuit", "unitard", "mono", "disponible", "cuánto", "cuanto",
)
_SALES_HINTS = (
    "venta", "ventas", "vendimos", "ingreso", "ingresos", "ticket",
    "facturación", "facturacion", "cierre", "cierres",
)


def _evolution_config() -> tuple[str, str, str]:
    url = (os.getenv("EVOLUTION_API_URL") or settings.EVOLUTION_API_URL or "").rstrip("/")
    instance = os.getenv("EVOLUTION_INSTANCE") or settings.EVOLUTION_INSTANCE or "super_vendedor"
    api_key = os.getenv("EVOLUTION_API_KEY") or settings.EVOLUTION_API_KEY or ""
    return url, instance, api_key


async def enviar_mensaje_evolution(numero_o_jid: str, texto: str) -> bool:
    """
    Envía texto al cliente vía Evolution API (POST /message/sendText/{instance}).

    Usa httpx async. No lanza excepción si Evolution falla — devuelve False.
    """
    if not texto.strip():
        return False

    base_url, instance, api_key = _evolution_config()
    numero = numero_o_jid.split("@")[0].replace("+", "").strip()

    if not base_url or not api_key:
        logger.warning("[Evolution] EVOLUTION_API_URL o EVOLUTION_API_KEY no configurados — mock")
        logger.info("[Evolution MOCK] → %s: %s", numero, texto[:120])
        return True

    endpoint = f"{base_url}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": numero, "text": texto}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
        ok = response.status_code < 400
        if ok:
            logger.info("[Evolution] → %s | HTTP %s", numero, response.status_code)
        else:
            logger.warning(
                "[Evolution] fallo → %s | HTTP %s %s",
                numero,
                response.status_code,
                response.text[:200],
            )
        return ok
    except Exception as exc:
        logger.exception("[Evolution] error enviando a %s: %s", numero, exc)
        return False


def _extract_message_text(msg_data: dict[str, Any]) -> str:
    """Extrae texto del payload Evolution (conversation, extendedText, etc.)."""
    message = msg_data.get("message") or {}
    text = message.get("conversation")
    if text:
        return str(text).strip()

    extended = message.get("extendedTextMessage") or {}
    if extended.get("text"):
        return str(extended["text"]).strip()

    image = message.get("imageMessage") or {}
    if image.get("caption"):
        return str(image["caption"]).strip()

    buttons = message.get("buttonsResponseMessage") or {}
    if buttons.get("selectedDisplayText"):
        return str(buttons["selectedDisplayText"]).strip()

    list_resp = message.get("listResponseMessage") or {}
    single = list_resp.get("singleSelectReply") or {}
    if single.get("title"):
        return str(single["title"]).strip()

    return ""


def _extract_inventory_query(mensaje: str) -> str:
    """Deriva keyword de búsqueda de catálogo desde el mensaje del cliente."""
    lower = mensaje.lower()
    for prefix in ("busca ", "buscar ", "tienen ", "precio de ", "precio del ", "cuánto cuesta "):
        if lower.startswith(prefix):
            return mensaje[len(prefix):].strip() or mensaje.strip()

    tokens = re.findall(r"[a-záéíóúüñ0-9]+", lower)
    stop = {
        "el", "la", "los", "las", "un", "una", "de", "del", "en", "y", "o",
        "precio", "precios", "tienen", "hay", "busca", "buscar", "quiero",
        "necesito", "cuanto", "cuánto", "cuesta", "inventario", "catalogo",
        "catálogo", "producto", "productos", "disponible", "disponibilidad",
    }
    keywords = [t for t in tokens if t not in stop and len(t) > 2]
    return " ".join(keywords[:4]) if keywords else mensaje.strip()


def _format_inventario(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return (
            "⚠️ No pude consultar el inventario en este momento. "
            f"{result.get('error', 'Intenta de nuevo en unos minutos.')}"
        )

    productos = result.get("productos") or []
    if not productos:
        aviso = result.get("aviso") or "No encontré coincidencias en el catálogo."
        return f"📦 {aviso}"

    lines = ["📦 *Inventario ED NET PRO*\n"]
    for p in productos[:5]:
        titulo = str(p.get("titulo", "Producto"))[:80]
        reventa = float(p.get("precio_reventa_cop") or p.get("precio_cop") or 0)
        lines.append(f"• *{titulo}*")
        lines.append(f"  💰 Reventa: ${reventa:,.0f} COP")
        reserve = p.get("reserve_price")
        target = p.get("target_price")
        if reserve and target:
            lines.append(f"  🤝 Negociación: ${float(reserve):,.0f} – ${float(target):,.0f} COP")
        stock = p.get("stock_estimado", "consultar")
        lines.append(f"  ✅ Disponibilidad: {stock}")
        lines.append("")

    total = result.get("total_encontrados", len(productos))
    if total > 5:
        lines.append(f"_…y {total - 5} producto(s) más en catálogo._")
    return "\n".join(lines).strip()


def _format_ventas(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"⚠️ No pude consultar ventas: {result.get('error', 'error desconocido')}"

    n = int(result.get("total_registros") or 0)
    ingresos = float(result.get("ingresos_totales_cop") or 0)
    ticket = float(result.get("ticket_promedio_cop") or 0)

    if n == 0:
        return "📊 Aún no hay ventas registradas en el sistema."

    lines = [
        "📊 *Resumen de ventas ED NET PRO*",
        f"• Registros: {n}",
        f"• Ingresos: ${ingresos:,.0f} COP",
        f"• Ticket promedio: ${ticket:,.0f} COP",
        "",
        "*Últimas ventas:*",
    ]
    for v in (result.get("ventas") or [])[:5]:
        prod = v.get("producto", "—")
        monto = float(v.get("monto") or 0)
        estado = v.get("estado", "—")
        lines.append(f"• {prod} — ${monto:,.0f} COP ({estado})")
    return "\n".join(lines)


def _procesar_mensaje_sync(mensaje: str, telefono: str) -> str:
    """
    Procesa el mensaje con herramientas MCP (catálogo/ventas) + pipeline de ventas.
    Ejecutar en thread pool desde el handler async.
    """
    lower = mensaje.lower()

    try:
        import servidor_ventas as mcp_tools
    except ImportError:
        mcp_tools = None
        logger.warning("servidor_ventas no disponible — solo pipeline local")

    if any(h in lower for h in _SALES_HINTS):
        if mcp_tools:
            result = mcp_tools.call_tool(
                "consultar_ventas_pocketbase",
                {"limit": 10, "producto": _extract_inventory_query(mensaje)},
            )
            return _format_ventas(result)

    if any(h in lower for h in _INVENTORY_HINTS):
        query = _extract_inventory_query(mensaje)
        if mcp_tools:
            result = mcp_tools.call_tool(
                "buscar_productos_inventario",
                {"query": query, "limit": 5},
            )
            return _format_inventario(result)

    from app.sales_pipeline import negotiate_response

    return negotiate_response(mensaje)


async def procesar_mensaje_ia(mensaje: str, telefono: str) -> str:
    """Wrapper async — delega la lógica MCP/IA a un thread."""
    return await asyncio.to_thread(_procesar_mensaje_sync, mensaje, telefono)


async def _handle_incoming_message(
    remote_jid: str,
    mensaje: str,
    event_id: Optional[str],
) -> None:
    try:
        respuesta = await procesar_mensaje_ia(mensaje, remote_jid)
        if respuesta:
            await enviar_mensaje_evolution(remote_jid, respuesta)
    except Exception:
        logger.exception("[WhatsApp] Error procesando mensaje de %s", remote_jid)
    finally:
        if event_id:
            from app.services.processed_events import mark_processed
            mark_processed("whatsapp", event_id)


@router.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe eventos de Evolution API (messages.upsert).

    Responde 200 de inmediato y procesa IA + respuesta en background.
    """
    verify_evolution_webhook(request)

    try:
        data = await request.json()
    except json.JSONDecodeError:
        logger.warning("[WhatsApp] Payload JSON inválido")
        return {"status": "ok", "ignored": "invalid_json"}

    from app.services.processed_events import (
        extract_whatsapp_event_id,
        is_processed,
    )

    event_id = extract_whatsapp_event_id(data)
    if event_id and is_processed("whatsapp", event_id):
        return {"status": "ok", "duplicate": True}

    if data.get("event") != "messages.upsert":
        return {"status": "ok", "ignored": data.get("event")}

    msg_data = data.get("data") or {}
    key = msg_data.get("key") or {}
    remote_jid = key.get("remoteJid", "")
    from_me = key.get("fromMe", False)

    if from_me or not remote_jid:
        return {"status": "ok", "ignored": "from_me_or_empty_jid"}

    if remote_jid.endswith("@g.us"):
        return {"status": "ok", "ignored": "group_message"}

    user_message = _extract_message_text(msg_data)
    if not user_message:
        return {"status": "ok", "ignored": "no_text"}

    telefono = remote_jid.split("@")[0]
    logger.info("[WhatsApp] Mensaje de %s: %r", telefono, user_message[:80])

    background_tasks.add_task(_handle_incoming_message, remote_jid, user_message, event_id)

    return {"status": "ok", "queued": True}
