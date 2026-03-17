# app/orchestrator.py
import os
from groq import Groq # pip install groq
from .config import settings

class ZeusOrchestrator:
    def __init__(self):
        # Usamos Groq por su velocidad extrema
        self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
        
    def process_message(self, user_id, user_message, chat_history):
        try:
            # Llamada rápida a Llama 3 en Groq
            completion = self.groq_client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": "Eres el cerrador de ED NET PRO. Sé breve y directo."},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
            )
            return {"type": "text", "content": completion.choices[0].message.content}
        except Exception as e:
            return {"type": "text", "content": "Optimizando... escribe en un momento."}