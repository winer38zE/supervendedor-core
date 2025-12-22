# app/main.py
from fastapi import FastAPI
import uvicorn
import os

# Importamos SOLO los handlers que vamos a usar
from app.routers import gupshup_handler
from app.routers import vapi_handler

app = FastAPI()

# Por esto (agregando el prefijo):
app.include_router(gupshup_handler.router, prefix="/gupshup")
# Asegúrate de que vapi_handler.py define un 'router' tipo APIRouter:
# from fastapi import APIRouter
# router = APIRouter()
# ...Rutas aquí...
# Luego, puedes usar:
app.include_router(vapi_handler.router)

@app.get("/")
def read_root():
    return {"status": "🚀 EL OLIMPO ESTÁ ACTIVO (Gupshup + Vapi)"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)