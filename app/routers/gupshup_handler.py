from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 CONFIGURACIÓN BLINDADA ---
# Usamos las variables directas para evitar errores de lectura por ahora
GUPHSUP_API_KEY = "zgov8ynqbughsixwkmygxbhym9uwybwf" # Tu clave real
GUPHSUP_APP_NAME = "EDNETBOTIA" 
GUPHSUP_URL = "https://api.gupshup.io/sm/api/v1/msg"

# --- 🛠️ FUNCIÓN DE ENVÍO (CORREGIDA A FORM-DATA) ---
def send_whatsapp_message(destination_number, text_message):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": GUPHSUP_API_KEY
    }

    # Usamos Form-Data que es más robusto para Gupshup Access API
    payload = {
        "channel": "whatsapp",
        "source": GUPHSUP_APP_NAME,
        "destination": destination_number,
        "message": text_message,
        "src.name": GUPHSUP_APP_NAME
    }

    print(f"🚀 ENVIANDO RESPUESTA A: {destination_number}")

    try:
        response = requests.post(GUPHSUP_URL, headers=headers, data=payload)
        print(f"📬 GUPSHUP DICE: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"💀 ERROR DE ENVÍO: {e}")

# --- 📡 EL WEBHOOK (ADAPTADO A FASTAPI) ---
@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    # 1. RESPUESTA INMEDIATA: Gupshup exige un 200 OK rápido
    # En FastAPI, al final de la función retornamos el 200, 
    # pero usamos BackgroundTasks para que el proceso pesado no bloquee.
    
    try:
        data = await request.json()
        print(f"📥 DATA RECIBIDA: {json.dumps(data)}")
        
        # 2. EXTRACCIÓN DE DATOS (Con seguridad anti-caídas)
        payload = data.get('payload', {})
        
        # Buscamos el número del cliente (source o sender)
        cliente = payload.get('source')
        if not cliente:
            cliente = payload.get('sender', {}).get('phone')

        # Buscamos el mensaje de texto
        texto = payload.get('body', {}).get('text')
        tipo = data.get('type')

        # 3. FILTRO DE SEGURIDAD
        if not cliente:
            print("⚠️ Webhook sin cliente identificado (Ping de sistema).")
            return {"status": "ok"} # Salimos sin hacer nada

        if tipo != "msg" and tipo != "message":
            print(f"ℹ️ Evento ignorado (Tipo: {tipo})")
            return {"status": "ok"}

        # 4. LÓGICA DEL BOT (GEMINI SIMULADO POR AHORA)
        print(f"✅ MENSAJE DE {cliente}: {texto}")
        
        # Aquí iría tu llamada a Gemini. Por ahora, respuesta automática de prueba:
        respuesta_bot = f"🤖 Recibido: {texto}. Soy EDNETBOTIA y estoy vivo."
        
        # 5. AGENDAR EL ENVÍO (SEGUNDO PLANO)
        background_tasks.add_task(send_whatsapp_message, cliente, respuesta_bot)

    except Exception as e:
        print(f"🔥 ERROR EN EL CÓDIGO: {e}")
    
    # Siempre devolvemos OK para que Gupshup no se queje
    return {"status": "ok"}