"""
app/agents/hermes_negotiator.py
────────────────────────────────────────────────────────────────────────────────
Hermes — Negociador estratégico ZOPA (Zona de Acuerdo POsible).

Lógica matemática: calcula contraoferta óptima dentro de la ZOPA.
Lógica verbal: genera la respuesta persuasiva con IA.

Prioridad de motor para generate_response:
  1. Claude Sonnet  (ANTHROPIC_API_KEY) — mejor calidad de cierre
  2. Groq Llama3    (GROQ_API_KEY)
  3. Gemini Flash   (GEMINI_API_KEY)
  4. Texto plantilla (sin API key)
"""

import os


class HermesNegotiator:

    def __init__(self, target_price: float, reserve_price: float):
        self.target_price  = target_price   # precio ideal
        self.reserve_price = reserve_price  # precio mínimo aceptable

    # ── Matemática ZOPA ───────────────────────────────────────────────────────

    def calculate_counter_offer(self, user_offer: float) -> dict:
        """Calcula la contraoferta usando la Zona de Acuerdo POsible."""
        if user_offer >= self.target_price:
            return {"action": "accept", "price": user_offer, "diff": 0}

        if user_offer < self.reserve_price:
            # Fuera del límite — concesión mínima para mantener el diálogo
            counter = self.reserve_price + (self.target_price - self.reserve_price) * 0.1
            return {"action": "reject_counter", "price": round(counter, 2),
                    "diff": self.target_price - counter}

        # En ZOPA — ceder la mitad de la diferencia restante
        concession   = (self.target_price - user_offer) * 0.5
        counter_price = self.target_price - concession
        return {"action": "counter", "price": round(counter_price, 2),
                "diff": self.target_price - counter_price}

    # ── Voz persuasiva ────────────────────────────────────────────────────────

    def generate_response(self, decision: dict) -> str:
        """Da voz persuasiva a la decisión matemática usando IA."""
        prompt = self._build_prompt(decision)

        # ── Intento 1: Claude Sonnet ─────────────────────────────────────────
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=anthropic_key)
                msg    = client.messages.create(
                    model      = "claude-sonnet-4-6",
                    max_tokens = 300,
                    system     = (
                        "Eres Hermes, un negociador experto en ventas B2B. "
                        "Respuestas cortas (máx 3 oraciones), directas y persuasivas. "
                        "Hablas en español colombiano informal pero profesional."
                    ),
                    messages   = [{"role": "user", "content": prompt}],
                )
                return msg.content[0].text.strip()
            except Exception as e:
                print(f"[Hermes] Claude error: {e}")

        # ── Intento 2: Groq ──────────────────────────────────────────────────
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq
                client     = Groq(api_key=groq_key)
                completion = client.chat.completions.create(
                    model       = "llama3-8b-8192",
                    messages    = [
                        {"role": "system", "content":
                         "Eres Hermes, negociador experto en ventas B2B. "
                         "Respuestas cortas y persuasivas en español colombiano."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature = 0.7,
                    max_tokens  = 300,
                )
                return completion.choices[0].message.content.strip()
            except Exception as e:
                print(f"[Hermes] Groq error: {e}")

        # ── Intento 3: Gemini ─────────────────────────────────────────────────
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model    = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt)
                return response.text.strip()
            except Exception as e:
                print(f"[Hermes] Gemini error: {e}")

        # ── Fallback: texto plantilla ─────────────────────────────────────────
        return self._template_response(decision)

    def _build_prompt(self, decision: dict) -> str:
        action = decision.get("action", "counter")
        price  = decision.get("price", self.target_price)

        if action == "accept":
            return "El cliente aceptó el precio. Escribe una respuesta entusiasta para cerrar la venta ahora mismo."
        elif action == "reject_counter":
            return (
                f"El cliente ofreció muy poco. Rechaza respetuosamente y propón ${price} USD "
                "como concesión exclusiva y urgente."
            )
        else:
            return (
                f"Propón ${price} USD al cliente. Usa el principio de reciprocidad: "
                "tu haces el esfuerzo, ahora es su turno de cerrar el trato."
            )

    def _template_response(self, decision: dict) -> str:
        action = decision.get("action", "counter")
        price  = decision.get("price", self.target_price)

        if action == "accept":
            return (
                "Excelente decision. Vamos a cerrar esto ahora — "
                "confirma los datos y queda listo."
            )
        elif action == "reject_counter":
            return (
                f"Entiendo tu posicion. Por ser un cliente nuevo, "
                f"puedo llegar hasta ${price} USD — es mi mejor oferta."
            )
        else:
            return (
                f"Mira, yo cedo de mi lado y llego a ${price} USD. "
                "Ahora es tu turno — cerramos hoy?"
            )
