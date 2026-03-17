# app/main.py
from fastapi import FastAPI
import uvicorn
import os

# 1. Importamos solo los handlers que vamos a utilizar
# Eliminamos Gupshup por completo
from app.routers import evolution_handler
from app.routers import vapi_handler

# 2. Inicializamos la aplicación primero (Paso crítico)
app = FastAPI(
    title="ED NET PRO - Engineering in Sales",
    description="Súper Vendedor AI con Evolution API y Vapi",
    version="1.1.0"
)

# 3. Registramos los routers activos
# Ruta para WhatsApp (Evolution API)
app.include_router(
    evolution_handler.router, 
    prefix="/evolution", 
    tags=["WhatsApp (Evolution API)"]
)

# Ruta para el asistente de voz (Vapi)
app.include_router(
    vapi_handler.router, 
    prefix="/vapi", 
    tags=["Voice AI (Vapi)"]
)

# 4. Ruta de control para verificar el estado del servidor
@app.get("/")
def read_root():
    return {
        "status": "🚀 SISTEMA ED NET PRO EN LÍNEA",
        "agente": "Súper Vendedor Pro",
        "motor": "Anthropic Claude 3.5 Sonnet + Groq",
        "canales_activos": ["WhatsApp (Evolution)", "Voice (Vapi)"],
        "region": "AWS Cloud"
    }

# 5. Ejecución del servidor
if __name__ == "__main__":
    # Usamos el puerto 8080 que es el estándar para tus instancias de AWS
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)