# app/orchestrator.py — Single Tenant
import os
from .config import settings


class ZeusOrchestrator:
    """
    Orquestador principal de mensajes.
    Usa Groq (Llama 3) como motor rápido; cae a Claude si no hay Groq key.
    Carga el system prompt localmente sin depender de S3.
    """

    def __init__(self):
        self._groq_client = None
        self._anthropic_client = None

    def _get_groq(self):
        if self._groq_client is None and settings.GROQ_API_KEY:
            from groq import Groq
            self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
        return self._groq_client

    def _get_anthropic(self):
        if self._anthropic_client is None and settings.ANTHROPIC_API_KEY:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._anthropic_client

    def process_message(
        self,
        user_id: str,
        user_message: str,
        chat_history: list,
        client_id: str = "default",
    ) -> dict:
        from app.main import get_client_context
        system_prompt = get_client_context(client_id)

        # ── Intento 1: Groq Llama3 (velocidad extrema) ───────────────────────
        groq = self._get_groq()
        if groq:
            try:
                completion = groq.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_message},
                    ],
                    temperature=0.7,
                )
                return {"type": "text", "content": completion.choices[0].message.content}
            except Exception as e:
                print(f"[Zeus] Groq error: {e}")

        # ── Intento 2: Claude Haiku (fallback) ───────────────────────────────
        ant = self._get_anthropic()
        if ant:
            try:
                msg = ant.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=512,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                return {"type": "text", "content": msg.content[0].text}
            except Exception as e:
                print(f"[Zeus] Claude error: {e}")

        return {"type": "text", "content": "Un momento, estoy procesando tu mensaje..."}
