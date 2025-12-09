import os
import base64
import json
import vertexai
from vertexai.generative_models import GenerativeModel

# Importamos a los Dioses (Agentes)
# Asegúrate de que las carpetas existan en app/agents/
from .agents.athena_analyst import AthenaAnalyst
from .agents.hermes_negotiator import HermesNegotiator
from .agents.hephaestus_creator import HephaestusCreator
from .agents.shaka_quantum_prospector import ShakaQuantumProspector

class ZeusOrchestrator:
    def __init__(self):
        # 1. Autenticación (Esta es la línea que fallaba antes)
        self.setup_google_auth()
        
        # 2. Invocación de los Dioses
        self.athena = AthenaAnalyst()
        self.hermes = HermesNegotiator(target_price=100, reserve_price=80)
        self.hephaestus = HephaestusCreator()
        self.shaka = ShakaQuantumProspector()
        
        # 3. El Cerebro de Zeus
        self.zeus_model = GenerativeModel("gemini-1.5-pro")

    def setup_google_auth(self):
        """Desencripta la llave de Railway y conecta con Vertex AI"""
        print("⚡ Iniciando secuencia de autenticación del Olimpo...")
        try:
            b64_key = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
            if b64_key:
                # Limpiamos cualquier espacio en blanco accidental
                b64_key = b64_key.strip()
                key_json = base64.b64decode(b64_key).decode('utf-8')
                key_info = json.loads(key_json)
                
                # Guardamos temporalmente para que Google lo lea
                with open("temp_key.json", "w") as f:
                    json.dump(key_info, f)
                
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "temp_key.json"
                
                # Inicializamos Vertex AI con el ID del proyecto
                vertexai.init(project=key_info["project_id"], location="us-central1")
                print("⚡ Conexión con el Olimpo (Vertex AI) establecida.")
            else:
                print("⚠️ Error: No se encontró la variable GOOGLE_CREDENTIALS_BASE64")
        except Exception as e:
            print(f"🔥 Error crítico de autenticación: {e}")

    def process_message(self, user_id, user_message, chat_history):
        """Cerebro Principal: Decide qué agente usar"""
        print(f"📩 Zeus procesando mensaje de {user_id}: {user_message}")
        
        # Lógica simplificada de respuesta directa
        chat = self.zeus_model.start_chat()
        response = chat.send_message(user_message)
        return {"type": "text", "content": response.text}

    def initiate_quantum_prospecting(self, lead_data):
        """Activa a Shaka para prospección"""
        return self.shaka.collapse_wave_function(lead_data.get('lead_id'), 0.8)