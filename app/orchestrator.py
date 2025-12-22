import os
import anthropic # Asegúrese de instalarlo: pip install anthropic
from .database import SupabaseDB
from dotenv import load_dotenv

load_dotenv()

class ZeusOrchestrator:
    def __init__(self):
        print("🧠 INICIANDO ZEUS CON CEREBRO ANTHROPIC...")
        # Carga la llave de Anthropic configurada en Railway
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.db = SupabaseDB()

    def process_message(self, user_id, user_message, chat_history_unused):
        # 1. Obtener historial de Supabase
        lead = self.db.get_or_create_lead(user_id)
        
        try:
            # 2. Llamada a Claude 3.5 Sonnet
            message = self.client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=150,
                system="Eres el Arquitecto de ED NET PRO. Vendes Tarjetas NFC e IA.",
                messages=[{"role": "user", "content": user_message}]
            )
            
            response_text = message.content[0].text
            self.db.save_message(lead['id'], "assistant", response_text)
            return {"type": "text", "content": response_text}
            
        except Exception as e:
            print(f"💀 ERROR ANTHROPIC: {e}")
            return {"type": "text", "content": "Optimizando sistemas..."}