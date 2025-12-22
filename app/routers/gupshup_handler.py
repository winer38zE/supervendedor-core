import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv() # Carga las variables del archivo .env

# --- DATOS DE TU NEGOCIO (ED NET PRO) ---
NOMBRE_EMPRESA = "ED NET PRO"
PRODUCTO_1 = "Tarjetas NFC Inteligentes (Tu contacto en un toque)"
PRODUCTO_2 = "Super Vendedor IA (Automatización de ventas 24/7)"
from ..database import SupabaseDB  # <--- Fix the import, since database is one folder up
TONO = "Innovador, tecnológico, directo y persuasivo. Usa emojis 🚀🛡️🏛️."

SYSTEM_PROMPT = f"""
Eres el Arquitecto Jefe de Ventas de {NOMBRE_EMPRESA}.
Vendes:
1. {PRODUCTO_1}: Ideales para networking de alto nivel.
2. {PRODUCTO_2}: Sistemas de IA como yo para escalar negocios.
Objetivo: Calificar al cliente y cerrar una cita técnica o la venta directa.
Tono: {TONO}.
REGLA: Respuestas breves, máximo 60 palabras. Siempre enfócate en el retorno de inversión y la tecnología de punta.
"""

class ZeusOrchestrator:
    def __init__(self):
        print("🧠 INICIANDO ZEUS PARA ED NET PRO...")
        
        # 1. Conectar Cerebro (Usando variable de entorno)
        api_key = os.getenv("GEMINI_API_KEY") 
        if not api_key:
            # Fallback por si aún no creas el .env (No recomendado para producción)
            api_key = "TU_LLAVE_AQUI" 
            
        genai.configure(api_key=api_key)
        
        # 2. Conectar Memoria (Supabase)
        self.db = SupabaseDB()
        
        # 3. Configurar Modelo
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT 
        )

    def process_message(self, user_id, user_message, chat_history_unused):
        print(f"🤔 Pensando respuesta para: {user_message}")
        
        # A. Obtener o crear Lead y recuperar historial real
        lead = self.db.get_or_create_lead(user_id)
        
        # --- CARGA DE MEMORIA REAL ---
        # Aquí pedimos los últimos mensajes a Supabase para que Zeus no olvide
        raw_history = self.db.get_messages(lead['id'], limit=10) 
        formatted_history = []
        for msg in raw_history:
            role = "user" if msg['role'] == "user" else "model"
            formatted_history.append({"role": role, "parts": [msg['content']]})
        
        # B. Generar respuesta con historial
        try:
            chat = self.model.start_chat(history=formatted_history)
            response = chat.send_message(user_message)
            response_text = response.text
            
            # C. Guardar en base de datos
            self.db.save_message(lead['id'], "user", user_message)
            self.db.save_message(lead['id'], "assistant", response_text)
            
            return {"type": "text", "content": response_text}
            
        except Exception as e:
            print(f"🔥 ERROR CEREBRAL: {e}")
            return {"type": "text", "content": "Estamos optimizando mis sistemas de IA. ¿En qué puedo ayudarte con tus Tarjetas NFC?"}