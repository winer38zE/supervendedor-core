from fastapi import Depends, FastAPI, HTTPException
import uvicorn
import os
import asyncio
import logging

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

from app.config import settings, log_startup_warnings
from app.security import verify_api_key

logger = logging.getLogger(__name__)

# ── INICIO DE TELEMETRÍA (Sentry) ─────────────────────────────────────────────
import sentry_sdk

sentry_sdk.init(
    dsn="https://34352135b5074b0937afbee8f1e92192@o4511691690016768.ingest.us.sentry.io/4511691765383168",
    traces_sample_rate=1.0,
)
# ──────────────────────────────────────────────────────────────────────────────

_is_production = settings.ENV == "production"

app = FastAPI(
    title="ED NET PRO - Supervendedor Core",
    description="Supervendedor AI — Single Tenant | WhatsApp + Vapi + Hunter",
    version="3.0.0-single",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

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


@app.on_event("startup")
async def startup_supervendedor():
    global _followup_task
    log_startup_warnings()

    try:
        from app.agents.catalog_bridge_agent import get_catalog_bridge
        bridge = get_catalog_bridge()
        count = bridge.refresh()
        logger.info(f"[Startup] Catalog Bridge: {count} productos cargados")
    except Exception as e:
        logger.warning(f"[Startup] Catalog Bridge error: {e}")

    try:
        from app.database.sqlalchemy_session import init_content_db
        init_content_db()
    except Exception as e:
        logger.warning(f"[Startup] Content DB error: {e}")

    if os.environ.get("FOLLOWUP_SCHEDULER_ENABLED", "true").lower() == "true":
        from app.agents.closing_followup_agent import followup_scheduler_loop
        interval = float(os.environ.get("FOLLOWUP_INTERVAL_HOURS", "6"))
        _followup_task = asyncio.create_task(followup_scheduler_loop(interval))
        logger.info(f"[Startup] Followup scheduler cada {interval}h")


@app.on_event("shutdown")
async def shutdown_supervendedor():
    global _followup_task
    if _followup_task and not _followup_task.done():
        _followup_task.cancel()
        try:
            await _followup_task
        except asyncio.CancelledError:
            pass


@app.get("/", dependencies=[Depends(verify_api_key)])
def read_root():
    return {
        "status": "✅ SISTEMA ED NET PRO EN LINEA",
        "modo": "single-tenant",
        "env": settings.ENV,
        "owner": settings.OWNER_ID,
        "version": "3.0.0",
        "canales_activos": ["WhatsApp (Evolution API)", "Voice (Vapi)", "Hunter", "Agentes/Catálogo", "Meta Ads", "Chat n8n", "Hermes Bridge", "Avatares (ElevenLabs + Replicate)", "Content & Outliers"],
        "embudo": "Prospecto → Athena → Catalog Bridge → Objection Killer → Hermes → Cita",
        "agentes_activos": 11,
    }


@app.get("/health")
def health():
    from app.database.supabase_client import db_health
    return {"status": "healthy", "database": db_health()}


@app.get("/sentry-debug")
async def provocar_error():
    """Solo disponible fuera de producción."""
    if settings.ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")
    division_por_cero = 1 / 0
    return {"status": "Esto nunca se va a imprimir"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
