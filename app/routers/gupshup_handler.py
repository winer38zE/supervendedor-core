# app/routers/gupshup_handler.py
# --- CODIGO DE DIAGNOSTICO FINAL (MODO LORO) ---
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import os
import json

router = APIRouter()

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"🔍 LLEGÓ PAQUETE: {json.dumps(data)}") # Vemos todo
        
        # Intentamos sacar el teléfono y el texto a la fuerza
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')
        type_msg = payload.get('type')

        # RESPONDER A TODO (Incluso si es solo un evento)
        if sender:
            print(f"✅ Intentando responder a: {sender}")
            send_test_reply(sender, f"¡ESTOY VIVO! Recibí un evento tipo: {type_msg}")
            
    except Exception as e:
        print(f"🔥 ERROR LEYENDO: {e}")
    
    return {"status": "ok"}

def send_test_reply(phone, text):
    # OJO: Aquí forzamos el nombre EDNETBOTIA que vimos en tu cuenta
    src_name = "EDNETBOTIA" 
    
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY")
    }
    
    data = {
        "channel": "whatsapp",
        "source": src_name,
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": src_name
    }
    
    print(f"📤 ENVIANDO RESPUESTA A GUPSHUP...")
    try:
        r = requests.post(url, headers=headers, data=data)
        # ESTO ES LO QUE NECESITO VER EN LA FOTO SI FALLA:
        print(f"📬 RESULTADO DEL ENVIO: Código {r.status_code} - {r.text}")
    except Exception as e:
        print(f"🔥 ERROR DE CONEXIÓN: {e}")