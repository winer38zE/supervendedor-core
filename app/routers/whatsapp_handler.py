# Dentro de app/routers/whatsapp_handler.py

from fastapi import APIRouter
# En app/routers/whatsapp_handler.py
from app.orchestrator import ZeusOrchestrator  # <--- Esta es la forma segura

router = APIRouter()
# Instancia global (Zeus cobra vida)
global_olympus_brain = ZeusOrchestrator() 

# ... (El resto de la lógica para manejar el mensaje de WhatsApp) ...