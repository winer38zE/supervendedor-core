import os
import sys
import base64
import json
import vertexai
from vertexai.generative_models import GenerativeModel

# Importaciones de agentes
from .agents.athena_analyst import AthenaAnalyst
from .agents.hermes_negotiator import HermesNegotiator
from .agents.hephaestus_creator import HephaestusCreator
from .agents.shaka_quantum_prospector import ShakaQuantumProspector

class ZeusOrchestrator:
    def __init__(self):
        # 1. Autenticación (Si falla, el sistema se detiene AQUÍ)
        self.project_id = self.setup_google_auth()
        
        # 2. Invocación de los Dioses (Solo si hay autenticación)
        print("⚡ Invocando a los Dioses del Olimpo...")
        self.athena = AthenaAnalyst()
        self.hermes = HermesNegotiator(target_price=100, reserve_price=80)
        self.hephaestus = HephaestusCreator()
        self.shaka = ShakaQuantumProspector()
        
        # 3. El Cerebro de Zeus
        self.zeus_model = GenerativeModel("gemini-1.5-pro")

    def setup_google_auth(self):
        """Desencripta la llave de Railway y conecta con Vertex AI"""
        print("🔐 Iniciando secuencia de autenticación...")
        
        b64_key = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
        
        # Verificación 1: ¿Existe la variable?
        if not b64_key:
            print("❌ ERROR CRÍTICO: La variable GOOGLE_CREDENTIALS_BASE64 está vacía o no existe en Railway.")
            sys.exit(1) # Detener el programa
            
        try:
            # Limpieza de la llave (quitar espacios o saltos de línea accidentales)
            b64_key_clean = b64_key.strip().replace('\n', '').replace(' ', '')
            
            # Decodificación
            key_json_str = base64.b64decode(b64_key_clean).decode('utf-8')
            key_info = json.loads(key_json_str)
            
            # Guardamos temporalmente
            with open("temp_key.json", "w") as f:
                json.dump(key_info, f)
            
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "temp_key.json"
            project_id = key_info["project_id"]
            
            # Inicializamos Vertex AI
            vertexai.init(project=project_id, location="us-central1")
            print(f"✅ Conexión con Vertex AI exitosa. Proyecto: {project_id}")
            return project_id

        except Exception as e:
            print(f"🔥 ERROR DE AUTENTICACIÓN: {str(e)}")
            print("TIP: Verifica que tu código Base64 en Railway sea correcto y corresponda a un JSON válido.")
            sys.exit(1) # Detener el programa

    def process_message(self, user_id, user_message, chat_history):
        chat = self.zeus_model.start_chat()
        response = chat.send_message(user_message)
        return {"type": "text", "content": response.text}

    def initiate_quantum_prospecting(self, lead_data):
        return self.shaka.collapse_wave_function(lead_data.get('lead_id'), 0.8)