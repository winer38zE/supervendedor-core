"""
app/services/platform_tools_service.py
────────────────────────────────────────────────────────────────────────────────
Capa unificada de tools ED NET PRO 3.0 — inventario (FastAPI) + ventas (PocketBase).

Consumida por:
  - servidor_ventas.py (MCP stdio)
  - app/services/vapi_tools_service.py (Vapi)
  - app/routers/whatsapp_handler.py (Evolution API)
  - app/routers/metrics_router.py (métricas de negocio)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_TOOLS = frozenset({"buscar_productos_inventario", "consultar_ventas_pocketbase"})


def _fastapi_base() -> str:
    return (
        settings.SUPERVENDEDOR_URL
        or settings.FASTAPI_BASE_URL
        or f"http://127.0.0.1:{settings.PORT}"
    ).rstrip("/")


def _api_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.INTERNAL_API_KEY.strip():
        headers["X-API-Key"] = settings.INTERNAL_API_KEY.strip()
    return headers


def _pb_quote(value: str) -> str:
    return f'"{value.replace(chr(34), chr(92) + chr(34))}"'


def _normalize_product(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("goods_id") or raw.get("id") or ""),
        "titulo": str(raw.get("titulo") or raw.get("nombre") or "Producto"),
        "precio_cop": float(raw.get("precio_cop") or 0),
        "precio_reventa_cop": float(raw.get("precio_reventa") or raw.get("precio_reventa_cop") or 0),
        "target_price": raw.get("target_price"),
        "reserve_price": raw.get("reserve_price"),
        "stock_estimado": raw.get("stock_estimado", "disponible"),
        "url": raw.get("producto_url") or raw.get("imagen_url") or "",
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
        titulo = str(product.get("titulo", product.get("nombre", ""))).lower()
        if cat and cat not in titulo:
            continue
        if tokens and not any(token in titulo for token in tokens):
            continue
        matched.append(_normalize_product(product))

    if not matched and products and not q:
        matched = [_normalize_product(p) for p in products[:limit]]

    return matched[: max(1, min(limit, 50))]


async def _fetch_catalog_zopa(query: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_fastapi_base()}/agents/catalog/zopa",
            params={"q": query},
            headers=_api_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _fetch_catalog_snapshot() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_fastapi_base()}/agents/catalog/snapshot",
            headers=_api_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _pb_auth_token() -> str | None:
    email = settings.POCKETBASE_EMAIL.strip()
    password = settings.POCKETBASE_PASSWORD.strip()
    if not email or not password:
        return None

    base = settings.POCKETBASE_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        for path in (
            "/api/collections/_superusers/auth-with-password",
            "/api/admins/auth-with-password",
        ):
            try:
                response = await client.post(
                    f"{base}{path}",
                    json={"identity": email, "password": password},
                )
                if response.status_code == 200:
                    return response.json().get("token")
            except httpx.HTTPError:
                continue
    return None


async def buscar_productos_inventario(
    query: str,
    *,
    categoria: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Inventario real vía FastAPI /agents/catalog/*."""
    try:
        zopa_data = await _fetch_catalog_zopa(query)
        product = zopa_data.get("product")
        if product:
            item = _normalize_product(product)
            zopa = zopa_data.get("zopa") or {}
            item["target_price"] = zopa.get("target_price")
            item["reserve_price"] = zopa.get("reserve_price")
            return {
                "ok": True,
                "fuente": "fastapi",
                "api_base": _fastapi_base(),
                "productos": [item],
                "zopa": zopa,
            }

        snapshot = await _fetch_catalog_snapshot()
        products = snapshot.get("products") or []
        filtered = _filter_products(products, query, categoria, limit)
        if not filtered:
            return {
                "ok": True,
                "fuente": "fastapi",
                "productos": [],
                "aviso": f"No encontré productos con '{query}' en el catálogo.",
            }

        return {
            "ok": True,
            "fuente": "fastapi",
            "api_base": _fastapi_base(),
            "productos": filtered,
            "total_encontrados": len(filtered),
            "resumen_catalogo": snapshot.get("summary"),
        }
    except Exception as exc:
        logger.exception("[PlatformTools] buscar_productos_inventario")
        return {"ok": False, "error": str(exc)}


async def consultar_ventas_pocketbase(
    *,
    limit: int = 5,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    """Ventas reales desde PocketBase."""
    try:
        token = await _pb_auth_token()
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = token

        filters: list[str] = []
        if estado.strip():
            filters.append(f"estado={_pb_quote(estado.strip())}")
        if producto.strip():
            filters.append(f"producto~{_pb_quote(producto.strip())}")

        base_path = (
            f"{settings.POCKETBASE_URL.rstrip('/')}"
            f"/api/collections/{settings.VENTAS_COLLECTION}/records"
        )
        per_page = max(1, min(limit, 100))

        param_variants: list[dict[str, Any]] = [
            {"page": 1, "perPage": per_page, "sort": "-created"},
            {"page": 1, "perPage": per_page, "sort": "-@created"},
            {"page": 1, "perPage": per_page},
        ]

        body: dict[str, Any] | None = None
        for params in param_variants:
            if filters:
                params = {**params, "filter": "&&".join(filters)}
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(base_path, params=params, headers=headers)
            if response.status_code == 404:
                return {
                    "ok": True,
                    "fuente": "pocketbase",
                    "total_registros": 0,
                    "ventas": [],
                    "ingresos_totales_cop": 0,
                    "ticket_promedio_cop": 0,
                }
            if response.status_code == 200:
                body = response.json()
                break
            if response.status_code not in (400, 422):
                response.raise_for_status()

        if body is None:
            return {"ok": False, "error": "No se pudo leer ventas desde PocketBase"}

        items = body.get("items") or []
        ventas = [
            {
                "id": item.get("id"),
                "cliente": item.get("cliente", ""),
                "producto": item.get("producto", ""),
                "monto": float(item.get("monto") or 0),
                "estado": item.get("estado", ""),
            }
            for item in items
        ]
        montos = [v["monto"] for v in ventas if v["monto"] > 0]
        ingresos = sum(montos)
        ticket = ingresos / len(montos) if montos else 0

        return {
            "ok": True,
            "fuente": "pocketbase",
            "coleccion": settings.VENTAS_COLLECTION,
            "total_registros": len(ventas),
            "ventas": ventas,
            "ingresos_totales_cop": round(ingresos, 2),
            "ticket_promedio_cop": round(ticket, 2),
        }
    except Exception as exc:
        logger.exception("[PlatformTools] consultar_ventas_pocketbase")
        return {"ok": False, "error": str(exc)}


def _run_async(coro: Any) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def call_tool_async(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatcher async — preferido en handlers FastAPI."""
    args = arguments or {}

    if tool_name == "buscar_productos_inventario":
        return await buscar_productos_inventario(
            str(args.get("query", "")),
            categoria=str(args.get("categoria", "")),
            limit=int(args.get("limit", 5)),
        )

    if tool_name == "consultar_ventas_pocketbase":
        return await consultar_ventas_pocketbase(
            limit=int(args.get("limit", 5)),
            estado=str(args.get("estado", "")),
            producto=str(args.get("producto", "")),
        )

    return {"ok": False, "error": f"Herramienta desconocida: {tool_name}"}


def call_tool_sync(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatcher síncrono — MCP, Vapi thread pool, scripts."""
    return _run_async(call_tool_async(tool_name, arguments))
