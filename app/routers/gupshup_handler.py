# app/routers/gupshup_handler.py
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# --- 📝 TUS DATOS FIJOS (Edita solo la clave) ---
# 1. EL NOMBRE (Documento 1)
NOMBRE_APP = "EDNETBOTIA" 

# 2. EL NÚMERO (Documento 2)
NUMERO_TEL = "573169060209"

# 3. LA CLAVE (Bórrala y pega la tuya del 15 de Noviembre)
API_KEY = "sk_9155b7e4fc11480481b7f7cee0fbe845"
# ------------------------------------------------

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        print(f"📥 LLEGÓ: {json.dumps(data)}") 
        
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')

        if sender:
            # Responde confirmando que funcionó
            mensaje = f"✅ ¡IDENTIDAD CONFIRMADA! Soy {NOMBRE_APP} en el número {NUMERO_TEL}"
            background_tasks.add_task(enviar_mensaje_fijo, sender, mensaje)

    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}

def enviar_mensaje_fijo(cliente, texto):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": API_KEY  # Usa la clave fija de arriba
    }
    
    # AQUÍ ESTÁ EL ARREGLO: Entregamos los dos documentos por separado
    data = {
        "channel": "whatsapp",
        "source": NUMERO_TEL,     # Aquí va el 57316...
        "destination": cliente,
        "message": json.dumps({"type": "text", "text": texto}),
        "src.name": NOMBRE_APP    # Aquí va EDNETBOTIA
    }
    
    print(f"📤 Enviando con: {NUMERO_TEL} y {NOMBRE_APP}")
    
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📬 RESULTADO: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"💀 ERROR CONEXION: {e}")