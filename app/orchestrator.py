# app/orchestrator.py
import os
import google.generativeai as genai
from .database import SupabaseDB

# --- ZONA DE CREDENCIALES (PARA QUE NO FALLE) ---
# Pega aquí tu API Key de Google AI Studio (la que empieza por AIza...)
MI_GEMINI_KEY = "AIzaSyCaXONqjBbKshAE1zUdK5-jLuc5MEz1lD8" 

# --- ZONA DE PERSONALIDAD ---
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

class ZeusOrchestrator:
    def __init__(self):
        # 1. Conectar Cerebro (Directo, sin variables de entorno para probar)
        print("🧠 Conectando Cerebro Gemini...")
        try:
            genai.configure(api_key=MI_GEMINI_KEY)
            print("⚡ ZEUS CONECTADO (Cerebro Listo)")
        except Exception as e:
            print(f"💀 Error conectando Gemini: {e}")
        
        # 2. Conectar Memoria (Supabase)
        self.db = SupabaseDB()
        
        # 3. Configurar Modelo
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT 
        )

    def process_message(self, user_id, user_message, chat_history_unused):
        # A. Guardar mensaje del usuario
        lead = self.db.get_or_create_lead(user_id)
        self.db.save_message(lead['id'], "user", user_message)
        
        # B. Pensar respuesta
        response_text = ""
        try:
            # Recuperar historial
            history = self.db.get_chat_history(lead['id'])
            
            # Formatear historial para Gemini
            formatted_history = []
            # TRUCO: Excluimos el último mensaje si es igual al actual para no confundir a Gemini
            for m in history[:-1]: 
                role = "user" if m["role"] == "user" else "model"
                formatted_history.append({"role": role, "parts": [m["content"]]})
            
            # Iniciar chat
            chat = self.model.start_chat(history=formatted_history)
            response = chat.send_message(user_message)
            response_text = response.text
            
        except Exception as e:
            print(f"🔥 Error cerebral: {e}")
            response_text = "¡Ups! Se me cruzaron los cables. ¿Me repites?"

        # C. Guardar y devolver respuesta
        if response_text:
            self.db.save_message(lead['id'], "assistant", response_text)
            
        return {"type": "text", "content": response_text}