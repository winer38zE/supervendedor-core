from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 CONFIGURACIÓN BLINDADA ---
# Tu clave real (asegúrate que sea la correcta de tu cuenta)
GUPHSUP_API_KEY = "zgov8ynqbughsixwkmygxbhym9uwybwf" 
GUPHSUP_APP_NAME = "EDNETBOTIA" 

# ⚠️ CAMBIO CRÍTICO: URL ACTUALIZADA SEGÚN DOCUMENTACIÓN OFICIAL (/wa/)
# ⚠️ CAMBIA ESTO EN TU CÓDIGO AHORA MISMO
GUPHSUP_URL = "https://api.gupshup.io/sm/api/v1/msg"

# --- 🛠️ FUNCIÓN DE ENVÍO ---
def send_whatsapp_message(destination_number, text_message):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPHSUP_API_KEY
    }

    # Payload en formato Form-Data
    payload = {
        "channel": "whatsapp",
        "source": GUPHSUP_APP_NAME,
        "destination": destination_number,
        "message": text_message,
        "src.name": GUPHSUP_APP_NAME
    }

    print(f"🚀 ENVIANDO A {destination_number} USANDO URL: {GUPHSUP_URL}")

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
        # 1. Intentamos leer JSON
        data = await request.json()
        print(f"📥 DATA RECIBIDA: {json.dumps(data)}")
        
        # 2. Extraer datos
        payload = data.get('payload', {})
        tipo = data.get('type')

        # Buscar cliente
        cliente = payload.get('source')
        if not cliente:
            cliente = payload.get('sender', {}).get('phone')

        texto = payload.get('body', {}).get('text')

        # 3. Filtrar eventos de sistema
        if tipo == "sandbox-start":
            print("ℹ️ Evento de inicio (sandbox-start). No se responde.")
            return {"status": "ok"}
            
        if not cliente:
            print("⚠️ No hay cliente identificado. Ignorando.")
            return {"status": "ok"}

        # 4. Responder
        print(f"✅ MENSAJE DE {cliente}: {texto}")
        respuesta = f"🤖 Recibido: {texto}. Soy {GUPHSUP_APP_NAME}."
        
        background_tasks.add_task(send_whatsapp_message, cliente, respuesta)

    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}