# app/main.py — Single Tenant (Edwuar)
from fastapi import FastAPI
import uvicorn
import os
from pathlib import Path

from app.routers import vapi_handler
from app.routers import hunter_router
from app.routers import gupshup_handler
from app.config import settings

app = FastAPI(
    title="ED NET PRO - Supervendedor",
    description="Supervendedor AI — Single Tenant | WhatsApp + Vapi + Hunter",
    version="3.0.0-single",
)

# Voz (Vapi)
app.include_router(vapi_handler.router, tags=["Voice AI (Vapi)"])

# WhatsApp directo (Evolution API)
app.include_router(gupshup_handler.router, prefix="/gupshup", tags=["WhatsApp"])

# Prospección Hunter (Google Maps → Supabase)
app.include_router(hunter_router.router, prefix="/hunter", tags=["Hunter"])


# ── Carga de prompts locales (sin S3) ─────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DEFAULT_PROMPT = (
    "Eres Zeus, el súper vendedor de ED NET PRO. "
    "Identificas negocios y empresas serias, cualificas su interés y agendas reuniones. "
    "Eres directo, profesional y cálido. Hablas en español colombiano. "
    "Tu objetivo: llevar al prospecto desde el primer contacto hasta una cita agendada."
)


def get_client_context(client_id: str = "default") -> str:
    """
    Carga el system prompt desde archivo local.
    Busca en: prompts/{client_id}.txt  →  prompts/default.txt  →  prompt integrado.
    """
    for name in (client_id, "default"):
        path = _PROMPTS_DIR / f"{name}.txt"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return _DEFAULT_PROMPT


# ── Estado del sistema ────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "status":          "SISTEMA ED NET PRO EN LINEA",
        "modo":            "single-tenant",
        "owner":           settings.OWNER_ID,
        "canales_activos": ["WhatsApp (Evolution API)", "Voice (Vapi)"],
        "embudo":          "Prospecto → Athena → Hermes → Cita",
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
