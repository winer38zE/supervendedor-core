import os
import google.generativeai as genai # <--- CAMBIO IMPORTANTE: Librería Gratis
from .database import SupabaseDB
# Si tienes los otros agentes (Saga, Patriarca), mantenlos importados
# pero por hoy aseguraremos que Zeus funcione directo.
# from .agents.guardian_security import SystemGuardian 
# from .agents.grand_patriarch import GrandPatriarch
# from .agents.saga_strategist import SagaStrategist

class ZeusOrchestrator:
    def __init__(self):
        # 1. Autenticación GRATUITA (API Key)
        self.setup_free_auth()
        
        # 2. Conexión a Memoria (Supabase)
        self.db = SupabaseDB()
        
        # Si tienes el guardián, descomenta esto:
        # self.guardian = SystemGuardian()
        
        print("⚡ ZEUS (MODO GRATUITO) INICIADO...")

        # 3. Modelo Base (Gemini 1.5 Flash es rápido y gratis)
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def setup_free_auth(self):
        """Conecta con Google usando la llave gratuita"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ Faltan la GEMINI_API_KEY en Railway")
            return
        
        genai.configure(api_key=api_key)
        print("✅ Conexión Gratuita Exitosa.")

    def process_message(self, user_id, user_message, chat_history_unused):
        print(f"📩 Mensaje de {user_id}: {user_message}")

        # 1. Base de Datos (CRM)
        lead = self.db.get_or_create_lead(user_id)
        self.db.save_message(lead['id'], "user", user_message)
        
        try:
            # Recuperar historial breve para contexto
            history_data = self.db.get_chat_history(lead['id'], limit=5)
            
            # Formatear historial para Gemini Flash
            formatted_history = []
            for msg in history_data:
                role = "user" if msg["role"] == "user" else "model"
                formatted_history.append({"role": role, "parts": [msg["content"]]})

            # Iniciar chat
            chat = self.model.start_chat(history=formatted_history)
            response = chat.send_message(user_message)
            response_text = response.text
            
        except Exception as e:
            print(f"🔥 Error Zeus: {e}")
            response_text = "Estoy reiniciando mis sistemas neuronales. Intenta de nuevo."

        # 2. Guardar y Responder
        self.db.save_message(lead['id'], "assistant", response_text)
        return {"type": "text", "content": response_text}