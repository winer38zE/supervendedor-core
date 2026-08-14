"""
app/agents/hermes_negotiator.py — Negociador ZOPA + voz persuasiva con fallback.
"""

import logging
import os

from app.fallback_responses import hermes_fallback

logger = logging.getLogger(__name__)


class HermesNegotiator:

    def __init__(self, target_price: float, reserve_price: float):
        self.target_price = target_price
        self.reserve_price = reserve_price

    def calculate_counter_offer(self, user_offer: float) -> dict:
        if user_offer >= self.target_price:
            return {"action": "accept", "price": user_offer, "diff": 0}

        if user_offer < self.reserve_price:
            counter = self.reserve_price + (self.target_price - self.reserve_price) * 0.1
            return {
                "action": "reject_counter",
                "price": round(counter, 2),
                "diff": self.target_price - counter,
            }

        concession = (self.target_price - user_offer) * 0.5
        counter_price = self.target_price - concession
        return {
            "action": "counter",
            "price": round(counter_price, 2),
            "diff": self.target_price - counter_price,
        }

    def generate_response(self, decision: dict) -> str:
        prompt = self._build_prompt(decision)

        try:
            text = self._call_llm(prompt)
            if text:
                return text
        except Exception as e:
            logger.error(f"[Hermes] LLM falló completamente: {e}")

        logger.error("[Hermes] Usando fallback de plantilla — revisar créditos/API keys")
        return hermes_fallback(decision)

    def _call_llm(self, prompt: str) -> str:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                msg = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=300,
                    system=(
                        "Eres Hermes, negociador de ventas. "
                        "Respuestas cortas en español colombiano."
                    ),
                    messages=[{"role": "user", "content": prompt}],
                )
                return msg.content[0].text.strip()
            except Exception as e:
                logger.error(f"[Hermes] Claude error: {e}")

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Eres Hermes, negociador de ventas CO."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=300,
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"[Hermes] OpenAI error: {e}")

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=groq_key)
                completion = client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"[Hermes] Groq error: {e}")

        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                return model.generate_content(prompt).text.strip()
            except Exception as e:
                logger.error(f"[Hermes] Gemini error: {e}")

        return ""

    def _build_prompt(self, decision: dict) -> str:
        action = decision.get("action", "counter")
        price = decision.get("price", self.target_price)

        if action == "accept":
            return "El cliente aceptó el precio. Respuesta entusiasta para cerrar ahora."
        if action == "reject_counter":
            return (
                f"Cliente ofreció muy poco. Propón ${price:,.0f} COP como concesión exclusiva."
            )
        return (
            f"Propón ${price:,.0f} COP al cliente. Máx 3 oraciones, español colombiano."
        )
