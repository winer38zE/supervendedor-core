# app/routers/gupshup_handler.py
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
        print(f"🔍 LLEGÓ PAQUETE: {json.dumps(data)}") 
        
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')
        type_msg = payload.get('type')

        # RESPONDER SIEMPRE (Quitamos los filtros para probar)
        if sender:
            # Si es texto, repetimos el texto. Si es evento, saludamos.
            mensaje_respuesta = f"🦜 Loro activo. Recibí: {text}" if text else f"👋 ¡Conexión recibida! Evento: {type_msg}"
            
            print(f"✅ Intentando responder a: {sender}")
            background_tasks.add_task(send_reply, sender, mensaje_respuesta)
            
    except Exception as e:
        print(f"🔥 ERROR LEYENDO: {e}")
    
    return {"status": "ok"}

def send_reply(phone, text):
    # --- CORRECCIÓN DE IDENTIDAD ---
    # Usamos el nombre EDNETBOTIA fijo (lo vi en tu foto)
    src_name = "EDNETBOTIA" 
    
    # Usamos el número de teléfono desde las variables
    source_phone = os.environ.get("GUPSHUP_SRC_NAME") 
    # (Asegúrate de que en Railway GUPSHUP_SRC_NAME sea tu número: 573169060209)

    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY")
    }
    
    data = {
        "channel": "whatsapp",
        "source": source_phone, # Aquí va el número
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": src_name    # Aquí va el nombre EDNETBOTIA
    }
    
    print(f"📤 Enviando respuesta a {phone}...")
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📬 RESULTADO GUPSHUP: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"🔥 ERROR DE CONEXIÓN: {e}")