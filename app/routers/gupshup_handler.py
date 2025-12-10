# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import os
import json
from app.orchestrator import ZeusOrchestrator

router = APIRouter()
zeus_brain = ZeusOrchestrator()

# --- 1. VERIFICACIÓN (Para que Gupshup acepte la URL) ---
@router.get("/gupshup/webhook")
async def verify_webhook():
    print("🔔 Gupshup está verificando la URL...")
    return "OK"  # Responder simple y plano para que Gupshup sepa que estamos vivos.

# --- 2. RECIBIR MENSAJES (El Oído) ---
@router.post("/gupshup/webhook")
async def gupshup_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        
        # Filtro: Si no es un mensaje (ej. es un reporte de 'leído'), lo ignoramos
        if data.get('type') != 'message':
            return {"status": "ignored"}

        # Extraer datos (Formato Gupshup v2)
        payload = data.get('payload', {})
        sender_phone = payload.get('source')      # Quién envía
        user_text = payload.get('body', {}).get('text') # Qué dice
        
        print(f"📩 Mensaje de {sender_phone}: {user_text}")

        # Procesar con ZEUS en segundo plano
        if user_text:
            background_tasks.add_task(process_and_reply, sender_phone, user_text)

    except Exception as e:
        print(f"🔥 Error en Webhook: {e}")

    return {"status": "received"}

# --- 3. RESPONDER (La Boca) ---
async def process_and_reply(phone, text):
    # Zeus piensa...
    ai_response = zeus_brain.process_message(phone, text, [])
    response_text = ai_response.get("content", "")
    
    if response_text:
        send_message(phone, response_text)

def send_message(phone, text):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY")
    }
    data = {
        "channel": "whatsapp",
        "source": os.environ.get("GUPSHUP_SRC_NAME"), # Tu número 57316... o nombre de app
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": os.environ.get("GUPSHUP_SRC_NAME")
    }
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📤 Respuesta enviada: {r.status_code}")
    except Exception as e:
        print(f"🔥 Error enviando respuesta: {e}")
        # --- AGREGAR ESTO AL FINAL DEL ARCHIVO ---

@router.get("/gupshup/webhook")
async def verify_webhook():
    """Gupshup usa esto para verificar que existimos"""
    return {"status": "Zeus está escuchando"}
# --- SIMULADOR DE PRUEBAS (Para probar sin celular) ---
@router.get("/test/simular")
async def simulate_chat(background_tasks: BackgroundTasks):
    """
    Esto engaña al sistema haciéndole creer que llegó un mensaje.
    Úsalo para probar si Zeus piensa y responde.
    """
    phone_falso = "573001234567" # Un número inventado
    mensaje_prueba = "Hola Zeus, ¿vendes sábanas?"
    
    print(f"🧪 INICIANDO SIMULACRO: {mensaje_prueba}")
    
    # Le decimos a Zeus que procese este mensaje falso
    background_tasks.add_task(process_and_reply, phone_falso, mensaje_prueba)
    
    return {"status": "Simulacro enviado. ¡Corre a ver los Logs en Railway!"}
