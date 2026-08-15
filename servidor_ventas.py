"""
servidor_ventas.py — MCP server + call_tool dispatcher (inventario + ventas PocketBase).

Tools expuestas vía @mcp.tool y dispatcher síncrono `call_tool` para Vapi/WhatsApp.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any

import httpx
from mcp.server import MCPServer

logger = logging.getLogger(__name__)

mcp = MCPServer("Servidor Ventas ED NET PRO")

FASTAPI_BASE = os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
POCKETBASE_URL = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")
VENTAS_COLLECTION = os.getenv("VENTAS_COLLECTION", "ventas").strip() or "ventas"
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def _api_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if INTERNAL_API_KEY.strip():
        headers["X-API-Key"] = INTERNAL_API_KEY.strip()
    return headers


def _pb_quote(value: str) -> str:
    return f'"{value.replace(chr(34), chr(92) + chr(34))}"'


def _normalize_product(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": raw.get("titulo", "Producto"),
        "precio_cop": float(raw.get("precio_cop") or 0),
        "precio_reventa_cop": float(raw.get("precio_reventa") or raw.get("precio_reventa_cop") or 0),
        "stock_estimado": raw.get("stock_estimado", "disponible"),
        "imagen_url": raw.get("imagen_url", ""),
        "goods_id": raw.get("goods_id", ""),
    }


def _filter_products(
    products: list[dict[str, Any]],
    query: str,
    categoria: str,
    limit: int,
) -> list[dict[str, Any]]:
    q = query.lower().strip()
    cat = categoria.lower().strip()
    tokens = [t for t in q.split() if len(t) > 2]

    matched: list[dict[str, Any]] = []
    for product in products:
        titulo = str(product.get("titulo", "")).lower()
        if cat and cat not in titulo:
            continue
        if tokens and not any(token in titulo for token in tokens):
            continue
        matched.append(_normalize_product(product))

    if not matched and products:
        matched = [_normalize_product(p) for p in products[:limit]]

    return matched[: max(1, min(limit, 10))]


async def _fetch_catalog_zopa(query: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{FASTAPI_BASE}/agents/catalog/zopa",
            params={"q": query},
            headers=_api_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _fetch_catalog_snapshot() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{FASTAPI_BASE}/agents/catalog/snapshot",
            headers=_api_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _pb_auth_token() -> str | None:
    email = os.getenv("POCKETBASE_EMAIL", os.getenv("PB_ADMIN_EMAIL", "")).strip()
    password = os.getenv("POCKETBASE_PASSWORD", os.getenv("PB_ADMIN_PASSWORD", "")).strip()
    if not email or not password:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        for path in (
            "/api/collections/_superusers/auth-with-password",
            "/api/admins/auth-with-password",
        ):
            try:
                response = await client.post(
                    f"{POCKETBASE_URL}{path}",
                    json={"identity": email, "password": password},
                )
                if response.status_code == 200:
                    return response.json().get("token")
            except httpx.HTTPError:
                continue
    return None


async def buscar_productos_inventario_impl(
    query: str,
    categoria: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    try:
        zopa_data = await _fetch_catalog_zopa(query)
        product = zopa_data.get("product")
        if product:
            return {
                "ok": True,
                "productos": [_normalize_product(product)],
                "zopa": zopa_data.get("zopa"),
            }

        snapshot = await _fetch_catalog_snapshot()
        products = snapshot.get("products") or []
        filtered = _filter_products(products, query, categoria, limit)
        if not filtered:
            return {
                "ok": True,
                "productos": [],
                "aviso": f"No encontré productos con '{query}' en el catálogo.",
            }

        return {"ok": True, "productos": filtered, "summary": snapshot.get("summary")}
    except Exception as exc:
        logger.exception("[servidor_ventas] buscar_productos_inventario")
        return {"ok": False, "error": str(exc)}


async def consultar_ventas_pocketbase_impl(
    limit: int = 5,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    try:
        token = await _pb_auth_token()
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = token

        filters: list[str] = []
        if estado.strip():
            filters.append(f"estado={_pb_quote(estado.strip())}")
        if producto.strip():
            filters.append(f"producto~{_pb_quote(producto.strip())}")

        params: dict[str, Any] = {
            "page": 1,
            "perPage": max(1, min(limit, 20)),
            "sort": "-created",
        }
        if filters:
            params["filter"] = "&&".join(filters)

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{POCKETBASE_URL}/api/collections/{VENTAS_COLLECTION}/records",
                params=params,
                headers=headers,
            )
            if response.status_code == 404:
                return {
                    "ok": True,
                    "total_registros": 0,
                    "ventas": [],
                    "ingresos_totales_cop": 0,
                    "ticket_promedio_cop": 0,
                }
            response.raise_for_status()
            body = response.json()

        items = body.get("items") or []
        ventas = [
            {
                "cliente": item.get("cliente", ""),
                "producto": item.get("producto", ""),
                "monto": float(item.get("monto") or 0),
                "estado": item.get("estado", ""),
            }
            for item in items
        ]
        montos = [venta["monto"] for venta in ventas if venta["monto"] > 0]
        ingresos = sum(montos)
        ticket = ingresos / len(montos) if montos else 0

        return {
            "ok": True,
            "total_registros": len(ventas),
            "ventas": ventas,
            "ingresos_totales_cop": ingresos,
            "ticket_promedio_cop": ticket,
        }
    except Exception as exc:
        logger.exception("[servidor_ventas] consultar_ventas_pocketbase")
        return {"ok": False, "error": str(exc)}


@mcp.tool()
async def buscar_productos_inventario(
    query: str,
    categoria: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Consulta inventario, precios COP y disponibilidad del catálogo Shein/Nyx Bridge."""
    return await buscar_productos_inventario_impl(query, categoria, limit)


@mcp.tool()
async def consultar_ventas_pocketbase(
    limit: int = 5,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    """Consulta ventas cerradas, ingresos totales y ticket promedio desde PocketBase."""
    return await consultar_ventas_pocketbase_impl(limit, estado, producto)


def _run_async(coro: Any) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def call_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatcher síncrono usado por Vapi y el webhook WhatsApp."""
    args = arguments or {}

    if tool_name == "buscar_productos_inventario":
        return _run_async(
            buscar_productos_inventario_impl(
                str(args.get("query", "")),
                str(args.get("categoria", "")),
                int(args.get("limit", 5)),
            )
        )

    if tool_name == "consultar_ventas_pocketbase":
        return _run_async(
            consultar_ventas_pocketbase_impl(
                int(args.get("limit", 5)),
                str(args.get("estado", "")),
                str(args.get("producto", "")),
            )
        )

    return {"ok": False, "error": f"Herramienta desconocida: {tool_name}"}


if __name__ == "__main__":
    mcp.run()
