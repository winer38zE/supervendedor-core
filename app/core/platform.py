"""
app/core/platform.py — Metadatos y mapa arquitectónico ED NET PRO 3.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformChannel:
    id: str
    name: str
    router_module: str
    webhook_paths: tuple[str, ...]
    integration: str


PLATFORM_VERSION = "3.0.0"
PLATFORM_NAME = "ED NET PRO"
PLATFORM_TAGLINE = "Agencia digital automatizada — ventas IA, voz, WhatsApp y catálogo"

CHANNELS: tuple[PlatformChannel, ...] = (
    PlatformChannel(
        id="whatsapp_evolution",
        name="WhatsApp (Evolution API)",
        router_module="app.routers.whatsapp_handler",
        webhook_paths=("/webhook/whatsapp", "/whatsapp/webhook"),
        integration="Evolution API + MCP tools",
    ),
    PlatformChannel(
        id="voice_vapi",
        name="Voz (Vapi)",
        router_module="app.routers.vapi_handler",
        webhook_paths=("/vapi/webhook", "/vapi/tools/webhook"),
        integration="Vapi tool-calls + inventario/ventas",
    ),
    PlatformChannel(
        id="mcp_servidor_ventas",
        name="MCP Servidor Ventas",
        router_module="servidor_ventas",
        webhook_paths=(),
        integration="stdio MCP — Cursor / Claude Desktop",
    ),
)

API_GROUPS: dict[str, dict[str, Any]] = {
    "agents_catalog": {
        "prefix": "/agents",
        "description": "Catálogo Shein/Nyx Bridge, ZOPA, followup CRM",
    },
    "hermes_bridge": {
        "prefix": "/api/v1/agents",
        "description": "Puente Hermes → agentes de negociación",
    },
    "chat_orchestrator": {
        "prefix": "/api/v1/chat",
        "description": "Orquestador multimodal n8n",
    },
    "content_pipeline": {
        "prefix": "/api/v1/content",
        "description": "Outliers virales + remix comercial",
    },
    "marketing_ads": {
        "prefix": "/ads",
        "description": "Meta Ads — ciclo automatizado",
    },
    "business_metrics": {
        "prefix": "/api/v1/metrics",
        "description": "Métricas unificadas ventas, catálogo y marketing",
    },
    "hunter_b2b": {"prefix": "/hunter", "description": "Prospección B2B Shaka"},
    "saas_admin": {"prefix": "/saas", "description": "Multi-tenant SAAS (legacy)"},
}


def platform_architecture_payload() -> dict[str, Any]:
    """Payload JSON para dashboards y documentación runtime."""
    return {
        "platform": PLATFORM_NAME,
        "version": PLATFORM_VERSION,
        "tagline": PLATFORM_TAGLINE,
        "channels": [
            {
                "id": ch.id,
                "name": ch.name,
                "webhooks": list(ch.webhook_paths),
                "integration": ch.integration,
            }
            for ch in CHANNELS
        ],
        "api_groups": API_GROUPS,
        "data_layer": {
            "crm": "PocketBase (leads, ventas, conversaciones)",
            "catalog": "Catalog Bridge + Shein Excel/scraper",
            "content": "SQLAlchemy (outliers/scripts)",
        },
        "ai_stack": {
            "llm_router": "OpenAI + Claude (app/services/llm_router.py)",
            "vision": "Gemini 2.0 Flash",
            "memory": "Mem0",
            "voice": "Vapi + ElevenLabs",
        },
    }


PLATFORM = platform_architecture_payload()
