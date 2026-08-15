#!/usr/bin/env python3
"""
servidor_ventas.py — Punto de entrada MCP (stdio) ED NET PRO 3.0

Delega la lógica de inventario/ventas a app.services.platform_tools_service.
Ejecutar: python servidor_ventas.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from mcp.server import MCPServer

from app.services.platform_tools_service import (
    buscar_productos_inventario,
    call_tool_sync,
    consultar_ventas_pocketbase,
)

mcp = MCPServer("super-vendedor-ventas")


@mcp.tool(
    name="buscar_productos_inventario",
    description=(
        "Consulta inventario y precios COP del catálogo Shein/Nyx Bridge vía FastAPI ED NET PRO."
    ),
)
async def buscar_productos_inventario_tool(
    query: str,
    categoria: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    return await buscar_productos_inventario(query, categoria=categoria, limit=limit)


@mcp.tool(
    name="consultar_ventas_pocketbase",
    description="Consulta ventas, ingresos y ticket promedio desde PocketBase.",
)
async def consultar_ventas_pocketbase_tool(
    limit: int = 5,
    estado: str = "",
    producto: str = "",
) -> dict[str, Any]:
    return await consultar_ventas_pocketbase(limit=limit, estado=estado, producto=producto)


def call_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatcher síncrono para Vapi, WhatsApp y scripts."""
    return call_tool_sync(tool_name, arguments)


async def main() -> None:
    await mcp.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
