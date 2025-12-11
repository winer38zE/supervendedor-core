# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import os
import json
from app.orchestrator import ZeusOrchestrator

router = APIRouter()
zeus_brain = ZeusOrchestrator()

# --- 1. VERIFICACIÓN (Gupshup pregunta: "¿Estás vivo?") ---
@router.get("/gupshup/webhook")
async def verify_webhook():
    print("🔔 Gupshup verificando conexión...")
    return "OK"

# --- 2. RECIBIR MENSAJES (El Oído) ---
@router.post("/gupshup/webhook")
async def gupshup_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        
        # Filtro: Ignorar reportes de entrega (solo queremos mensajes de texto)
        if data.get('type') != 'message':
            return {"status": "ignored"}

        # Extraer datos (Formato Gupshup v2)
        payload = data.get('payload', {})
        sender_phone = payload.get('source')      # El cliente
        user_text = payload.get('body', {}).get('text') # Lo que dijo
        
        print(f"📩 Mensaje de {sender_phone}: {user_text}")

        # Si hay texto, ponemos a Zeus a trabajar en segundo plano
        if user_text:
            background_tasks.add_task(process_and_reply, sender_phone, user_text)

    except Exception as e:
        print(f"🔥 Error en Webhook: {e}")

    return {"status": "received"}

# --- 3. RESPONDER (La Boca) ---
async def process_and_reply(phone, text):
    # 1. Zeus piensa la respuesta
    ai_response = zeus_brain.process_message(phone, text, [])
    response_text = ai_response.get("content", "")
    
    # 2. Enviamos la respuesta a WhatsApp
    if response_text:
        send_message(phone, response_text)

def send_message(phone, text):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY") # Tu llave nueva del 15 Nov
    }
    data = {
        "channel": "whatsapp",
        "source": os.environ.get("GUPSHUP_SRC_NAME"), # Debe ser EDNETBOTIA
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": os.environ.get("GUPSHUP_SRC_NAME")
    }
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📤 Respuesta enviada: {r.status_code}")
        # Si sale 202, todo perfecto. Si sale 401, revisa las llaves.
    except Exception as e:
        print(f"🔥 Error enviando respuesta: {e}")