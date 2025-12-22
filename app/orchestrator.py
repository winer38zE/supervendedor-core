# app/orchestrator.py
import os
import google.generativeai as genai
from .database import SupabaseDB

# --- 🛑 ZONA DE LLAVE MAESTRA (EDITA ESTO) 🛑 ---
# Pega aquí tu API KEY de Google (la que empieza por AIza...)
MI_GEMINI_KEY = "AIzaSyCaXONqjBbKshAE1zUdK5-jLuc5MEz1lD8"
# ------------------------------------------------

# --- DATOS DEL NEGOCIO ---
NOMBRE_EMPRESA = "Joyería El Diamante"
PRODUCTO = "Pulseras de Hilo Rojo y Oro Laminado"
PRECIO = "80.000 COP"
OFERTA = "Si llevas 2, el envío es gratis."
TONO = "Amable, usa emojis 💎 y sé breve."

from fastapi import APIRouter

router = APIRouter()

# Endpoint para procesar mensajes
@router.post("/olympus/zeus/process")
def process(user_id: str, user_message: str):
    orchestrator = ZeusOrchestrator()
    result = orchestrator.process_message(user_id, user_message, chat_history_unused=[])
    return result

SYSTEM_PROMPT = f"""
Eres el vendedor experto de {NOMBRE_EMPRESA}.
Vendes {PRODUCTO} a {PRECIO}.
Oferta: {OFERTA}.
Tono: {TONO}.
IMPORTANTE: Tu objetivo es cerrar la venta. Respuestas cortas (max 50 palabras).
"""

class ZeusOrchestrator:
    def __init__(self):
        print("🧠 INICIANDO ZEUS...")
        
        # 1. Conectar Cerebro (Directo)
        try:
            genai.configure(api_key=MI_GEMINI_KEY)
            print("⚡ ZEUS CONECTADO (Cerebro Listo con Llave Directa)")
        except Exception as e:
            print(f"💀 ERROR CRÍTICO CONECTANDO GEMINI: {e}")
        
        # 2. Conectar Memoria
        self.db = SupabaseDB()
        
        # 3. Configurar Modelo
        self.model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT 
        )

    def process_message(self, user_id, user_message, chat_history_unused):
        print(f"🤔 Pensando respuesta para: {user_message}")
        
        # A. Guardar mensaje usuario
        lead = self.db.get_or_create_lead(user_id)
        self.db.save_message(lead['id'], "user", user_message)
        
        response_text = ""
        
        # B. Generar respuesta
        try:
            # Historial (Truco: Usamos historial vacío por ahora para probar rápido)
            chat = self.model.start_chat(history=[])
            response = chat.send_message(user_message)
            response_text = response.text
            print(f"💡 Idea generada: {response_text}")
            
        except Exception as e:
            print(f"🔥 ERROR CEREBRAL AL PENSAR: {e}")
            response_text = "¡Hola! Estoy reiniciando mis sistemas. ¿Me repites?"

        # C. Guardar respuesta
        if response_text:
            import os
            import anthropic

            # Configurar el cliente de Anthropic con la variable de entorno
            anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
            if not anthropic_api_key:
                print("💀 ERROR: Falta la variable de entorno ANTHROPIC_API_KEY")
                response_text = "Lo siento, hay un error con mi sistema de IA. Intenta más tarde."
            else:
                try:
                    client = anthropic.Anthropic(api_key=anthropic_api_key)
                    message_history = []

                    # Puedes traer historial real aquí si lo deseas

                    # Claude espera una lista de dicts {role: "user"/"assistant", content: str}
                    # Pregunta y contexto del sistema
                    system_content = SYSTEM_PROMPT
                    message_history.append({"role": "user", "content": user_message})

                    response = client.messages.create(
                        model="claude-3.5-sonnet-20240620",
                        max_tokens=320,
                        system=system_content,
                        messages=message_history
                    )
                    response_text = response.content[0].text
                except Exception as e:
                    print(f"🔥 ERROR CEREBRAL AL PENSAR (Anthropic): {e}")
                    response_text = "¡Hola! Estoy reiniciando mis sistemas. ¿Me repites?"

            # Guarda la respuesta generada por Claude
            self.db.save_message(lead['id'], "assistant", response_text)
            
        return {"type": "text", "content": response_text}