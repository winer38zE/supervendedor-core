# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 🔐 DATOS FIJOS (LOS VEO PERFECTOS EN TU FOTO) ---
# Usamos esto directo para que no falle la lectura de variables
NOMBRE_APP_FIJO = "EDNETBOTIA" 
NUMERO_FIJO = "573169060209"

# ⚠️ BORRA ESTO Y PEGA TU API KEY DEL 15 NOV AQUÍ ⚠️
API_KEY_FIJA = "sk_9155b7e4fc11480481b7f7cee0fbe845"
# -----------------------------------------------------

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"📥 LLEGÓ DATA: {json.dumps(data)}") 
        
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')

        # Si hay un remitente, respondemos
        if sender:
            mensaje = f"✅ ¡PRUEBA EXITOSA! Soy {NOMBRE_APP_FIJO} y mi numero es {NUMERO_FIJO}"
            background_tasks.add_task(enviar_mensaje_blindado, sender, mensaje)

    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}

def enviar_mensaje_blindado(cliente, texto):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": API_KEY_FIJA
    }
    
    # AQUÍ ESTÁ EL SECRETO: Usamos las dos llaves por separado
    data = {
        "channel": "whatsapp",
        "source": NUMERO_FIJO,      # 57316...
        "destination": cliente,
        "message": json.dumps({"type": "text", "text": texto}),
        "src.name": NOMBRE_APP_FIJO # EDNETBOTIA
    }
    
    print(f"📤 Enviando con: {NUMERO_FIJO} y {NOMBRE_APP_FIJO}")
    
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📬 RESULTADO FINAL: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"💀 ERROR CONEXIÓN: {e}")