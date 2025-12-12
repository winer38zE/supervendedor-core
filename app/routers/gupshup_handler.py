# app/routers/gupshup_handler.py
# --- CODIGO NUCLEAR DE DIAGNOSTICO ---
from fastapi import APIRouter, Request, BackgroundTasks
import requests
import json

router = APIRouter()

# 🛑 PEGA TU API KEY AQUÍ ENTRE LAS COMILLAS 🛑
API_KEY_SEGURA = "sk_9155b7e4fc11480481b7f7cee0fbe845" 

@router.get("/gupshup/webhook")
async def verify():
    return "OK"

@router.post("/gupshup/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        # 1. Capturar el cuerpo crudo (RAW)
        body = await request.body()
        data = json.loads(body)
        print(f"📥 [ENTRADA] GUPSHUP DIJO: {json.dumps(data)}")

        # 2. Desglosar datos (sin miedo a errores)
        if data.get('type') == 'message':
            payload = data.get('payload', {})
            
            # DATOS DEL CLIENTE
            telefono_cliente = payload.get('source')
            texto_cliente = payload.get('payload', {}).get('text')
            
            # DATOS DEL BOT (CRÍTICO: Leemos a quién iba dirigido el mensaje)
            # Gupshup nos dice a qué numero escribieron. Usamos ese mismo para responder.
            telefono_bot = payload.get('destination') 
            
            print(f"🕵️ DETECTADO: Cliente {telefono_cliente} escribió a Bot {telefono_bot}")

            if texto_cliente:
                # Responder inmediatamente
                background_tasks.add_task(responder_a_la_fuerza, telefono_cliente, telefono_bot, texto_cliente)
        
        else:
            print(f"⚠️ Evento ignorado (No es mensaje de texto): {data.get('type')}")

    except Exception as e:
        print(f"🔥 ERROR CATASTRÓFICO: {e}")

    return {"status": "received"}

def responder_a_la_fuerza(cliente, bot_numero, texto):
    url = "https://api.gupshup.io/sm/api/v1/msg"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": API_KEY_SEGURA
    }
    
    mensaje = f"🤖 SOY UN ROBOT TESTARUDO. Recibí: {texto}"
    
    # TRUCO MAESTRO: Usamos el mismo número de destino como origen
    # Y usamos el nombre de app EDNETBOTIA fijo
    data = {
        "channel": "whatsapp",
        "source": bot_numero,     # Usamos el número que Gupshup nos dio
        "destination": cliente,
        "message": json.dumps({"type": "text", "text": mensaje}),
        "src.name": "EDNETBOTIA"  # Tu nombre de app real
    }
    
    print(f"📤 [SALIDA] Intentando responder de {bot_numero} a {cliente}...")
    
    try:
        r = requests.post(url, headers=headers, data=data)
        print(f"📬 [RESULTADO] Código: {r.status_code}")
        print(f"📜 [RESPUESTA GUPSHUP]: {r.text}")
    except Exception as e:
        print(f"💀 ERROR DE CONEXIÓN: {e}")