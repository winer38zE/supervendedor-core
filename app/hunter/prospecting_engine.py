"""
Hunter: Motor de Prospección Multi-tenant con Inteligencia B2B
Busca negocios, los audita con IA (Intent Data) y los guarda en Supabase.
"""

import os
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx

from app.database.supabase_client import get_client

# ─────────────────────────────────────────────
# Constantes de scoring
# ─────────────────────────────────────────────
SCORE_WEIGHTS = {
    "tiene_telefono":   2,
    "tiene_sitio_web":  1,
    "rating_alto":      2,
    "rating_medio":     1,
    "reviews_alto":     2,
    "reviews_medio":    1,
    "tiene_fotos":      1,
    "tiene_horario":    1,
}
MAX_SCORE = sum(SCORE_WEIGHTS.values()) 

# ─────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────
class ProspectingEngine:
    def __init__(self, tenant_id: str):
        if not tenant_id or len(tenant_id) > 100:
            raise ValueError("tenant_id inválido")
        self.tenant_id = tenant_id

        self.db = get_client()
        if not self.db:
            print("⚠️ Hunter: No hay conexión a base de datos (PocketBase/Supabase)")

        self.gmaps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
        self.llm_key   = os.environ.get("GOOGLE_API_KEY", "") # Key para Gemini

    # ─────────────────────────────────────────
    # 1. Motor de Inteligencia (LLM Check)
    # ─────────────────────────────────────────
    async def llm_check(self, prompt: str) -> str:
        """Llamada a la API de Gemini para análisis de intención."""
        if not self.llm_key:
            return "NO" # Fallback si no hay key
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.llm_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, timeout=10)
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                return "NO"

    async def verificar_intencion(self, nombre_negocio: str, categoria: str) -> bool:
        """Usa IA para decidir si este negocio es 'high intent'."""
        prompt = f"""
        Eres un analista B2B. Evalúa al negocio: {nombre_negocio} ({categoria}).
        ¿Tiene señales de necesitar servicios digitales urgentes (ej: web desactualizada, pocos reviews, negocio local)?
        Responde solo 'SI' o 'NO'.
        """
        respuesta = await self.llm_check(prompt) 
        return "SI" in respuesta.upper()

    # ─────────────────────────────────────────
    # 2. Búsqueda en Google Maps
    # ─────────────────────────────────────────
    async def buscar_en_google_maps(self, query: str, ciudad: str, max_results: int = 20) -> list[dict]:
        if not self.gmaps_key:
            return self._mock_resultados(query, ciudad, max_results)

        prospectos = []
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": f"{query} en {ciudad}", "language": "es", "key": self.gmaps_key}

        async with httpx.AsyncClient(timeout=15) as client:
            while len(prospectos) < max_results:
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    print(f"❌ Google Maps error: {e}")
                    break

                for lugar in data.get("results", []):
                    prospectos.append(self._normalizar_lugar(lugar, ciudad))
                    if len(prospectos) >= max_results:
                        break

                next_token = data.get("next_page_token")
                if not next_token or len(prospectos) >= max_results:
                    break

                await asyncio.sleep(2)
                params = {"pagetoken": next_token, "key": self.gmaps_key}

        return prospectos

    def _normalizar_lugar(self, lugar: dict, ciudad: str) -> dict:
        geometry = lugar.get("geometry", {}).get("location", {})
        return {
            "lugar_id": lugar.get("place_id", ""),
            "nombre_negocio": lugar.get("name", ""),
            "direccion": lugar.get("formatted_address", ""),
            "telefono": lugar.get("formatted_phone_number", ""),
            "sitio_web": lugar.get("website", ""),
            "rating": lugar.get("rating"),
            "total_reviews": lugar.get("user_ratings_total", 0),
            "categoria": ", ".join(lugar.get("types", [])[:3]),
            "latitud": geometry.get("lat"),
            "longitud": geometry.get("lng"),
            "ciudad": ciudad,
            "pais": "CO",
            "horario": lugar.get("opening_hours"),
            "fotos": [p.get("photo_reference", "") for p in lugar.get("photos", [])[:3]],
            "metadata": {},
        }

    # ─────────────────────────────────────────
    # 3. Scoring y Guardado
    # ─────────────────────────────────────────
    def calificar_lead(self, prospecto: dict) -> int:
        score = 0
        rating = prospecto.get("rating") or 0
        total_reviews = prospecto.get("total_reviews") or 0
        if prospecto.get("telefono"): score += SCORE_WEIGHTS["tiene_telefono"]
        if prospecto.get("sitio_web"): score += SCORE_WEIGHTS["tiene_sitio_web"]
        if rating >= 4.0: score += SCORE_WEIGHTS["rating_alto"]
        elif rating >= 3.0: score += SCORE_WEIGHTS["rating_medio"]
        if total_reviews >= 50: score += SCORE_WEIGHTS["reviews_alto"]
        elif total_reviews >= 10: score += SCORE_WEIGHTS["reviews_medio"]
        if prospecto.get("fotos"): score += SCORE_WEIGHTS["tiene_fotos"]
        if prospecto.get("horario"): score += SCORE_WEIGHTS["tiene_horario"]
        normalizado = max(1, round((score / MAX_SCORE) * 10))
        return min(normalizado, 10)

    def guardar_prospecto(
        self,
        prospecto: dict,
        lead_score: int,
        shaka: Optional[dict] = None,
    ) -> dict:
        if not self.db:
            return {"status": "sin_db"}

        now = datetime.now(timezone.utc).isoformat()
        probability_score = (shaka or {}).get("probability_score", 0)
        shaka_meta = shaka or {}

        # Upsert en prospectos_hunter
        prospecto_row = {
            "tenant_id": self.tenant_id,
            "nombre_negocio": prospecto["nombre_negocio"],
            "direccion": prospecto.get("direccion", ""),
            "telefono": prospecto.get("telefono", ""),
            "sitio_web": prospecto.get("sitio_web", ""),
            "rating": prospecto.get("rating"),
            "total_reviews": prospecto.get("total_reviews", 0),
            "categoria": prospecto.get("categoria", ""),
            "latitud": prospecto.get("latitud"),
            "longitud": prospecto.get("longitud"),
            "lugar_id": prospecto.get("lugar_id", ""),
            "ciudad": prospecto.get("ciudad", ""),
            "procesado": False,
            "metadata": {
                "probability_score": probability_score,
                "shaka_channel": shaka_meta.get("channel"),
                "shaka_opening_line": shaka_meta.get("opening_line"),
            },
            "created_at": now,
        }
        res = self.db.table("prospectos_hunter").upsert(prospecto_row, on_conflict="tenant_id,lugar_id").execute()
        prospecto_id = res.data[0]["id"] if res.data else None

        # Score final: blend Maps + Shaka probability (1-10)
        if probability_score:
            blended_score = max(1, min(10, round(lead_score * 0.5 + probability_score * 10 * 0.5)))
        else:
            blended_score = lead_score

        # Upsert en leads_crm
        lead_row = {
            "tenant_id": self.tenant_id,
            "nombre": prospecto["nombre_negocio"],
            "telefono": prospecto.get("telefono", ""),
            "empresa": prospecto["nombre_negocio"],
            "lead_score": blended_score,
            "estado": "nuevo",
            "fuente": "hunter",
            "metadata": {
                "probability_score": probability_score,
                "shaka": shaka_meta,
                "prospecto_hunter_id": prospecto_id,
            },
            "created_at": now,
            "updated_at": now,
        }
        self.db.table("leads_crm").upsert(lead_row, on_conflict="tenant_id,telefono").execute()
        return {"status": "guardado", "probability_score": probability_score, "lead_score": blended_score}

    # ─────────────────────────────────────────
    # 4. Pipeline Inteligente (Actualizado)
    # ─────────────────────────────────────────
    async def ejecutar_campana(self, query: str, ciudad: str, max_results: int = 20) -> dict:
        from app.agents.shaka_quantum_prospector import ShakaQuantumProspector

        print(f"🔍 [{self.tenant_id}] Iniciando campaña: '{query}' en {ciudad}")
        prospectos = await self.buscar_en_google_maps(query, ciudad, max_results)
        shaka = ShakaQuantumProspector()

        resultados = []
        for p in prospectos:
            es_high_intent = await self.verificar_intencion(p["nombre_negocio"], p["categoria"])

            score = self.calificar_lead(p)
            if es_high_intent:
                score = min(score + 2, 10)

            shaka_result = shaka.score_hunter_lead(p, score)
            save_result = self.guardar_prospecto(p, score, shaka=shaka_result)

            resultados.append({
                "nombre": p["nombre_negocio"],
                "lead_score": save_result.get("lead_score", score),
                "probability_score": shaka_result.get("probability_score"),
                "shaka_channel": shaka_result.get("channel"),
                "opening_line": shaka_result.get("opening_line"),
                "intent": es_high_intent,
            })

        return {"status": "completado", "total": len(resultados), "detalles": resultados}

    # ─────────────────────────────────────────
    # 5. Métodos auxiliares
    # ─────────────────────────────────────────
    def obtener_leads_calientes(self, score_minimo: int = 7, limit: int = 50) -> list[dict]:
        if not self.db: return []
        res = self.db.table("leads_crm").select("*").eq("tenant_id", self.tenant_id).gte("lead_score", score_minimo).execute()
        return res.data or []

    def obtener_prospectos(self, ciudad: Optional[str] = None, limit: int = 100) -> list[dict]:
        if not self.db: return []
        query = self.db.table("prospectos_hunter").select("*").eq("tenant_id", self.tenant_id).order("created_at", desc=True).limit(limit)
        if ciudad: query = query.eq("ciudad", ciudad)
        return query.execute().data or []

    def marcar_prospecto_procesado(self, prospecto_id: str) -> bool:
        if not self.db: return False
        self.db.table("prospectos_hunter").update({"procesado": True}).eq("id", prospecto_id).execute()
        return True

    def _mock_resultados(self, query: str, ciudad: str, n: int) -> list[dict]:
        return [{"nombre_negocio": f"{query} Mock {i}", "ciudad": ciudad} for i in range(n)]