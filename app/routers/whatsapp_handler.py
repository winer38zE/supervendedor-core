# Dentro de app/routers/whatsapp_handler.py

from fastapi import APIRouter
from ..orchestrator import ZeusOrchestrator # <--- ¡SOLUCIÓN!

router = APIRouter()
# Instancia global (Zeus cobra vida)
global_olympus_brain = ZeusOrchestrator() 

# ... (El resto de la lógica para manejar el mensaje de WhatsApp) ...