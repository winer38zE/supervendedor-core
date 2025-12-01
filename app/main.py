from fastapi import FastAPI
from .routers import vapi_handler, whatsapp_handler

app = FastAPI(
    title="Super Vendedor IA - Backend",
    version="1.0"
)

# --- CONEXIÓN DE CABLES (ROUTERS) ---
# Aquí le decimos al cerebro que active el oído (Vapi) y el ojo (WhatsApp)
app.include_router(vapi_handler.router)
app.include_router(whatsapp_handler.router)

@app.get("/")
def root():
    return {
        "sistema": "ED NET PRO AI",
        "estado": "OPERATIVO 🟢",
        "ubicacion": "Nube Railway"
    }