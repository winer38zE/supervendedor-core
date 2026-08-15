"""
app/main.py — Núcleo unificado ED NET PRO 3.0

FastAPI central: canales (WhatsApp/Vapi/MCP), agentes IA, catálogo,
marketing, métricas de negocio y bridge Hermes.
"""

from __future__ import annotations

import logging
import os

<<<<<<< HEAD
# ✅ IMPORTA LOS ROUTERS
from app.routers import vapi_handler
from app.routers import gupshup_handler
from app.routers import whatsapp_handler
from app.routers import hunter_router
from app.routers import cierre_router
from app.routers import centinela_router
from app.routers import saas_router
from app.routers import agents_router
from app.routers import ads_router
from app.routers import chat
from app.routers import avatares
from app.routers import content_router
from app import api_bridge
=======
import sentry_sdk
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2

from app.config import settings
from app.core.lifecycle import on_shutdown, on_startup
from app.core.platform import PLATFORM_NAME, PLATFORM_VERSION
from app.core.router_registry import register_platform_routers
from app.security import verify_api_key

logger = logging.getLogger(__name__)

sentry_sdk.init(
    dsn="https://34352135b5074b0937afbee8f1e92192@o4511691690016768.ingest.us.sentry.io/4511691765383168",
    traces_sample_rate=1.0,
)

_is_production = settings.ENV == "production"

app = FastAPI(
    title=f"{PLATFORM_NAME} — Supervendedor Core",
    description=(
        "Plataforma todo-en-uno: ventas IA, WhatsApp (Evolution), voz (Vapi), "
        "catálogo Shein/dropshipping, Meta Ads y métricas de negocio."
    ),
    version=f"{PLATFORM_VERSION}-single",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

<<<<<<< HEAD
# ──────────────────────────────────────────────────────────────────────────────
# REGISTRA TODOS LOS ROUTERS
# ──────────────────────────────────────────────────────────────────────────────

app.include_router(vapi_handler.router, tags=["Voice (Vapi)"])
app.include_router(gupshup_handler.router, prefix="/whatsapp", tags=["WhatsApp"])
app.include_router(whatsapp_handler.router, tags=["WhatsApp Webhook"])
app.include_router(hunter_router.router, prefix="/hunter", tags=["Hunter"])
app.include_router(cierre_router.router, prefix="/cierre", tags=["Cierre"])
app.include_router(centinela_router.router, prefix="/centinela", tags=["Centinela"])
app.include_router(saas_router.router, prefix="/saas", tags=["SAAS"])
app.include_router(agents_router.router, prefix="/agents", tags=["Agentes"])
app.include_router(ads_router.router, tags=["Meta Ads"])
app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(api_bridge.router, prefix="/api/v1", tags=["Hermes Bridge"])
app.include_router(avatares.router, prefix="/api/v1/avatares", tags=["Avatares"])
app.include_router(content_router.router, prefix="/api/v1/content", tags=["Content & Outliers"])

_followup_task = None
=======
register_platform_routers(app)
>>>>>>> 5abd626cce5c7c9a25b79377954793361c2622a2


@app.on_event("startup")
async def startup_supervendedor() -> None:
    await on_startup()


@app.on_event("shutdown")
async def shutdown_supervendedor() -> None:
    await on_shutdown()


@app.get("/", dependencies=[Depends(verify_api_key)])
def read_root() -> dict:
    return {
        "status": f"SISTEMA {PLATFORM_NAME} EN LINEA",
        "version": PLATFORM_VERSION,
        "modo": "single-tenant",
        "env": settings.ENV,
        "owner": settings.OWNER_ID,
        "canales": {
            "whatsapp": ["/webhook/whatsapp", "/whatsapp/webhook"],
            "vapi": ["/vapi/webhook", "/vapi/tools/webhook"],
            "mcp": "servidor_ventas.py (stdio)",
        },
        "metricas": "/api/v1/metrics/overview",
        "arquitectura": "/api/v1/metrics/architecture",
        "embudo": "Prospecto → Athena → Catalog Bridge → Objection Killer → Hermes → Cita",
    }


@app.get("/health")
def health() -> dict:
    from app.database.supabase_client import db_health

    return {"status": "healthy", "database": db_health(), "version": PLATFORM_VERSION}


@app.get("/sentry-debug")
async def provocar_error() -> dict:
    if settings.ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")
    _ = 1 / 0
    return {"status": "unreachable"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.PORT))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
