"""
app/agents/athena_analyst.py
────────────────────────────────────────────────────────────────────────────────
Athena — Analista de Sentimiento y Momentum de Ventas.

Prioridad de motor:
  1. Google Gemini  (GEMINI_API_KEY)  — google-generativeai
  2. Claude Haiku   (ANTHROPIC_API_KEY)
  3. Groq Llama3    (GROQ_API_KEY)
  4. Análisis por palabras clave (sin API key)

Calcula:
  - Sentiment:  0.0 (hostil) → 1.0 (listo para comprar)
  - Velocity:   qué tan rápido responde el prospecto
  - Momentum:   sentiment × velocity → HOT / WARM / CHURN_RISK
"""

import os
from datetime import datetime


class AthenaAnalyst:

    def analyze_sentiment(self, text: str) -> float:
        """Devuelve un float 0.0–1.0 indicando intención de compra."""
        prompt = (
            f"Analiza el siguiente texto de un prospecto de ventas. "
            f"Devuelve SOLO un número decimal del 0.0 (totalmente sin interés o hostil) "
            f"al 1.0 (muy interesado, listo para comprar): '{text}'"
        )

        # ── Intento 1: Gemini ─────────────────────────────────────────────────
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model    = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt)
                return float(response.text.strip())
            except Exception as e:
                print(f"[Athena] Gemini error: {e}")

        # ── Intento 2: Claude Haiku ───────────────────────────────────────────
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                msg    = client.messages.create(
                    model      = "claude-haiku-4-5-20251001",
                    max_tokens = 10,
                    messages   = [{"role": "user", "content": prompt}],
                )
                return float(msg.content[0].text.strip())
            except Exception as e:
                print(f"[Athena] Claude error: {e}")

        # ── Intento 3: Groq ───────────────────────────────────────────────────
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq
                client     = Groq(api_key=groq_key)
                completion = client.chat.completions.create(
                    model       = "llama3-8b-8192",
                    messages    = [{"role": "user", "content": prompt}],
                    max_tokens  = 10,
                    temperature = 0.0,
                )
                return float(completion.choices[0].message.content.strip())
            except Exception as e:
                print(f"[Athena] Groq error: {e}")

        # ── Fallback: palabras clave ──────────────────────────────────────────
        return self._keyword_sentiment(text)

    def _keyword_sentiment(self, text: str) -> float:
        """Heurística simple basada en palabras clave en español."""
        text_lower = text.lower()

        high_interest = [
            "interesado", "interesante", "cuanto cuesta", "cuánto cuesta",
            "precio", "disponible", "cuando", "cuándo", "quiero", "necesito",
            "me gusta", "perfecto", "excelente", "claro", "si", "sí",
            "hablamos", "reunión", "reunion", "cita",
        ]
        low_interest = [
            "no me interesa", "no gracias", "ocupado", "después", "despues",
            "luego", "no necesito", "ya tengo", "no quiero", "para nada",
            "deje de", "quíteme", "quiteme", "spam",
        ]

        score = 0.5
        for kw in high_interest:
            if kw in text_lower:
                score = min(1.0, score + 0.15)
        for kw in low_interest:
            if kw in text_lower:
                score = max(0.0, score - 0.25)
        return round(score, 2)

    def calculate_velocity(
        self,
        last_bot_time: datetime,
        user_reply_time: datetime,
    ) -> float:
        """Velocidad de respuesta: cuanto más rápido responde, mayor score."""
        diff_seconds = max(1, (user_reply_time - last_bot_time).total_seconds())
        if diff_seconds <= 30:
            return 1.0
        velocity = 1 / (0.02 * diff_seconds + 1)
        return max(0.1, round(velocity, 2))

    def get_sales_momentum(
        self,
        last_user_message: str,
        last_interaction_time: datetime,
        current_time: datetime,
    ) -> dict:
        """
        Combina sentimiento y velocidad → dictamen estratégico.
        Returns: {status, momentum, advice}
        """
        sentiment = self.analyze_sentiment(last_user_message)
        velocity  = self.calculate_velocity(last_interaction_time, current_time)
        momentum  = round(sentiment * velocity, 3)

        if momentum > 0.65:
            return {
                "status":   "HOT_LEAD",
                "momentum": momentum,
                "advice":   "Cierre urgente. Hermes entra ahora.",
            }
        elif momentum < 0.25:
            return {
                "status":   "CHURN_RISK",
                "momentum": momentum,
                "advice":   "Prospecto frio. Seguimiento liviano.",
            }
        else:
            return {
                "status":   "WARM_LEAD",
                "momentum": momentum,
                "advice":   "Continuar dialogo de ventas.",
            }
