# app/hunter/prospecting_engine.py
"""
Hunter: Motor de Prospección Multi-tenant
Busca negocios en Google Maps, los puntúa (1-10) y los guarda en Supabase.
Soporta 10,000 tenants gracias a RLS, índices y operaciones async.
"""

import os
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx
from supabase import create_client, Client

# ─────────────────────────────────────────────
# Constantes de scoring
# ─────────────────────────────────────────────
SCORE_WEIGHTS = {
    "tiene_telefono":   2,
    "tiene_sitio_web":  1,
    "rating_alto":      2,   # rating >= 4.0
    "rating_medio":     1,   # rating >= 3.0
    "reviews_alto":     2,   # total_reviews >= 50
    "reviews_medio":    1,   # total_reviews >= 10
    "tiene_fotos":      1,
    "tiene_horario":    1,
}
MAX_SCORE = sum(SCORE_WEIGHTS.values())  # 11 → normalizado a 10


# ─────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────
class ProspectingEngine:
    """
    Motor de prospección por tenant.
    Cada instancia está aislada a un tenant_id específico.

    Uso:
        engine = ProspectingEngine(tenant_id="cliente_abc")
        resultados = await engine.ejecutar_campana("restaurantes", "Medellín", max_results=20)
    """

    def __init__(self, tenant_id: str):
        if not tenant_id or len(tenant_id) > 100:
            raise ValueError("tenant_id inválido")
        self.tenant_id = tenant_id

        url  = os.environ.get("SUPABASE_URL", "")
        key  = os.environ.get("SUPABASE_KEY", "")
        self.db: Optional[Client] = None

        if url and key:
            try:
                self.db = create_client(url, key)
            except Exception as e:
                print(f"⚠️ Hunter: No se pudo conectar a Supabase: {e}")

        self.gmaps_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")

    # ─────────────────────────────────────────
    # 1. Búsqueda en Google Maps (Places API)
    # ─────────────────────────────────────────
    async def buscar_en_google_maps(
        self,
        query: str,
        ciudad: str,
        max_results: int = 20,
    ) -> list[dict]:
        """
        Busca negocios usando Google Places Text Search API.
        Retorna lista de prospectos crudos.
        """
        if not self.gmaps_key:
            print("⚠️ GOOGLE_MAPS_API_KEY no configurada. Retornando mock.")
            return self._mock_resultados(query, ciudad, max_results)

        prospectos = []
        url        = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params     = {
            "query":    f"{query} en {ciudad}",
            "language": "es",
            "key":      self.gmaps_key,
        }

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

                # Google requiere ~2s antes del siguiente page_token
                await asyncio.sleep(2)
                params = {"pagetoken": next_token, "key": self.gmaps_key}

        return prospectos

    def _normalizar_lugar(self, lugar: dict, ciudad: str) -> dict:
        """Transforma la respuesta de Google en el esquema interno."""
        geometry  = lugar.get("geometry", {}).get("location", {})
        return {
            "lugar_id":       lugar.get("place_id", ""),
            "nombre_negocio": lugar.get("name", ""),
            "direccion":      lugar.get("formatted_address", ""),
            "telefono":       lugar.get("formatted_phone_number", ""),
            "sitio_web":      lugar.get("website", ""),
            "rating":         lugar.get("rating"),
            "total_reviews":  lugar.get("user_ratings_total", 0),
            "categoria":      ", ".join(lugar.get("types", [])[:3]),
            "latitud":        geometry.get("lat"),
            "longitud":       geometry.get("lng"),
            "ciudad":         ciudad,
            "pais":           "CO",
            "horario":        lugar.get("opening_hours"),
            "fotos":          [p.get("photo_reference", "") for p in lugar.get("photos", [])[:3]],
            "metadata":       {},
        }

    # ─────────────────────────────────────────
    # 2. Scoring (1-10)
    # ─────────────────────────────────────────
    def calificar_lead(self, prospecto: dict) -> int:
        """
        Asigna un puntaje 1-10 al prospecto basado en
        completitud y señales de calidad del negocio.
        """
        score = 0
        rating        = prospecto.get("rating") or 0
        total_reviews = prospecto.get("total_reviews") or 0

        if prospecto.get("telefono"):                       score += SCORE_WEIGHTS["tiene_telefono"]
        if prospecto.get("sitio_web"):                      score += SCORE_WEIGHTS["tiene_sitio_web"]
        if rating   >= 4.0:                                 score += SCORE_WEIGHTS["rating_alto"]
        elif rating >= 3.0:                                 score += SCORE_WEIGHTS["rating_medio"]
        if total_reviews >= 50:                             score += SCORE_WEIGHTS["reviews_alto"]
        elif total_reviews >= 10:                           score += SCORE_WEIGHTS["reviews_medio"]
        if prospecto.get("fotos"):                          score += SCORE_WEIGHTS["tiene_fotos"]
        if prospecto.get("horario"):                        score += SCORE_WEIGHTS["tiene_horario"]

        # Normalizar a escala 1-10
        normalizado = max(1, round((score / MAX_SCORE) * 10))
        return min(normalizado, 10)

    # ─────────────────────────────────────────
    # 3. Guardado en Supabase (multi-tenant)
    # ─────────────────────────────────────────
    def guardar_prospecto(self, prospecto: dict, lead_score: int) -> dict:
        """
        Guarda en prospectos_hunter y crea/actualiza el registro en leads_crm.
        Todas las operaciones filtran por tenant_id.
        """
        if not self.db:
            print("⚠️ Supabase no disponible. Saltando guardado.")
            return {"status": "sin_db", "prospecto": prospecto}

        now = datetime.now(timezone.utc).isoformat()

        # ── 3a. Upsert en prospectos_hunter ──────────────────────────
        prospecto_row = {
            "tenant_id":      self.tenant_id,
            "nombre_negocio": prospecto["nombre_negocio"],
            "direccion":      prospecto.get("direccion", ""),
            "telefono":       prospecto.get("telefono", ""),
            "sitio_web":      prospecto.get("sitio_web", ""),
            "rating":         prospecto.get("rating"),
            "total_reviews":  prospecto.get("total_reviews", 0),
            "categoria":      prospecto.get("categoria", ""),
            "latitud":        prospecto.get("latitud"),
            "longitud":       prospecto.get("longitud"),
            "lugar_id":       prospecto.get("lugar_id", ""),
            "ciudad":         prospecto.get("ciudad", ""),
            "pais":           prospecto.get("pais", "CO"),
            "horario":        prospecto.get("horario"),
            "fotos":          prospecto.get("fotos", []),
            "metadata":       prospecto.get("metadata", {}),
            "procesado":      False,
            "created_at":     now,
        }

        prospecto_res = (
            self.db.table("prospectos_hunter")
            .upsert(prospecto_row, on_conflict="tenant_id,lugar_id")
            .execute()
        )
        prospecto_id = prospecto_res.data[0]["id"] if prospecto_res.data else None

        # ── 3b. Upsert en leads_crm ───────────────────────────────────
        lead_row = {
            "tenant_id":  self.tenant_id,
            "nombre":     prospecto["nombre_negocio"],
            "telefono":   prospecto.get("telefono", ""),
            "empresa":    prospecto["nombre_negocio"],
            "fuente":     "google_maps",
            "lead_score": lead_score,
            "estado":     "nuevo",
            "notas":      f"Importado desde Google Maps. Rating: {prospecto.get('rating')} | Reviews: {prospecto.get('total_reviews')}",
            "metadata":   {"prospecto_id": str(prospecto_id), "lugar_id": prospecto.get("lugar_id")},
            "created_at": now,
            "updated_at": now,
        }

        lead_res = (
            self.db.table("leads_crm")
            .upsert(lead_row, on_conflict="tenant_id,telefono")
            .execute()
        )

        return {
            "status":       "guardado",
            "prospecto_id": prospecto_id,
            "lead_id":      lead_res.data[0]["id"] if lead_res.data else None,
            "lead_score":   lead_score,
        }

    # ─────────────────────────────────────────
    # 4. Pipeline completo
    # ─────────────────────────────────────────
    async def ejecutar_campana(
        self,
        query: str,
        ciudad: str,
        max_results: int = 20,
    ) -> dict:
        """
        Pipeline completo:
        1. Busca en Google Maps
        2. Califica cada prospecto
        3. Guarda en Supabase
        Retorna resumen de la campaña.
        """
        print(f"🔍 [{self.tenant_id}] Iniciando campaña: '{query}' en {ciudad}")

        prospectos = await self.buscar_en_google_maps(query, ciudad, max_results)
        if not prospectos:
            return {"status": "sin_resultados", "total": 0}

        resultados  = []
        score_total = 0

        for p in prospectos:
            score = self.calificar_lead(p)
            score_total += score
            res = self.guardar_prospecto(p, score)
            resultados.append({
                "nombre":     p["nombre_negocio"],
                "ciudad":     p["ciudad"],
                "telefono":   p.get("telefono", ""),
                "lead_score": score,
                "status":     res["status"],
            })

        promedio = round(score_total / len(resultados), 1) if resultados else 0

        print(f"✅ [{self.tenant_id}] Campaña finalizada: {len(resultados)} prospectos | Score promedio: {promedio}")
        return {
            "status":           "completado",
            "tenant_id":        self.tenant_id,
            "query":            query,
            "ciudad":           ciudad,
            "total":            len(resultados),
            "score_promedio":   promedio,
            "prospectos":       resultados,
        }

    # ─────────────────────────────────────────
    # 5. Consultas de solo lectura
    # ─────────────────────────────────────────
    def obtener_leads_calientes(self, score_minimo: int = 7, limit: int = 50) -> list[dict]:
        """Retorna leads con score >= score_minimo para este tenant."""
        if not self.db:
            return []
        try:
            res = (
                self.db.table("leads_crm")
                .select("*")
                .eq("tenant_id", self.tenant_id)
                .gte("lead_score", score_minimo)
                .order("lead_score", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            print(f"❌ obtener_leads_calientes: {e}")
            return []

    def obtener_prospectos(self, ciudad: Optional[str] = None, limit: int = 100) -> list[dict]:
        """Lista prospectos de Google Maps para este tenant."""
        if not self.db:
            return []
        try:
            query = (
                self.db.table("prospectos_hunter")
                .select("*")
                .eq("tenant_id", self.tenant_id)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if ciudad:
                query = query.eq("ciudad", ciudad)
            return query.execute().data or []
        except Exception as e:
            print(f"❌ obtener_prospectos: {e}")
            return []

    def marcar_prospecto_procesado(self, prospecto_id: str) -> bool:
        """Marca un prospecto como procesado (ya contactado/trabajado)."""
        if not self.db:
            return False
        try:
            self.db.table("prospectos_hunter").update(
                {"procesado": True}
            ).eq("id", prospecto_id).eq("tenant_id", self.tenant_id).execute()
            return True
        except Exception as e:
            print(f"❌ marcar_prospecto_procesado: {e}")
            return False

    # ─────────────────────────────────────────
    # 6. Mock para desarrollo sin API Key
    # ─────────────────────────────────────────
    def _mock_resultados(self, query: str, ciudad: str, n: int) -> list[dict]:
        """Genera prospectos de prueba cuando no hay GOOGLE_MAPS_API_KEY."""
        return [
            {
                "lugar_id":       f"mock_{i}_{uuid.uuid4().hex[:8]}",
                "nombre_negocio": f"{query.title()} {ciudad} #{i+1}",
                "direccion":      f"Calle {i+1} #{10+i}-{20+i}, {ciudad}",
                "telefono":       f"+5731{i:08d}",
                "sitio_web":      f"https://ejemplo{i}.com" if i % 2 == 0 else "",
                "rating":         round(3.0 + (i % 20) / 10, 1),
                "total_reviews":  (i + 1) * 7,
                "categoria":      query,
                "latitud":        6.2442 + i * 0.001,
                "longitud":       -75.5812 + i * 0.001,
                "ciudad":         ciudad,
                "pais":           "CO",
                "horario":        {"open_now": True} if i % 3 != 0 else None,
                "fotos":          [f"ref_{i}"] if i % 2 == 0 else [],
                "metadata":       {"mock": True},
            }
            for i in range(min(n, 20))
        ]
