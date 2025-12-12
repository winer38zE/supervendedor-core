# app/routers/gupshup_handler.py
# --- CODIGO DE PRUEBA DE EMERGENCIA ---
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
        print(f"🔍 LLEGÓ ALGO: {json.dumps(data)}") # Ver todo lo que entra
        
        # Extraer datos sin filtros estrictos
        payload = data.get('payload', {})
        sender = payload.get('source')
        text = payload.get('payload', {}).get('text')
        
        # SI VEMOS UN TEXTO, RESPONDEMOS DE INMEDIATO
        if text:
            print(f"✅ MENSAJE DETECTADO: {text} de {sender}")
            # Respondemos directo (sin Gemini, sin DB)
            send_echo(sender, text)
        else:
            print("⚠️ No es texto (es un evento de sistema), lo ignoramos.")
            
    except Exception as e:
        print(f"🔥 ERROR: {e}")
    
    return {"status": "ok"}

def send_echo(phone, text):
    # FORZAMOS EL NOMBRE CORRECTO SEGUN TU FOTO
    src_name = "EDNETBOTIA" 
    
    url = "https://api.gupshup.io/sm/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": os.environ.get("GUPSHUP_API_KEY")
    }
    
    respuesta = f"🦜 PRUEBA EXITOSA. Recibí: {text}"
    
    data = {
        "channel": "whatsapp",
        "source": src_name,
        "destination": phone,
        "message": json.dumps({"type": "text", "text": respuesta}),
        "src.name": src_name
    }
    
    print(f"📤 Intentando responder a {phone} usando {src_name}...")
    r = requests.post(url, headers=headers, data=data)
    print(f"📬 Resultado Gupshup: {r.status_code} - {r.text}")