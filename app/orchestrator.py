# app/orchestrator.py
import os
import google.generativeai as genai
from .database import SupabaseDB

# --- ZONA DE PERSONALIDAD (Aquí defines qué vende) ---
# Puedes cambiar esto rápido antes de mostrarle al cliente.

NOMBRE_EMPRESA = "Joyería El Diamante"
PRODUCTO = "Pulseras de Hilo Rojo y Oro Laminado"
PRECIO = "80.000 COP"
OFERTA = "Si llevas 2, el envío es gratis."
TONO = "Amable, usa emojis 💎 y sé breve."

SYSTEM_PROMPT = f"""
Eres el vendedor experto de {NOMBRE_EMPRESA}.
Vendes {PRODUCTO} a {PRECIO}.
Oferta: {OFERTA}.
Tono: {TONO}.
IMPORTANTE: Tu objetivo es cerrar la venta. Respuestas cortas (max 50 palabras).
"""
# -----------------------------------------------------

class ZeusOrchestrator:
    def __init__(self):
        # 1. Conectar Cerebro (Gemini)
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            print("⚡ ZEUS CONECTADO (Cerebro Listo)")
        
        # 2. Conectar Memoria (Supabase)
        self.db = SupabaseDB()
        
        # 3. Configurar Modelo (Con Instrucción de Sistema)
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT 
        )

    def process_message(self, user_id, user_message, chat_history_unused):
        # A. Guardar mensaje del usuario
        lead = self.db.get_or_create_lead(user_id)
        self.db.save_message(lead['id'], "user", user_message)
        
        # B. Pensar respuesta
        try:
            # Recuperar historial real de la base de datos
            history = self.db.get_chat_history(lead['id'])
            
            # Formatear para Gemini
            formatted_history = []
            for m in history:
                role = "user" if m["role"] == "user" else "model"
                formatted_history.append({"role": role, "parts": [m["content"]]})
            
            # Iniciar chat con memoria
            chat = self.model.start_chat(history=formatted_history)
            response = chat.send_message(user_message)
            response_text = response.text
            
        except Exception as e:
            print(f"🔥 Error cerebral: {e}")
            response_text = "¡Ups! Estoy reiniciando mis neuronas. Escríbeme en 1 minuto."

        # C. Guardar y devolver respuesta
        self.db.save_message(lead['id'], "assistant", response_text)
        return {"type": "text", "content": response_text}