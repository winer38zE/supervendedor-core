# app/orchestrator.py
import os
import google.generativeai as genai
from .database import SupabaseDB  # <--- AHORA SÍ FUNCIONARÁ PORQUE CREASTE LA DB

class ZeusOrchestrator:
    def __init__(self):
        # 1. Autenticación GRATIS (Gemini Key)
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            print("⚡ ZEUS CONECTADO (Modo Gratis con Memoria)")
        
        # 2. Conectar Memoria (Supabase)
        self.db = SupabaseDB()
        
        # 3. Modelo Gratis
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def process_message(self, user_id, user_message, chat_history_unused):
        # A. Identificar cliente en DB
        lead = self.db.get_or_create_lead(user_id)
        self.db.save_message(lead['id'], "user", user_message)
        
        # B. Generar respuesta con historial
        try:
            history = self.db.get_chat_history(lead['id'])
            formatted_history = [{"role": "user" if m["role"]=="user" else "model", "parts": [m["content"]]} for m in history]
            
            chat = self.model.start_chat(history=formatted_history)
            response = chat.send_message(user_message)
            response_text = response.text
        except Exception as e:
            response_text = "Reiniciando sistemas..."
            print(e)

        # C. Guardar respuesta
        self.db.save_message(lead['id'], "assistant", response_text)
        return {"type": "text", "content": response_text}