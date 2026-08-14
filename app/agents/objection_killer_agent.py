"""
app/agents/objection_killer_agent.py
────────────────────────────────────────────────────────────────────────────────
Manejo de objeciones complejas en WhatsApp / chat de ventas.

Intercepta: precio alto, desconfianza en envíos, "voy a consultar", etc.
Usa márgenes del catalog_bridge para descuentos autorizados.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from app.fallback_responses import objection_fallback

logger = logging.getLogger(__name__)


_OBJECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("precio_alto", [
        "muy caro", "caro", "costoso", "no alcanza", "mucho dinero",
        "mas barato", "más barato", "bajale", "rebaja", "descuento",
    ]),
    ("desconfianza_envio", [
        "no confio", "no confío", "estafa", "fraude", "seguro",
        "confiable", "envio", "envío", "llega", "garantia", "garantía",
    ]),
    ("consultar", [
        "consultar", "preguntar", "pensarlo", "lo pienso", "despues",
        "después", "mas tarde", "más tarde", "vuelvo", "decido",
    ]),
    ("competencia", [
        "shein", "mercado libre", "otra tienda", "vi mas barato",
        "vi más barato", "en otro lado",
    ]),
]


class ObjectionKillerAgent:
    """Detecta objeciones y genera contraargumentos accionables."""

    def detect_objection(self, message: str) -> Optional[str]:
        msg = message.lower()
        for objection_type, keywords in _OBJECTION_PATTERNS:
            if any(kw in msg for kw in keywords):
                return objection_type
        return None

    def handle(
        self,
        message: str,
        zopa: dict[str, float],
        product_title: str = "",
    ) -> Optional[dict[str, Any]]:
        """
        Returns None si no hay objeción.
        Else: {objection_type, response, authorized_price?, tactic}
        """
        objection = self.detect_objection(message)
        if not objection:
            return None

        target = zopa.get("target_price", 0)
        reserve = zopa.get("reserve_price", 0)
        titulo = product_title or zopa.get("titulo", "este producto")

        if objection == "precio_alto":
            # Descuento autorizado: hasta 8% sobre target, nunca bajo reserve
            authorized = max(reserve, round(target * 0.92, 0))
            response = self._llm_or_template(
                objection,
                f"Producto: {titulo}. Precio lista ${target:,.0f}. "
                f"Precio especial autorizado ${authorized:,.0f} COP. "
                f"Pago contra entrega Cúcuta. Máx 3 oraciones persuasivas.",
                self._template_precio(authorized, titulo),
                {"titulo": titulo, "authorized": authorized, "target_price": target},
            )
            return {
                "objection_type": objection,
                "response": response,
                "authorized_price": authorized,
                "tactic": "descuento_margen_autorizado",
            }

        if objection == "desconfianza_envio":
            response = self._llm_or_template(
                objection,
                f"Cliente desconfía del envío para {titulo}. "
                f"Responde con: pago contra entrega, revisa antes de pagar, "
                f"cobertura Cúcuta y envío nacional. Español CO.",
                self._template_envio(titulo),
                {"titulo": titulo, "target_price": target},
            )
            return {
                "objection_type": objection,
                "response": response,
                "tactic": "garantia_contraentrega",
            }

        if objection == "consultar":
            response = self._llm_or_template(
                objection,
                f"Cliente dice que va a consultar sobre {titulo}. "
                f"Crea urgencia suave: reserva 24h, stock limitado. Español colombiano.",
                self._template_consultar(titulo, target),
                {"titulo": titulo, "target_price": target},
            )
            return {
                "objection_type": objection,
                "response": response,
                "tactic": "reserva_temporal_24h",
            }

        if objection == "competencia":
            response = self._llm_or_template(
                objection,
                f"Cliente compara {titulo} con competencia. "
                f"Destaca entrega local, contraentrega, WhatsApp. Precio ${target:,.0f} COP.",
                self._template_competencia(titulo, target),
                {"titulo": titulo, "target_price": target},
            )
            return {
                "objection_type": objection,
                "response": response,
                "tactic": "diferenciacion_local",
            }

        return None

    def _llm_or_template(
        self,
        objection: str,
        prompt: str,
        fallback: str,
        ctx: dict,
    ) -> str:
        try:
            openai_key = os.environ.get("OPENAI_API_KEY", "")
            if openai_key:
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=openai_key)
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=200,
                    )
                    return completion.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"[ObjectionKiller] OpenAI error: {e}")

            gemini_key = os.environ.get("GEMINI_API_KEY", "")
            if gemini_key:
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=gemini_key)
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    return model.generate_content(prompt).text.strip()
                except Exception as e:
                    logger.error(f"[ObjectionKiller] Gemini error: {e}")

            groq_key = os.environ.get("GROQ_API_KEY", "")
            if groq_key:
                try:
                    from groq import Groq
                    client = Groq(api_key=groq_key)
                    completion = client.chat.completions.create(
                        model="llama3-8b-8192",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=200,
                    )
                    return completion.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"[ObjectionKiller] Groq error: {e}")
        except Exception as e:
            logger.error(f"[ObjectionKiller] LLM pipeline error: {e}")

        logger.error(f"[ObjectionKiller] Fallback plantilla para objeción: {objection}")
        return objection_fallback(objection, ctx) if ctx else fallback

    def _template_precio(self, authorized: float, titulo: str) -> str:
        return (
            f"Te entiendo — por ser cliente directo te dejo *{titulo}* en "
            f"*${authorized:,.0f} COP* (precio especial de hoy).\n"
            f"Pago *solo cuando recibes* en Cúcuta. ¿Te lo aparto?"
        )

    def _template_envio(self, titulo: str) -> str:
        return (
            f"Totalmente válido desconfiar. Por eso trabajamos *pago contra entrega*: "
            f"recibes *{titulo}*, lo revisas y *ahí pagas*.\n"
            f"Entregas en Cúcuta y envío nacional con seguimiento por WhatsApp."
        )

    def _template_consultar(self, titulo: str, target: float) -> str:
        return (
            f"Claro, tómate tu tiempo. Solo te *aparto {titulo}* por 24 horas "
            f"al precio de *${target:,.0f} COP* para que no suba.\n"
            f"Escríbeme cuando decidas — sin compromiso."
        )

    def _template_competencia(self, titulo: str, target: float) -> str:
        return (
            f"En Shein esperas semanas; con nosotros *{titulo}* llega rápido "
            f"a Cúcuta con *pago al recibir* por *${target:,.0f} COP*.\n"
            f"Tienes soporte directo por WhatsApp — ¿te envío la ficha con foto?"
        )


_killer_instance: Optional[ObjectionKillerAgent] = None


def get_objection_killer() -> ObjectionKillerAgent:
    global _killer_instance
    if _killer_instance is None:
        _killer_instance = ObjectionKillerAgent()
    return _killer_instance
