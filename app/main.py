from fastapi import FastAPI
import uvicorn
import os

# ✅ IMPORTA LOS ROUTERS
from app.routers import vapi_handler
from app.routers import gupshup_handler
from app.routers import hunter_router
from app.routers import cierre_router
from app.routers import centinela_router
from app.routers import saas_router

# Configuración
try:
    from app.config import settings
except ImportError:
    class settings:
        OWNER_ID = "edwuar"

# ── INICIO DE TELEMETRÍA (Sentry) ─────────────────────────────────────────────
import sentry_sdk

sentry_sdk.init(
    dsn="https://34352135b5074b0937afbee8f1e92192@o4511691690016768.ingest.us.sentry.io/4511691765383168",
    traces_sample_rate=1.0, 
)
# ──────────────────────────────────────────────────────────────────────────────

# CREA LA APP
app = FastAPI(
    title="ED NET PRO - Supervendedor Core",
    description="Supervendedor AI — Single Tenant | WhatsApp + Vapi + Hunter",
    version="3.0.0-single",
)

# ──────────────────────────────────────────────────────────────────────────────
# REGISTRA TODOS LOS ROUTERS
# ──────────────────────────────────────────────────────────────────────────────

# ✅ Se eliminó el prefijo "/vapi" solo de esta línea para evitar el choque
app.include_router(vapi_handler.router, tags=["Voice (Vapi)"])

# Las demás se dejan igual para no romper los otros canales
app.include_router(gupshup_handler.router, prefix="/whatsapp", tags=["WhatsApp"])
app.include_router(hunter_router.router, prefix="/hunter", tags=["Hunter"])
app.include_router(cierre_router.router, prefix="/cierre", tags=["Cierre"])
app.include_router(centinela_router.router, prefix="/centinela", tags=["Centinela"])
app.include_router(saas_router.router, prefix="/saas", tags=["SAAS"])

# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINTS BASE
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "status": "✅ SISTEMA ED NET PRO EN LINEA",
        "modo": "single-tenant",
        "owner": getattr(settings, "OWNER_ID", "edwuar"),
        "version": "3.0.0",
        "canales_activos": ["WhatsApp (Evolution API)", "Voice (Vapi)", "Hunter"],
        "embudo": "Prospecto → Athena → Hermes → Cita",
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/sentry-debug")
async def provocar_error():
    """Ruta secreta para probar que el radar de Sentry funciona"""
    print("Iniciando prueba de Sentry...")
    division_por_cero = 1 / 0
    return {"status": "Esto nunca se va a imprimir"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)