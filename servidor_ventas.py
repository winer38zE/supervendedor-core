#!/usr/bin/env python3
"""
servidor_ventas.py — Servidor MCP (stdio) para Super Vendedor ED NET PRO.

Expone herramientas para que un host MCP (Cursor, Claude Desktop, etc.)
consulte inventario de catálogo y ventas en tiempo real vía HTTP.

Ejecución:
    python servidor_ventas.py

Config Cursor (~/.cursor/mcp.json o .cursor/mcp.json):
    {
      "mcpServers": {
        "super-vendedor": {
          "command": "python",
          "args": ["C:/ruta/al/proyecto/servidor_ventas.py"],
          "env": { "POCKETBASE_URL": "...", "POCKETBASE_EMAIL": "...", ... }
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# ── Path del proyecto (imports app.* solo como fallback) ─────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# ── Logging seguro: SOLO stderr (stdout reservado a JSON-RPC MCP) ─────────────
logger = logging.getLogger("servidor_ventas")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(_handler)
logger.propagate = False

from mcp.server import MCPServer

SERVER_NAME = "super-vendedor-ventas"
mcp = MCPServer(SERVER_NAME)

_pb_token: str | None = None


# ── Config HTTP ───────────────────────────────────────────────────────────────

def _supervendedor_base() -> str:
    return os.getenv("SUPERVENDEDOR_URL", "http://127.0.0.1:8000").rstrip("/")


def _pocketbase_base() -> str:
    return os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")


def _fastapi_headers() -> dict[str, str]:
    api_key = os.getenv("INTERNAL_API_KEY", "")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _pocketbase_credentials() -> tuple[str, str]:
    email = os.getenv("POCKETBASE_EMAIL", os.getenv("PB_ADMIN_EMAIL", ""))
    password = os.getenv("POCKETBASE_PASSWORD", os.getenv("PB_ADMIN_PASSWORD", ""))
    return email, password


def _pocketbase_auth_headers() -> dict[str, str]:
    global _pb_token
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    if _pb_token:
        headers["Authorization"] = _pb_token
        return headers

    email, password = _pocketbase_credentials()
    if not email or not password:
        logger.error("Faltan POCKETBASE_EMAIL / POCKETBASE_PASSWORD en el entorno")
        return headers

    base = _pocketbase_base()
    auth_urls = [
        f"{base}/api/collections/_superusers/auth-with-password",
        f"{base}/api/admins/auth-with-password",
    ]
    for url in auth_urls:
        try:
            response = httpx.post(
                url,
                json={"identity": email, "password": password},
                timeout=15,
            )
            if response.status_code == 200:
                _pb_token = response.json().get("token")
                if _pb_token:
                    headers["Authorization"] = _pb_token
                    logger.info("PocketBase autenticación OK")
                    return headers
        except Exception as exc:
            logger.debug("PocketBase auth %s: %s", url, exc)

    logger.error("No se pudo autenticar en PocketBase")
    return headers


# Rutas de inventario ED NET PRO (FastAPI app.main → agents_router)
INVENTARIO_SNAPSHOT_PATH = "/agents/catalog/snapshot"
INVENTARIO_ZOPA_PATH = "/agents/catalog/zopa"


def _fastapi_get(path: str, *, params: dict[str, Any] | None = None) -> httpx.Response | None:
    url = f"{_supervendedor_base()}{path}"
    try:
        logger.info("HTTP GET %s params=%s", url, params or {})
        response = httpx.get(
            url,
            headers=_fastapi_headers(),
            params=params or {},
            timeout=20,
        )
        logger.info("HTTP GET %s → %s", url, response.status_code)
        return response
    except Exception as exc:
        logger.warning("FastAPI GET %s falló: %s", url, exc)
        return None


def _pocketbase_get(path: str, *, params: dict[str, Any] | None = None) -> httpx.Response | None:
    url = f"{_pocketbase_base()}{path}"
    try:
        response = httpx.get(
            url,
            headers=_pocketbase_auth_headers(),
            params=params or {},
            timeout=20,
        )
        if response.status_code == 401:
            global _pb_token
            _pb_token = None
            response = httpx.get(
                url,
                headers=_pocketbase_auth_headers(),
                params=params or {},
                timeout=20,
            )
        return response
    except Exception as exc:
        logger.warning("PocketBase GET %s falló: %s", path, exc)
        return None


# ── Normalización ─────────────────────────────────────────────────────────────

def _normalize_producto(raw: dict[str, Any]) -> dict[str, Any]:
    precio = float(raw.get("precio_cop") or raw.get("precio_reventa") or 0)
    reventa = float(raw.get("precio_reventa") or precio)
    return {
        "id": str(raw.get("goods_id") or raw.get("id") or ""),
        "titulo": str(raw.get("titulo") or raw.get("nombre") or "Sin título"),
        "precio_cop": round(precio, 2),
        "precio_reventa_cop": round(reventa, 2),
        "target_price": raw.get("target_price"),
        "reserve_price": raw.get("reserve_price"),
        "stock_estimado": "disponible"
        if raw.get("imagen_url") or raw.get("producto_url")
        else "consultar",
        "url": raw.get("producto_url") or raw.get("imagen_url") or "",
    }


def _matches_query(titulo: str, query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    titulo_l = titulo.lower()
    if q in titulo_l:
        return True
    tokens = [t for t in q.split() if len(t) > 2]
    return any(t in titulo_l for t in tokens)


# ── Inventario vía FastAPI (HTTP exclusivo) ───────────────────────────────────

def _parse_fastapi_json(response: httpx.Response, endpoint: str) -> dict[str, Any] | None:
    if response.status_code != 200:
        logger.warning(
            "FastAPI %s → %s %s",
            endpoint,
            response.status_code,
            response.text[:200],
        )
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        logger.warning("FastAPI %s devolvió JSON inválido", endpoint)
        return None


def _merge_productos(
    productos: list[dict[str, Any]],
    raw: dict[str, Any] | None,
    *,
    zopa: dict[str, Any] | None = None,
) -> None:
    """Añade un producto normalizado sin duplicar por id."""
    if not raw:
        return
    item = _normalize_producto(raw)
    if zopa:
        item["target_price"] = zopa.get("target_price", item.get("target_price"))
        item["reserve_price"] = zopa.get("reserve_price", item.get("reserve_price"))
    if any(p["id"] == item["id"] for p in productos):
        return
    productos.append(item)


def _buscar_inventario_fastapi(
    query: str,
    *,
    categoria: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """
    Inventario real exclusivamente vía HTTP GET a FastAPI ED NET PRO.

    Endpoints:
      GET /agents/catalog/zopa?q=...   — match + precios ZOPA
      GET /agents/catalog/snapshot     — listado del catálogo Shein/Nyx Bridge
    """
    base = _supervendedor_base()
    endpoints_usados: list[str] = []
    productos: list[dict[str, Any]] = []
    resumen: dict[str, Any] | None = None
    errores: list[str] = []

    q = query.strip()
    if q:
        zopa_url = f"{base}{INVENTARIO_ZOPA_PATH}"
        response = _fastapi_get(INVENTARIO_ZOPA_PATH, params={"q": q})
        if response is None:
            errores.append(f"No hubo conexión con {zopa_url}")
        else:
            endpoints_usados.append(f"GET {INVENTARIO_ZOPA_PATH}?q={q}")
            data = _parse_fastapi_json(response, INVENTARIO_ZOPA_PATH)
            if data:
                _merge_productos(productos, data.get("product"), zopa=data.get("zopa"))

    snapshot_url = f"{base}{INVENTARIO_SNAPSHOT_PATH}"
    response = _fastapi_get(INVENTARIO_SNAPSHOT_PATH)
    if response is None:
        errores.append(f"No hubo conexión con {snapshot_url}")
    else:
        endpoints_usados.append(f"GET {INVENTARIO_SNAPSHOT_PATH}")
        data = _parse_fastapi_json(response, INVENTARIO_SNAPSHOT_PATH)
        if data:
            resumen = data.get("summary")
            for raw in data.get("products", []):
                _merge_productos(productos, raw)

    cat = categoria.strip().lower()
    if q or cat:
        productos = [
            p
            for p in productos
            if _matches_query(p["titulo"], query)
            and (not cat or cat in p["titulo"].lower())
        ]

    productos = productos[:limit]

    if productos:
        return {
            "ok": True,
            "fuente": "fastapi",
            "api_base": base,
            "endpoints_consultados": endpoints_usados,
            "query": query,
            "categoria": categoria or None,
            "total_encontrados": len(productos),
            "resumen_catalogo": resumen,
            "productos": productos,
        }

    if errores:
        return {
            "ok": False,
            "fuente": "fastapi",
            "api_base": base,
            "endpoints_consultados": endpoints_usados,
            "query": query,
            "productos": [],
            "error": (
                f"FastAPI no respondió en {base}. "
                "Levanta la API: .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000"
            ),
            "detalle": errores,
        }

    return {
        "ok": True,
        "fuente": "fastapi",
        "api_base": base,
        "endpoints_consultados": endpoints_usados,
        "query": query,
        "categoria": categoria or None,
        "total_encontrados": 0,
        "resumen_catalogo": resumen,
        "productos": [],
        "aviso": f"Sin coincidencias para «{query}» en el catálogo ED NET PRO.",
    }


def buscar_productos_inventario(
    query: str,
    *,
    categoria: str = "",
    limit: int = 10,
    incluir_ventas_recientes: bool = False,
) -> dict[str, Any]:
    """Consulta inventario exclusivamente vía HTTP GET a FastAPI (127.0.0.1:8000)."""
    limit = max(1, min(int(limit), 50))
    result = _buscar_inventario_fastapi(query, categoria=categoria, limit=limit)

    if incluir_ventas_recientes:
        ventas_payload = _fetch_ventas_pocketbase_http(limit=5)
        result["ventas_recientes"] = ventas_payload.get("ventas", [])

    return result


def _fetch_ventas_pocketbase_http(
    *,
    limit: int = 20,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    """Ventas reales desde PocketBase vía httpx."""
    limit = max(1, min(int(limit), 100))
    collection = os.getenv("VENTAS_COLLECTION", "ventas")
    base_path = f"/api/collections/{collection}/records"

    param_variants: list[dict[str, Any]] = [
        {"page": 1, "perPage": limit, "sort": "-created"},
        {"page": 1, "perPage": limit, "sort": "-@created"},
        {"page": 1, "perPage": limit},
    ]

    items: list[dict[str, Any]] = []
    last_status = 0

    for params in param_variants:
        response = _pocketbase_get(base_path, params=params)
        if response is None:
            continue
        last_status = response.status_code
        if response.status_code != 200:
            if response.status_code not in (400, 422):
                break
            continue
        payload = response.json()
        raw_items = payload.get("items", [])
        if isinstance(raw_items, list):
            items = [r for r in raw_items if isinstance(r, dict)]
            break

    ventas = [
        {
            "id": r.get("id"),
            "cliente": r.get("cliente"),
            "producto": r.get("producto"),
            "monto": r.get("monto"),
            "estado": r.get("estado"),
            "created": r.get("created"),
        }
        for r in items[:limit]
    ]

    if estado.strip():
        est = estado.strip().lower()
        ventas = [v for v in ventas if str(v.get("estado", "")).lower() == est]

    if producto.strip():
        prod = producto.strip().lower()
        ventas = [v for v in ventas if prod in str(v.get("producto", "")).lower()]

    montos = [float(v.get("monto") or 0) for v in ventas]
    total_ingresos = sum(montos)
    n = len(ventas)

    ok = last_status in (0, 200) or bool(ventas)
    result: dict[str, Any] = {
        "ok": ok,
        "fuente": "pocketbase",
        "coleccion": collection,
        "total_registros": n,
        "ingresos_totales_cop": round(total_ingresos, 2),
        "ticket_promedio_cop": round(total_ingresos / n, 2) if n else 0,
        "filtros": {
            "estado": estado or None,
            "producto": producto or None,
            "limit": limit,
        },
        "ventas": ventas,
    }

    if not ok and last_status:
        result["error"] = f"PocketBase respondió HTTP {last_status}"
    elif not ventas:
        result["aviso"] = "No hay ventas registradas en PocketBase todavía."

    return result


def consultar_ventas_pocketbase(
    *,
    limit: int = 20,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    return _fetch_ventas_pocketbase_http(limit=limit, estado=estado, producto=producto)


# ── Dispatcher central de tools MCP ───────────────────────────────────────────

def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Ejecuta una tool MCP contra datos reales (FastAPI + PocketBase).

    Inventario: HTTP GET exclusivo a FastAPI ED NET PRO.
    Ventas: HTTP PocketBase con credenciales del entorno.
    """
    args = arguments or {}
    logger.info("call_tool name=%r args=%s", name, args)

    if name == "buscar_productos_inventario":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"ok": False, "error": "El parámetro 'query' es obligatorio."}
        return buscar_productos_inventario(
            query,
            categoria=str(args.get("categoria", "")),
            limit=int(args.get("limit", 10)),
            incluir_ventas_recientes=bool(args.get("incluir_ventas_recientes", False)),
        )

    if name == "consultar_ventas_pocketbase":
        return consultar_ventas_pocketbase(
            limit=int(args.get("limit", 20)),
            estado=str(args.get("estado", "")),
            producto=str(args.get("producto", "")),
        )

    return {"ok": False, "error": f"Tool desconocida: {name}"}


# ── MCP Tools (SDK MCP 2.x — transporte stdio vía run_stdio_async) ─────────────

@mcp.tool(
    name="buscar_productos_inventario",
    description=(
        "Consulta inventario y precios del catálogo Super Vendedor (Shein / Nyx Bridge). "
        "Invocar cuando el usuario o la IA necesiten: stock disponible, precios COP, "
        "comparar productos de ropa/calzado/accesorios, armar ofertas de venta, "
        "responder '¿tienen X?', 'precio de enterizo/vestido/zapatos', o preparar "
        "negociación ZOPA con datos reales del catálogo."
    ),
)
def buscar_productos_inventario_tool(
    query: str,
    categoria: str = "",
    limit: int = 10,
    incluir_ventas_recientes: bool = False,
) -> str:
    result = call_tool(
        "buscar_productos_inventario",
        {
            "query": query,
            "categoria": categoria,
            "limit": limit,
            "incluir_ventas_recientes": incluir_ventas_recientes,
        },
    )
    logger.info(
        "buscar_productos_inventario → %d productos (fuente=%s)",
        result.get("total_encontrados", len(result.get("productos", []))),
        result.get("fuente", "n/a"),
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool(
    name="consultar_ventas_pocketbase",
    description=(
        "Consulta ventas cerradas y métricas comerciales en tiempo real desde PocketBase. "
        "Invocar cuando necesites: ingresos del día/semana, ventas por producto, "
        "ticket promedio, leads convertidos, historial de cierres del simulador o "
        "dashboard, o responder '¿cuánto vendimos?', 'últimas ventas', 'ventas de Tarjeta NFC'."
    ),
)
def consultar_ventas_pocketbase_tool(
    limit: int = 20,
    estado: str = "",
    producto: str = "",
) -> str:
    result = call_tool(
        "consultar_ventas_pocketbase",
        {"limit": limit, "estado": estado, "producto": producto},
    )
    logger.info(
        "consultar_ventas_pocketbase → %d ventas",
        result.get("total_registros", 0),
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


async def main() -> None:
    logger.info(
        "Iniciando servidor MCP '%s' (stdio) — FastAPI=%s PocketBase=%s",
        SERVER_NAME,
        _supervendedor_base(),
        _pocketbase_base(),
    )
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
