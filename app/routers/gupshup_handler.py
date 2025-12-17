from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
import requests
import json
import os

router = APIRouter()

# --- 🔐 CONFIGURACIÓN SEGURA (usa variables de entorno en Railway) ---
GUPHSUP_API_KEY = os.getenv("zgov8ynqbughsixwkmygxbhym9uwybwf")  # Pon tu key aquí en Railway Secrets
GUPHSUP_SOURCE_NUMBER = os.getenv("573169060209")  # Ej: "521234567890" (tu número WhatsApp Business)
GUPHSUP_APP_NAME = os.getenv("GUPHSUP_APP_NAME", "EDNETBOTIA")  # Nombre de tu app
GUPHSUP_URL = "https://api.gupshup.io/wa/api/v1/msg"  # Endpoint correcto

if not GUPHSUP_API_KEY or not GUPHSUP_SOURCE_NUMBER:
    raise ValueError("Faltan variables de entorno: GUPHSUP_API_KEY y GUPHSUP_SOURCE_NUMBER")

# --- 🛠️ FUNCIÓN DE ENVÍO CORREGIDA ---
def send_whatsapp_message(destination_number: str, text_message: str):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPHSUP_API_KEY
    }
    
    # Mensaje de texto simple (session message)
    message_payload = json.dumps({"type": "text", "text": text_message})
    
    payload = {
        "channel": "whatsapp",
        "source": GUPHSUP_SOURCE_NUMBER,      # Número del negocio
        "destination": destination_number,    # Número del cliente
        "message": message_payload,           # JSON stringificado
        "src.name": GUPHSUP_APP_NAME          # Nombre de la app
    }
    
    print(f"🚀 ENVIANDO A: {destination_number} -> {text_message}")
    try:
        response = requests.post(GUPHSUP_URL, headers=headers, data=payload)
        print(f"📬 GUPSHUP RESPONSE: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        print(f"💀 ERROR DE ENVÍO: {e}")

# --- 📡 WEBHOOK ---
@router.get("/gupshup/webhook")
async def verify(token: str = None, challenge: str = None):
    # Gupshup puede enviar un token para verificar (opcional)
    # Si no, solo devuelve OK
    if challenge:
        return challenge
    return {"status": "ok"}

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"📥 DATA RECIBIDA: {json.dumps(data, indent=2)}")
        
        # Estructura típica para mensaje entrante
        if data.get("type") != "message":
            print(f"ℹ️ Evento ignorado (tipo: {data.get('type')})")
            return {"status": "ok"}
        
        payload = data.get("payload", {})
        sender_phone = payload.get("source")  # Número del cliente
        msg_type = payload.get("type")
        
        if not sender_phone or msg_type != "text":
            print("⚠️ No es un mensaje de texto válido")
            return {"status": "ok"}
        
        texto_recibido = payload.get("payload", {}).get("text", "")
        print(f"✅ MENSAJE DE {sender_phone}: {texto_recibido}")
        
        # --- LÓGICA DEL BOT (aquí pondrás Gemini/Grok más adelante) ---
        respuesta_bot = f"🤖 Recibí tu mensaje: \"{texto_recibido}\". ¡Soy EDNETBOTIA y estoy aprendiendo a ser más inteligente!"
        
        # Enviar respuesta en segundo plano (no bloquea el 200 OK)
        background_tasks.add_task(send_whatsapp_message, sender_phone, respuesta_bot)
        
    except Exception as e:
        print(f"🔥 ERROR EN WEBHOOK: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    
    return {"status": "ok"}