# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import os
import json
from app.orchestrator import ZeusOrchestrator

router = APIRouter()
zeus_brain = ZeusOrchestrator()

# --- 1. VERIFICACIÓN ---
@router.get("/gupshup/webhook")
async def verify_webhook():
    return "OK"

# --- 2. EL OÍDO BIONICO (Recepción) ---
@router.post("/gupshup/webhook")
async def gupshup_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        # A. Capturar todo lo que llega (Modo Espía)
        data = await request.json()
        print(f"🔍 LO QUE LLEGÓ DE GUPSHUP: {json.dumps(data)}")

        # B. Filtrar solo mensajes reales
        if data.get('type') != 'message':
            return {"status": "ignored"}

        payload = data.get('payload', {})
        sender_phone = payload.get('source')
        message_type = payload.get('type') # ¿Es texto o audio?
        
        # C. Lógica del Oído Biónico
        user_text = ""
        
        if message_type == "text":
            user_text = payload.get('payload', {}).get('text')
        
        elif message_type == "audio":
            # AQUI ESTA LA MAGIA (Por ahora avisamos, luego transcribimos)
            print("🎤 AUDIO DETECTADO - Preparando transcripción...")
            user_text = "[CLIENTE ENVIÓ UN AUDIO - RESPONDER AMABLEMENTE QUE ESCUCHASTE]"
        
        # D. Si hay contenido, procesar
        if user_text:
            print(f"📩 Procesando para {sender_phone}: {user_text}")
            background_tasks.add_task(process_and_reply, sender_phone, user_text)

    except Exception as e:
        print(f"🔥 ERROR CRÍTICO EN WEBHOOK: {e}")

    return {"status": "received"}

# --- 3. LA BOCA (Respuesta) ---
async def process_and_reply(phone, text):
    try:
        # Zeus piensa...
        ai_response = zeus_brain.process_message(phone, text, [])
        response_text = ai_response.get("content", "")
        
        if response_text:
            send_message(phone, response_text)
    except Exception as e:
        print(f"💀 Error pensando respuesta: {e}")

def send_message(phone, text):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY")
    }
    
    # IMPORTANTE: Aseguramos que el Source Name no esté vacío
    src_name = os.environ.get("GUPSHUP_SRC_NAME")
    if not src_name:
        src_name = "EDNETBOTIA" # Respaldo de emergencia
        
    data = {
        "channel": "whatsapp",
        "source": src_name,
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": src_name
    }
    
    try:
        print(f"📤 Enviando respuesta a {phone} vía {src_name}...")
        r = requests.post(url, headers=headers, data=data)
        print(f"✅ Estado del Envío: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"🔥 Error enviando a Gupshup: {e}")