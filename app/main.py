# app/main.py
from fastapi import FastAPI
import uvicorn
import os

# Importamos SOLO los handlers que vamos a usar
from app.routers import gupshup_handler
from app.routers import vapi_handler

app = FastAPI()

# Activamos las rutas
app.include_router(gupshup_handler.router)
app.include_router(vapi_handler.router)

@app.get("/")
def read_root():
    return {"status": "🚀 EL OLIMPO ESTÁ ACTIVO (Gupshup + Vapi)"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)