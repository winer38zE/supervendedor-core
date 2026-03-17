from fastapi import APIRouter, Request
from app.orchestrator import ZeusOrchestrator
from app.config import settings
import requests

router = APIRouter()
zeus = ZeusOrchestrator()

@router.post("/webhook")
async def handle_evolution(request: Request):
    data = await request.json()
    
    # Verificamos que sea un mensaje de texto entrante
    if data.get("event") == "messages.upsert":
        msg_data = data.get("data", {})
        user_id = msg_data.get("key", {}).get("remoteJid")
        user_message = msg_data.get("message", {}).get("conversation") or \
                       msg_data.get("message", {}).get("extendedTextMessage", {}).get("text")

        if user_message and not msg_data.get("key", {}).get("fromMe"):
            # Zeus procesa la respuesta
            response = zeus.process_message(user_id, user_message, [])
            
            # Enviamos la respuesta de vuelta por WhatsApp
            send_whatsapp(user_id, response["content"])
            
    return {"status": "success"}

def send_whatsapp(remote_jid, text):
    # Ajusta 'super_vendedor' al nombre de tu instancia real
    url = f"http://localhost:8080/message/sendText/super_vendedor"
    headers = {"apikey": "TU_KEY_DE_EVOLUTION", "Content-Type": "application/json"}
    payload = {"number": remote_jid.split("@")[0], "text": text}
    requests.post(url, json=payload, headers=headers)