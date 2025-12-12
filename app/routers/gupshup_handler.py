# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- ZONA DE DATOS DUROS (Edita esto con tus datos reales) ---
# ¡OJO! Pega aquí tu clave real del 15 de Noviembre, sin espacios.
MI_API_KEY_REAL = "sk_9155b7e4fc11480481b7f7cee0fbe845" 

# Tus datos exactos que vimos en las fotos:
MI_NUMERO_GUPSHUP = "573169060209"  # Tu número (source)
MI_NOMBRE_APP = "EDNETBOTIA"        # Tu nombre de app (src.name)
# ------------------------------------------------------------

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"🔍 LLEGÓ ALGO: {json.dumps(data)}") 
        
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')

        # RESPONDER A TODO (Si hay remitente, respondemos)
        if sender:
            # Mensaje de prueba
            respuesta = f"🦜 PRUEBA FINAL. Recibí: {text}"
            
            print(f"✅ Intentando responder a: {sender}")
            background_tasks.add_task(send_reply_hardcoded, sender, respuesta)
            
    except Exception as e:
        print(f"🔥 ERROR LEYENDO: {e}")
    
    return {"status": "ok"}

def send_reply_hardcoded(phone, text):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": MI_API_KEY_REAL # Usamos la variable directa de arriba
    }
    
    data = {
        "channel": "whatsapp",
        "source": MI_NUMERO_GUPSHUP, # 57316...
        "destination": phone,
        "message": json.dumps({"type": "text", "text": text}),
        "src.name": MI_NOMBRE_APP    # EDNETBOTIA
    }
    
    print(f"📤 Enviando con: Source={MI_NUMERO_GUPSHUP} | Name={MI_NOMBRE_APP}")
    
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📬 RESULTADO FINAL: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"🔥 ERROR DE CONEXIÓN: {e}")