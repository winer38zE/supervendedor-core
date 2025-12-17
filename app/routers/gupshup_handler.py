from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 DATOS DE TU CUENTA ---
GUPHSUP_API_KEY = "zgov8ynqbughsixwkmygxbhym9uwybwf" 
GUPHSUP_APP_NAME = "EDNETBOTIA" 
# ESTA ES LA URL QUE SALE EN TU FOTO (SANDBOX):
GUPHSUP_URL = "https://api.gupshup.io/wa/api/v1/msg"

# --- 🛠️ FUNCIÓN DE ENVÍO (MIMETIZANDO TU FOTO) ---
def send_whatsapp_message(destination_number, text_message):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPHSUP_API_KEY,
        "Cache-Control": "no-cache"
    }

    # Payload exacto como lo pide tu Sandbox
    payload = {
        "channel": "whatsapp",
        "source": "573169060209", # IMPORTANTE: En /wa/ a veces pide el NÚMERO, no el nombre.
        "destination": destination_number,
        "message": text_message,
        "src.name": GUPHSUP_APP_NAME
    }

    print(f"🚀 ENVIANDO A {destination_number}...")

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
        print(f"📥 DATA: {json.dumps(data)}")
        
        payload = data.get('payload', {})
        tipo = data.get('type')

        # Buscar cliente
        cliente = payload.get('source')
        if not cliente:
            cliente = payload.get('sender', {}).get('phone')

        texto = payload.get('body', {}).get('text')

        # Filtros
        if tipo == "sandbox-start":
            return {"status": "ok"}
            
        if not cliente:
            return {"status": "ok"}

        print(f"✅ MENSAJE DE {cliente}: {texto}")
        
        # Respuesta
        respuesta = f"🤖 Recibido: {texto}. Probando URL WA."
        background_tasks.add_task(send_whatsapp_message, cliente, respuesta)

    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}