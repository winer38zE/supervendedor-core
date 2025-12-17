from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 DATOS DE TU CUENTA ---
GUPHSUP_API_KEY = "zgov8ynqbughsixwkmygxbhym9uwybwf" 
GUPHSUP_APP_NAME = "EDNETBOTIA" 

# ⚠️ CORRECCIÓN FINAL: Usamos la ruta "sm" (Smart Messaging) que es la ÚNICA para QR
GUPHSUP_URL = "https://api.gupshup.io/sm/api/v1/msg"

# --- 🛠️ FUNCIÓN DE ENVÍO (CONFIGURADA PARA QR) ---
def send_whatsapp_message(destination_number, text_message):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPHSUP_API_KEY
    }

    # En la API de QR (sm), el source DEBE ser el nombre de la app
    payload = {
        "channel": "whatsapp",
        "source": GUPHSUP_APP_NAME,  # Aquí va "EDNETBOTIA"
        "destination": destination_number,
        "message": text_message,
        "src.name": GUPHSUP_APP_NAME
    }

    print(f"🚀 ENVIANDO A {destination_number} POR RUTA QR (SM)...")

    try:
        response = requests.post(GUPHSUP_URL, headers=headers, data=payload)
        print(f"📬 GUPSHUP RESPONDE: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"💀 ERROR DE ENVÍO: {e}")

# --- 📡 EL WEBHOOK ---
@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        # print(f"📥 DATA: {json.dumps(data)}") # Descomenta si quieres ver todo el ruido
        
        payload = data.get('payload', {})
        tipo = data.get('type')

        # Buscar cliente (Soporta ambos formatos de Gupshup)
        cliente = payload.get('source')
        if not cliente:
            cliente = payload.get('sender', {}).get('phone')

        texto = payload.get('body', {}).get('text')

        # Filtros de eventos que no son mensajes
        if tipo in ["sandbox-start", "sent", "delivered", "read", "failed", "enqueued"]:
            if tipo == "failed":
                print(f"❌ ERROR REPORTADO POR GUPSHUP: {json.dumps(payload)}")
            return {"status": "ok"}
            
        if not cliente or not texto:
            return {"status": "ok"}

        print(f"✅ MENSAJE RECIBIDO DE {cliente}: {texto}")
        
        # Respuesta Automática
        respuesta = f"🤖 ¡Hola! Soy {GUPHSUP_APP_NAME}. Recibí tu mensaje: '{texto}'"
        background_tasks.add_task(send_whatsapp_message, cliente, respuesta)

    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}