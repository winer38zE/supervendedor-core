"""
app/services/vapi_tools_service.py
────────────────────────────────────────────────────────────────────────────────
Ejecución de tools Vapi → backend ED NET PRO (inventario + ventas vía MCP/FastAPI).

Formato respuesta Vapi:
  { "results": [ { "toolCallId": "...", "result": "texto para el asistente" } ] }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

<<<<<<< HEAD
# ── Definiciones OpenAI-style para assistant-request ─────────────────────────
=======
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2

def _tool_server_url(path: str = "/vapi/tools/webhook") -> Optional[str]:
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    return f"{base}{path}" if base else None


def get_vapi_tool_definitions(*, include_agenda: bool = True) -> list[dict[str, Any]]:
    """Tools registrables en assistant-request de Vapi."""
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "buscar_productos_inventario",
                "description": (
                    "Consulta inventario, precios COP y disponibilidad del catálogo Shein/Nyx Bridge. "
                    "Usar cuando el cliente pregunte por productos, precios, stock, enterizos, vestidos, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Palabra clave o nombre del producto a buscar.",
                        },
                        "categoria": {
                            "type": "string",
                            "description": "Filtro opcional de categoría.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de productos a devolver (1-10).",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_ventas_pocketbase",
                "description": (
                    "Consulta ventas cerradas, ingresos totales y ticket promedio desde PocketBase. "
                    "Usar cuando pregunten cuánto se vendió, últimas ventas o métricas comerciales."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Cantidad de ventas recientes (1-20).",
                            "default": 5,
                        },
                        "estado": {
                            "type": "string",
                            "description": "Filtrar por estado, ej. Cerrado.",
                        },
                        "producto": {
                            "type": "string",
                            "description": "Filtrar por nombre de producto.",
                        },
                    },
                },
            },
        },
    ]

    if include_agenda:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "agendar_cita",
                    "description": (
                        "Agenda una cita cuando el cliente confirme nombre, fecha y hora."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nombre": {"type": "string", "description": "Nombre del cliente."},
                            "fecha": {"type": "string", "description": "Fecha de la cita."},
                            "hora": {"type": "string", "description": "Hora de la cita."},
                        },
                        "required": ["nombre", "fecha", "hora"],
                    },
                },
            }
        )

    server_url = _tool_server_url()
    if server_url:
        for tool in tools:
            tool["server"] = {"url": server_url}

    return tools


<<<<<<< HEAD
# ── Parsing tool-calls (formatos Vapi v1/v2) ─────────────────────────────────

def parse_tool_call(tool_call: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """
    Normaliza un tool call de Vapi.

    Soporta:
      - toolCallList[].function.name + function.arguments (string JSON)
      - toolCallList[].name + parameters / arguments (dict)
    """
    tool_id = str(tool_call.get("id") or tool_call.get("toolCallId") or "")

    function = tool_call.get("function") or {}
    tool_name = (
        function.get("name")
        or tool_call.get("name")
        or ""
    ).strip()
=======
def parse_tool_call(tool_call: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Normaliza un tool call de Vapi (formatos function.* y name/parameters)."""
    tool_id = str(tool_call.get("id") or tool_call.get("toolCallId") or "")

    function = tool_call.get("function") or {}
    tool_name = (function.get("name") or tool_call.get("name") or "").strip()
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2

    raw_args = (
        function.get("arguments")
        if function.get("arguments") is not None
        else tool_call.get("parameters", tool_call.get("arguments", {}))
    )

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}

    return tool_id, tool_name, args


def extract_tool_call_list(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae lista de tool calls del mensaje Vapi."""
    msg_type = message.get("type", "")
    if msg_type == "tool-calls":
        return list(message.get("toolCallList") or [])
    if msg_type == "tool-call":
        single = message.get("toolCall") or {}
        if single:
            return [single]
        lst = message.get("toolCallList") or []
        return [lst[0]] if lst else []
    return []


<<<<<<< HEAD
# ── Backend (MCP tools / FastAPI / PocketBase) ────────────────────────────────

def _invoke_backend_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        import servidor_ventas as mcp_tools

        return mcp_tools.call_tool(tool_name, arguments)
    except Exception as exc:
        logger.exception("[VapiTools] Error invocando %s", tool_name)
        return {"ok": False, "error": str(exc)}
=======
def _invoke_backend_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.platform_tools_service import call_tool_sync

    return call_tool_sync(tool_name, arguments)
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2


def _format_inventario_voz(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return (
            "No pude consultar el inventario en este momento. "
            f"{result.get('error', 'Intenta de nuevo más tarde.')}"
        )

    productos = result.get("productos") or []
    if not productos:
        return result.get("aviso") or "No encontré productos con esa búsqueda en el catálogo."

    partes = [f"Encontré {len(productos)} producto(s) en inventario."]
    for i, p in enumerate(productos[:3], start=1):
        titulo = str(p.get("titulo", "Producto"))[:70]
        precio = float(p.get("precio_reventa_cop") or p.get("precio_cop") or 0)
        stock = p.get("stock_estimado", "consultar")
        partes.append(
            f"Opción {i}: {titulo}. Precio de reventa {precio:,.0f} pesos colombianos. "
            f"Disponibilidad: {stock}."
        )
    if len(productos) > 3:
        partes.append(f"Hay {len(productos) - 3} productos adicionales en catálogo.")
    return " ".join(partes)


def _format_ventas_voz(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"No pude consultar las ventas. {result.get('error', '')}".strip()

    n = int(result.get("total_registros") or 0)
    if n == 0:
        return "Aún no hay ventas registradas en el sistema."

    ingresos = float(result.get("ingresos_totales_cop") or 0)
    ticket = float(result.get("ticket_promedio_cop") or 0)
    partes = [
        f"Hay {n} ventas registradas.",
        f"Ingresos totales: {ingresos:,.0f} pesos colombianos.",
        f"Ticket promedio: {ticket:,.0f} pesos.",
    ]
    ultimas = result.get("ventas") or []
    if ultimas:
        v = ultimas[0]
        partes.append(
            f"La venta más reciente: {v.get('producto', 'producto')} "
            f"por {float(v.get('monto') or 0):,.0f} pesos, estado {v.get('estado', '—')}."
        )
    return " ".join(partes)


def execute_tool(tool_name: str, args: dict[str, Any], *, client_id: str = "default") -> str:
<<<<<<< HEAD
    """
    Ejecuta una tool y devuelve texto listo para que Vapi lo lea al usuario.
    """
=======
    """Ejecuta una tool y devuelve texto listo para que Vapi lo lea al usuario."""
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2
    logger.info("[VapiTools] execute tool=%r client=%r args=%s", tool_name, client_id, args)

    if tool_name == "buscar_productos_inventario":
        query = str(args.get("query", "")).strip()
        if not query:
            return "Necesito saber qué producto buscar. Por ejemplo: enterizos, vestidos o jumpsuit."
        result = _invoke_backend_tool(
            "buscar_productos_inventario",
            {
                "query": query,
                "categoria": str(args.get("categoria", "")),
                "limit": int(args.get("limit", 5)),
            },
        )
        return _format_inventario_voz(result)

    if tool_name == "consultar_ventas_pocketbase":
        result = _invoke_backend_tool(
            "consultar_ventas_pocketbase",
            {
                "limit": int(args.get("limit", 5)),
                "estado": str(args.get("estado", "")),
                "producto": str(args.get("producto", "")),
            },
        )
        return _format_ventas_voz(result)

    if tool_name == "agendar_cita":
        from app.routers.vapi_handler import handle_agendar_cita

        return handle_agendar_cita(args, client_id)

    return f"La herramienta '{tool_name}' no está disponible."


def build_vapi_tool_results(
    tool_call_list: list[dict[str, Any]],
    *,
    client_id: str = "default",
) -> list[dict[str, str]]:
    """Construye array `results` compatible con Vapi."""
    results: list[dict[str, str]] = []
    for tool_call in tool_call_list:
        tool_id, tool_name, args = parse_tool_call(tool_call)
        try:
            result_text = execute_tool(tool_name, args, client_id=client_id)
<<<<<<< HEAD
        except Exception as exc:
=======
        except Exception:
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2
            logger.exception("[VapiTools] fallo tool=%s", tool_name)
            result_text = f"Ocurrió un error ejecutando {tool_name}. Intenta de nuevo."
        results.append({"toolCallId": tool_id, "result": result_text})
    return results


async def build_vapi_tool_results_async(
    tool_call_list: list[dict[str, Any]],
    *,
    client_id: str = "default",
) -> list[dict[str, str]]:
    """Wrapper async — ejecuta tools en thread pool."""
    return await asyncio.to_thread(
        build_vapi_tool_results,
        tool_call_list,
        client_id=client_id,
    )
<<<<<<< HEAD


def vapi_tools_response(
    tool_call_list: list[dict[str, Any]],
    *,
    client_id: str = "default",
) -> dict[str, Any]:
    """Respuesta JSON final para POST tool-calls."""
    return {
        "results": build_vapi_tool_results(tool_call_list, client_id=client_id),
    }
=======
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2
