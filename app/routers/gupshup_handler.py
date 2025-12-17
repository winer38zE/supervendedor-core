import requests
import json
import os # Para usar variables de entorno de Railway

# --- CONFIGURACIÓN (REEMPLAZA ESTOS VALORES EN TU Railway SECRETS) ---
GUPHSUP_API_KEY = os.environ.get("zgov8ynqbughsixwkmygxbhym9uwybwf")
GUPHSUP_API_ENDPOINT = "https://api.gupshup.io/sm/api/v1/msg" # VERIFICA ESTO EN TU DOC
GUPHSUP_APP_NAME = "EDNETBOTIA" # O el número fuente

def send_whatsapp_message(destination_number, gemini_response_text):
    # 1. Headers para autenticación y tipo de contenido
    headers = {
        "Content-Type": "application/json",
        "apikey": GUPHSUP_API_KEY # Autenticación de Gupshup
    }

    # 2. Cuerpo (Payload) del mensaje: La estructura JSON que Gupshup espera
    # Asegúrate de que esta estructura coincida con la documentación de tu imagen.
    payload = {
        "channel": "whatsapp", # Siempre 'whatsapp'
        "source": GUPHSUP_APP_NAME, # Tu número o identificador de App Gupshup
        "destination": destination_number, # El número al que le vamos a responder
        "message": {
            "type": "text",
            "text": gemini_response_text # El texto generado por Gemini
        }
    }

    # 3. Hacer la llamada POST a Gupshup
    try:
        response = requests.post(
            GUPHSUP_API_ENDPOINT,
            headers=headers,
            data=json.dumps(payload)
        )
        response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        
        # Opcional: Loggear la respuesta para depuración
        print(f"Respuesta de Gupshup: {response.status_code}")
        print(f"Detalles de Gupshup: {response.text}")
        
    except requests.exceptions.RequestException as e:
        print(f"ERROR al enviar mensaje por Gupshup: {e}")
        # Loggea el payload completo si el error ocurre antes del envío
        print(f"Payload enviado: {json.dumps(payload)}")
        
# ----------------------------------------------------------------------
# LÓGICA PRINCIPAL (Donde recibes el webhook)

@app.route('/gupshup_webhook', methods=['POST'])
def handle_webhook():
    data = request.get_json()
    
    # 1. RESPUESTA INMEDIATA (CLAVE)
    response_to_gupshup = jsonify({'status': 'ok'})
    response_to_gupshup.status_code = 200 # Asegura el 200 OK inmediato
    
    # *** Aquí inicia el procesamiento asíncrono o de segundo plano ***
    
    try:
        # 2. Extracción de datos (Ajusta la ruta de extracción según tu JSON entrante)
        user_number = data.get('payload').get('sender').get('phone') # Ejemplo de ruta común
        user_message = data.get('payload').get('text') # Ejemplo de ruta común
        
        if not user_message:
            return response_to_gupshup # Si no hay texto, solo respondemos 200 y salimos

        # 3. LLAMADA A GEMINI (TU FUNCIÓN)
        gemini_response = tu_funcion_de_gemini(user_message)
        
        # 4. ENVÍO DEL MENSAJE DE VUELTA (USANDO LA NUEVA FUNCIÓN)
        send_whatsapp_message(user_number, gemini_response)
        
    except Exception as e:
        print(f"Error en el flujo principal después de 200 OK: {e}")
        
    # 5. RETORNO DE LA RESPUESTA INMEDIATA
    return response_to_gupshup

# ----------------------------------------------------------------------