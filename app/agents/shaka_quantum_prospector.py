"""
app/agents/shaka_quantum_prospector.py
────────────────────────────────────────────────────────────────────────────────
Shaka — Prospector cuántico: probabilidad de compra + canal + línea de apertura.

Prioridad de motor:
  1. Gemini Flash  (GEMINI_API_KEY)
  2. Groq Llama3   (GROQ_API_KEY)
  3. Heurística por datos del lead (sin API)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


class ShakaQuantumProspector:
    def __init__(self, target_channel: str = "WhatsApp"):
        self.target_channel = target_channel

    def calculate_initial_probability(self, lead_data: dict[str, Any]) -> float:
        """
        Probabilidad inicial de compra (0.0–1.0) según perfil del prospecto.
        """
        data_str = json.dumps(lead_data, ensure_ascii=False)
        prompt = (
            f"Analiza el perfil de prospecto B2B: {data_str}. "
            f"Devuelve SOLO un decimal del 0.0 al 1.0 = probabilidad de compra ahora."
        )

        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                raw = model.generate_content(prompt).text.strip()
                return _clamp_probability(raw)
            except Exception as e:
                print(f"[Shaka] Gemini error: {e}")

        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=groq_key)
                completion = client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=10,
                    temperature=0.0,
                )
                return _clamp_probability(completion.choices[0].message.content.strip())
            except Exception as e:
                print(f"[Shaka] Groq error: {e}")

        return self._heuristic_probability(lead_data)

    def collapse_wave_function(self, lead_id: str, probability_score: float) -> dict:
        """Canal óptimo + línea de apertura según probabilidad."""
        if probability_score > 0.8:
            channel = "Direct_Call_Vapi"
        elif probability_score > 0.5:
            channel = "WhatsApp_Personalized"
        else:
            channel = "Email_RAG_Nurture"

        opening_line = self._generate_opening_line(lead_id, probability_score, channel)

        return {
            "lead_id": lead_id,
            "probability": round(probability_score, 3),
            "action": "PROSPECTAR_PROACTIVO",
            "channel": channel,
            "opening_line": opening_line,
        }

    def score_hunter_lead(self, prospecto: dict[str, Any], lead_score: int) -> dict:
        """
        Evalúa un prospecto Hunter y devuelve probability_score + metadata Shaka.
        Combina score Maps (1-10) con probabilidad IA.
        """
        lead_data = {
            "name": prospecto.get("nombre_negocio", ""),
            "source": "Google Maps Hunter",
            "category": prospecto.get("categoria", ""),
            "city": prospecto.get("ciudad", ""),
            "rating": prospecto.get("rating"),
            "reviews": prospecto.get("total_reviews", 0),
            "has_phone": bool(prospecto.get("telefono")),
            "has_website": bool(prospecto.get("sitio_web")),
            "maps_score": lead_score,
        }
        probability = self.calculate_initial_probability(lead_data)
        # Blend: 60% Shaka IA + 40% score normalizado Maps
        maps_norm = min(1.0, max(0.0, lead_score / 10))
        blended = round(probability * 0.6 + maps_norm * 0.4, 3)

        lead_id = prospecto.get("lugar_id") or prospecto.get("nombre_negocio", "lead")
        collapse = self.collapse_wave_function(lead_id, blended)
        collapse["probability_score"] = blended
        return collapse

    def _generate_opening_line(
        self, lead_id: str, probability_score: float, channel: str
    ) -> str:
        prompt = (
            f"Lead '{lead_id}' probabilidad {probability_score * 100:.0f}%. "
            f"Canal: {channel}. Escribe UNA línea de apertura B2B en español colombiano, "
            f"máximo 25 palabras, directa y profesional."
        )

        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                return model.generate_content(prompt).text.strip()
            except Exception:
                pass

        if probability_score > 0.7:
            return (
                "Hola, vi su negocio en Google y tengo una propuesta concreta "
                "para aumentar ventas esta semana. ¿Le interesa una llamada de 10 min?"
            )
        return (
            "Buenos días, trabajo con soluciones digitales para negocios locales. "
            "¿Le comparto una idea rápida sin compromiso?"
        )

    def _heuristic_probability(self, lead_data: dict[str, Any]) -> float:
        score = 0.25
        if lead_data.get("has_phone"):
            score += 0.15
        if lead_data.get("has_website"):
            score += 0.05
        rating = lead_data.get("rating") or 0
        if rating >= 4.0:
            score += 0.15
        reviews = lead_data.get("reviews") or 0
        if reviews >= 20:
            score += 0.1
        maps_score = lead_data.get("maps_score") or 0
        score += min(0.25, maps_score / 40)
        return round(min(1.0, score), 3)


def _clamp_probability(raw: str) -> float:
    m = re.search(r"(\d+\.?\d*)", raw.replace(",", "."))
    if not m:
        return 0.25
    val = float(m.group(1))
    if val > 1.0:
        val = val / 100.0
    return round(max(0.0, min(1.0, val)), 3)
