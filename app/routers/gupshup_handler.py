import os
from fastapi import APIRouter, Request
from ..orchestrator import ZeusOrchestrator

# --- LÍNEA VITAL: DEFINE EL ROUTER ---
router = APIRouter()
orchestrator = ZeusOrchestrator()

@router.post("/")
async def handle_gupshup(request: Request):
    """Recibe mensajes de WhatsApp vía Gupshup"""
    data = await request.json()
    print(f"📩 Webhook recibido: {data}")
    
    # Lógica para extraer mensaje y responder...
    return {"status": "success"}