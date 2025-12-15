from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 DATOS FIJOS ---
NOMBRE_APP_FIJO = "EDNETBOTIA" 
NUMERO_FIJO = "573169060209"
API_KEY_FIJA = "zgov8ynqbughsixwkmygxbhym9uwybwf" 
# ----------------------

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"📥 LLEGÓ DATA BRUTA: {json.dumps(data)}") 
        
        # Lógica para detectar el número del cliente en Gupshup V2
        payload = data.get('payload', {})
        sender = payload.get('source') 
        
        # Si no está en 'source', buscamos en 'sender' (para backup)
        if not sender:
            sender = payload.get('sender', {}).get('phone')

        text_body = payload.get('body', {}).get('text')
        type_msg = payload.get('type')

        print(f"🕵️ DETECTADO -> Cliente: {sender} | Tipo: {type_msg}")

        # Solo respondemos si encontramos un remitente (sender) válido
        if sender:
            mensaje = f"✅ ¡HOLA! Soy {NOMBRE_APP_FIJO}. Recibí tu mensaje."
            # Enviamos la respuesta en segundo plano
            background_tasks.add_task(enviar_mensaje_blindado, sender, mensaje)
        else:
            print("⚠️ No encontré el número del cliente (sender) en el webhook.")

    except Exception as e:
        print(f"🔥 ERROR LEYENDO WEBHOOK: {e}")
    
    return {"status": "ok"}

def enviar_mensaje_blindado(cliente, texto):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": API_KEY_FIJA
    }
    
    # DATOS PARA API ACCESS (QR)
    data = {
        "channel": "whatsapp",
        "source": NOMBRE_APP_FIJO, # IMPORTANTE: En Access API, el source es el NOMBRE DE LA APP
        "destination": cliente,    # El número del cliente
        "message": texto,
        "src.name": NOMBRE_APP_FIJO
    } # <--- ¡ESTA LLAVE } ERA LA QUE FALTABA!
    
    print(f"📤 INTENTANDO ENVIAR A: {cliente} DESDE: {NOMBRE_APP_FIJO}")
    
    try:
        response = requests.post(url, headers=headers, data=data)
        print(f"📬 RESPUESTA GUPSHUP: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"💀 ERROR FATAL DE CONEXIÓN: {e}")