"""
app/services/content_remix_service.py
────────────────────────────────────────────────────────────────────────────────
Ingeniería inversa de contenido viral + remix comercial con LLM.

Integración: OpenAI / Anthropic vía llm_router + Gemini como fallback.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.content.crud import create_generated_script, create_outlier, get_profile
from app.content.exceptions import ContentLLMError, ContentNotFoundError, ContentValidationError
from app.content.models import GeneratedScript, ViralOutlier
from app.content.schemas import (
    ContentStructure,
    OutlierAnalyzeRequest,
    OutlierAnalyzeResponse,
    ScriptGenerateRequest,
    ScriptGenerateResponse,
)
from app.services.llm_router import get_llm_router

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)
_LLM_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = int(os.getenv("CONTENT_LLM_CACHE_TTL_SECONDS", "86400"))


class ContentRemixService:
    """
    Servicio central del módulo Catchwave-style:
      - Calcula outlier_score y engagement_rate
      - Extrae Hook / Tensión / Resolución con LLM
      - Reescribe guiones comerciales con nivel de remix configurable
    """

    OUTLIER_THRESHOLD = float(os.getenv("CONTENT_OUTLIER_THRESHOLD", "1.5"))
    COMPOSITE_THRESHOLD = float(os.getenv("CONTENT_COMPOSITE_THRESHOLD", "1.2"))
    DEFAULT_LLM = os.getenv("CONTENT_DEFAULT_LLM", "openai")

    @staticmethod
    def calculate_engagement_rate(views: int, likes: int, comments: int, shares: int) -> float:
        if views <= 0:
            return 0.0
        interactions = likes + comments + shares
        return round((interactions / views) * 100, 4)

    @classmethod
    def calculate_outlier_score(cls, views: int, baseline_views: int) -> float:
        if baseline_views <= 0:
            baseline_views = max(views, 1)
        return round(views / baseline_views, 4)

    @classmethod
    def calculate_composite_score(
        cls,
        views: int,
        baseline_views: int,
        engagement_rate: float,
    ) -> float:
        """
        Score único para decidir si vale la pena gastar tokens LLM.
        views/baseline (60%) + engagement normalizado (40%).
        """
        view_ratio = views / max(baseline_views, 1)
        eng_norm = min(engagement_rate / 10.0, 1.0)
        return round(view_ratio * 0.6 + eng_norm * 0.4, 4)

    @classmethod
    def passes_quality_gate(
        cls,
        composite_score: float,
        *,
        simulate: bool = False,
        force: bool = False,
    ) -> bool:
        if simulate or force:
            return True
        return composite_score >= cls.COMPOSITE_THRESHOLD

    def resolve_baseline_views(
        self,
        db: Session,
        payload: OutlierAnalyzeRequest,
    ) -> int:
        if payload.baseline_views and payload.baseline_views > 0:
            return payload.baseline_views

        if payload.profile_id:
            profile = get_profile(db, payload.profile_id)
            if not profile:
                raise ContentNotFoundError(f"Perfil '{payload.profile_id}' no encontrado")
            if profile.avg_views > 0:
                return profile.avg_views

        return max(payload.metrics.views, 1)

    def extract_structure(
        self,
        *,
        caption: Optional[str],
        transcript: Optional[str],
        platform: str,
        metrics_summary: str,
        simulate: bool = False,
    ) -> ContentStructure:
        if simulate:
            return ContentStructure(
                hook="¿Sabías que el 80% de las marcas pierde ventas por no usar este gancho?",
                tension="La mayoría copia contenido genérico sin entender por qué un reel explota.",
                resolution="Aplica esta estructura en 3 pasos y convierte views en leads calificados.",
                analysis_notes="Estructura simulada para pruebas — sin LLM.",
            )

        source_text = (transcript or caption or "").strip()
        if not source_text:
            raise ContentValidationError(
                "Se requiere 'caption' o 'transcript' para extraer la estructura del video"
            )

        system_prompt = (
            "Eres un estratega de contenido viral especializado en ingeniería inversa "
            "de reels de Instagram y TikTok para equipos de ventas B2C.\n"
            "Analiza el contenido y devuelve SOLO un JSON válido (sin markdown) con estas claves:\n"
            "  hook: gancho inicial que detiene el scroll (1-2 frases)\n"
            "  tension: conflicto, problema o curiosidad que mantiene atención (2-3 frases)\n"
            "  resolution: payoff, revelación o CTA implícito (2-3 frases)\n"
            "  analysis_notes: breve nota sobre por qué funcionó este formato\n"
            "Responde en español."
        )
        user_message = (
            f"Plataforma: {platform}\n"
            f"Métricas: {metrics_summary}\n\n"
            f"Contenido del video:\n{source_text[:6000]}"
        )

        raw, model_used = self._call_llm(
            system_prompt, user_message, preference=self.DEFAULT_LLM, cache_key=source_text[:500]
        )
        parsed = self._parse_json_response(raw)

        return ContentStructure(
            hook=str(parsed.get("hook", "")).strip(),
            tension=str(parsed.get("tension", "")).strip(),
            resolution=str(parsed.get("resolution", "")).strip(),
            analysis_notes=str(parsed.get("analysis_notes", "")).strip() or None,
        )

    def remix_commercial_script(
        self,
        *,
        structure: ContentStructure,
        niche: str,
        brand_voice: Optional[str],
        remix_level: float,
        product_focus: Optional[str],
        platform: str,
        outlier_score: float,
        engagement_rate: float,
        target_duration_seconds: int,
        llm_preference: str = "auto",
    ) -> dict[str, Any]:
        fidelity_pct = int(round(remix_level * 100))
        brand_pct = 100 - fidelity_pct
        voice = brand_voice or "profesional, cercano y orientado a conversión"

        system_prompt = (
            "Eres copywriter senior de performance marketing para Super Vendedor / ED NET PRO.\n"
            "Tu tarea: reescribir un guion de video corto optimizado para VENTAS, "
            "inspirado en un outlier viral pero adaptado al nicho del cliente.\n\n"
            f"Nivel de remix: {fidelity_pct}% fidelidad a la estructura viral original, "
            f"{brand_pct}% voz de marca propia.\n"
            f"Duración objetivo: ~{target_duration_seconds} segundos de locución.\n\n"
            "Devuelve SOLO JSON válido (sin markdown) con:\n"
            "  script_title: título interno del guion\n"
            "  hook, tension, resolution: bloques reescritos para ventas\n"
            "  full_script: guion completo listo para teleprompter (párrafos cortos)\n"
            "  cta: llamada a la acción comercial clara\n"
            "Responde en español. Enfócate en generar leads o ventas directas."
        )

        user_message = (
            f"Nicho del cliente: {niche}\n"
            f"Voz de marca: {voice}\n"
            f"Producto/servicio a promover: {product_focus or 'catálogo general del nicho'}\n"
            f"Plataforma origen: {platform}\n"
            f"Outlier score: {outlier_score}x | Engagement: {engagement_rate}%\n\n"
            "Estructura viral de referencia:\n"
            f"HOOK: {structure.hook}\n"
            f"TENSIÓN: {structure.tension}\n"
            f"RESOLUCIÓN: {structure.resolution}\n"
        )
        if structure.analysis_notes:
            user_message += f"\nNotas del análisis: {structure.analysis_notes}\n"

        raw, model_used = self._call_llm(system_prompt, user_message, preference=llm_preference)
        parsed = self._parse_json_response(raw)
        provider = model_used.split()[0].lower() if model_used else "unknown"

        return {
            "script_title": str(parsed.get("script_title", f"Guion {niche}")).strip(),
            "script_body": str(parsed.get("full_script", parsed.get("script_body", raw))).strip(),
            "hook": str(parsed.get("hook", "")).strip(),
            "tension": str(parsed.get("tension", "")).strip(),
            "resolution": str(parsed.get("resolution", "")).strip(),
            "cta": str(parsed.get("cta", "")).strip(),
            "llm_provider": provider,
            "llm_model": model_used,
            "raw_parsed": parsed,
        }

    def single_pass_analyze_and_script(
        self,
        *,
        caption: Optional[str],
        transcript: Optional[str],
        platform: str,
        metrics_summary: str,
        niche: str,
        brand_voice: Optional[str],
        remix_level: float,
        product_focus: Optional[str],
        target_duration_seconds: int,
        llm_preference: str,
        simulate: bool = False,
    ) -> tuple[ContentStructure, dict[str, Any], int]:
        """
        1 sola llamada LLM → estructura + guion comercial.
        Retorna (structure, remixed_dict, llm_calls).
        """
        if simulate:
            structure = ContentStructure(
                hook="¿Sabías que el 80% de las marcas pierde ventas por no usar este gancho?",
                tension="La mayoría copia contenido genérico sin entender por qué un reel explota.",
                resolution="Aplica esta estructura en 3 pasos y convierte views en leads calificados.",
                analysis_notes="Modo simulado — 0 tokens.",
            )
            remixed = {
                "script_title": f"Guion demo {niche}",
                "script_body": f"{structure.hook}\n\n{structure.tension}\n\n{structure.resolution}",
                "hook": structure.hook,
                "tension": structure.tension,
                "resolution": structure.resolution,
                "cta": "Escríbenos por WhatsApp",
                "llm_provider": "simulate",
                "llm_model": "simulate",
                "raw_parsed": {},
            }
            return structure, remixed, 0

        source_text = (transcript or caption or "").strip()
        if not source_text:
            raise ContentValidationError("Se requiere 'caption' o 'transcript'")

        fidelity_pct = int(round(remix_level * 100))
        brand_pct = 100 - fidelity_pct
        voice = brand_voice or "profesional, cercano y orientado a conversión"
        pref = llm_preference or self.DEFAULT_LLM

        cache_key = hashlib.sha256(
            f"{source_text[:800]}|{niche}|{remix_level}|{product_focus or ''}".encode()
        ).hexdigest()
        cached = self._cache_get(cache_key)
        if cached:
            logger.info("[ContentRemix] Cache hit — 0 tokens")
            structure = ContentStructure(**cached["structure"])
            return structure, cached["remixed"], 0

        system_prompt = (
            "Eres estratega de contenido viral y copywriter de ventas para Super Vendedor.\n"
            "En UNA sola respuesta analiza el reel y genera el guion comercial.\n"
            "Devuelve SOLO JSON válido (sin markdown) con:\n"
            "  hook, tension, resolution, analysis_notes (análisis del original)\n"
            "  script_title, full_script, cta (guion comercial reescrito para ventas)\n"
            f"Remix: {fidelity_pct}% estructura viral + {brand_pct}% voz de marca.\n"
            f"Duración locución: ~{target_duration_seconds}s. Responde en español."
        )
        user_message = (
            f"Plataforma: {platform}\nMétricas: {metrics_summary}\n"
            f"Nicho: {niche}\nVoz: {voice}\nProducto: {product_focus or niche}\n\n"
            f"Contenido:\n{source_text[:5000]}"
        )

        raw, model_used = self._call_llm(system_prompt, user_message, preference=pref)
        parsed = self._parse_json_response(raw)
        provider = model_used.split()[0].lower() if model_used else "unknown"

        structure = ContentStructure(
            hook=str(parsed.get("hook", "")).strip(),
            tension=str(parsed.get("tension", "")).strip(),
            resolution=str(parsed.get("resolution", "")).strip(),
            analysis_notes=str(parsed.get("analysis_notes", "")).strip() or None,
        )
        remixed = {
            "script_title": str(parsed.get("script_title", f"Guion {niche}")).strip(),
            "script_body": str(parsed.get("full_script", parsed.get("script_body", ""))).strip(),
            "hook": str(parsed.get("hook", "")).strip(),
            "tension": str(parsed.get("tension", "")).strip(),
            "resolution": str(parsed.get("resolution", "")).strip(),
            "cta": str(parsed.get("cta", "")).strip(),
            "llm_provider": provider,
            "llm_model": model_used,
            "raw_parsed": parsed,
        }
        self._cache_set(cache_key, {"structure": structure.model_dump(), "remixed": remixed})
        return structure, remixed, 1

    # ── Orquestación de endpoints ─────────────────────────────────────────────

    def analyze_outlier(self, db: Session, payload: OutlierAnalyzeRequest) -> OutlierAnalyzeResponse:
        baseline = self.resolve_baseline_views(db, payload)
        metrics = payload.metrics

        engagement_rate = self.calculate_engagement_rate(
            metrics.views, metrics.likes, metrics.comments, metrics.shares
        )
        outlier_score = self.calculate_outlier_score(metrics.views, baseline)

        metrics_summary = (
            f"views={metrics.views}, likes={metrics.likes}, "
            f"comments={metrics.comments}, shares={metrics.shares}, "
            f"baseline={baseline}, outlier_score={outlier_score}x"
        )

        structure = self.extract_structure(
            caption=payload.caption,
            transcript=payload.transcript,
            platform=payload.platform.value,
            metrics_summary=metrics_summary,
            simulate=payload.simulate,
        )

        outlier = create_outlier(
            db,
            payload,
            engagement_rate=engagement_rate,
            outlier_score=outlier_score,
            structure_hook=structure.hook,
            structure_tension=structure.tension,
            structure_resolution=structure.resolution,
            analysis_notes=structure.analysis_notes,
        )

        return self._outlier_to_response(outlier, structure)

    def generate_script(self, db: Session, payload: ScriptGenerateRequest) -> ScriptGenerateResponse:
        from app.content.crud import get_outlier_for_tenant

        outlier = get_outlier_for_tenant(db, payload.outlier_id, payload.tenant_id)

        if not outlier.structure_hook:
            raise ContentValidationError(
                "El outlier no tiene estructura analizada — ejecuta POST /outliers/analyze primero"
            )

        structure = ContentStructure(
            hook=outlier.structure_hook,
            tension=outlier.structure_tension or "",
            resolution=outlier.structure_resolution or "",
            analysis_notes=outlier.analysis_notes,
        )

        remixed = self.remix_commercial_script(
            structure=structure,
            niche=payload.niche,
            brand_voice=payload.brand_voice,
            remix_level=payload.remix_level,
            product_focus=payload.product_focus,
            platform=outlier.platform.value,
            outlier_score=outlier.outlier_score,
            engagement_rate=outlier.engagement_rate,
            target_duration_seconds=payload.target_duration_seconds,
            llm_preference=payload.llm_preference,
        )

        script = create_generated_script(
            db,
            payload,
            script_title=remixed["script_title"],
            script_body=remixed["script_body"],
            hook=remixed["hook"],
            tension=remixed["tension"],
            resolution=remixed["resolution"],
            cta=remixed["cta"],
            llm_provider=remixed["llm_provider"],
            llm_model=remixed["llm_model"],
            metadata={"raw_parsed": remixed.get("raw_parsed")},
        )

        return ScriptGenerateResponse.model_validate(script)

    def run_pipeline(
        self,
        db: Session,
        payload: "ContentPipelineRequest",
    ) -> "ContentPipelineResponse":
        """Pipeline económico: filtro score → 1 LLM (single_pass) → opcional ads."""
        from app.content.schemas import ContentPipelineRequest, ContentPipelineResponse, OutlierAnalyzeRequest, ScriptGenerateRequest

        analyze_req = OutlierAnalyzeRequest(
            tenant_id=payload.tenant_id,
            platform=payload.platform,
            metrics=payload.metrics,
            profile_id=payload.profile_id,
            baseline_views=payload.baseline_views,
            caption=payload.caption,
            transcript=payload.transcript,
            simulate=payload.simulate,
        )

        baseline = self.resolve_baseline_views(db, analyze_req)
        metrics = payload.metrics
        engagement_rate = self.calculate_engagement_rate(
            metrics.views, metrics.likes, metrics.comments, metrics.shares
        )
        outlier_score = self.calculate_outlier_score(metrics.views, baseline)
        composite_score = self.calculate_composite_score(metrics.views, baseline, engagement_rate)

        if not self.passes_quality_gate(
            composite_score,
            simulate=payload.simulate,
            force=payload.force_process,
        ):
            outlier = create_outlier(
                db,
                analyze_req,
                engagement_rate=engagement_rate,
                outlier_score=outlier_score,
                structure_hook="",
                structure_tension="",
                structure_resolution="",
                analysis_notes=f"SKIP composite={composite_score} < {self.COMPOSITE_THRESHOLD}",
            )
            return ContentPipelineResponse(
                outlier_id=outlier.id,
                script_id="",
                outlier_score=outlier_score,
                engagement_rate=engagement_rate,
                composite_score=composite_score,
                structure=ContentStructure(hook="", tension="", resolution=""),
                script_preview="",
                skipped=True,
                skip_reason=(
                    f"Video no califica (score {composite_score} < {self.COMPOSITE_THRESHOLD}). "
                    "0 tokens gastados. Usa force_process=true para forzar."
                ),
                llm_calls=0,
                mode="skipped",
            )

        metrics_summary = (
            f"views={metrics.views}, engagement={engagement_rate}%, "
            f"outlier={outlier_score}x, composite={composite_score}"
        )

        llm_calls = 0
        if payload.single_pass:
            structure, remixed, llm_calls = self.single_pass_analyze_and_script(
                caption=payload.caption,
                transcript=payload.transcript,
                platform=payload.platform.value,
                metrics_summary=metrics_summary,
                niche=payload.niche,
                brand_voice=payload.brand_voice,
                remix_level=payload.remix_level,
                product_focus=payload.product_focus,
                target_duration_seconds=payload.target_duration_seconds,
                llm_preference=payload.llm_preference,
                simulate=payload.simulate,
            )
            mode = "single_pass"
        else:
            outlier_resp = self.analyze_outlier(db, analyze_req)
            from app.content.schemas import ScriptGenerateRequest

            script_resp = self.generate_script(
                db,
                ScriptGenerateRequest(
                    tenant_id=payload.tenant_id,
                    outlier_id=outlier_resp.id,
                    niche=payload.niche,
                    brand_voice=payload.brand_voice,
                    remix_level=payload.remix_level,
                    product_focus=payload.product_focus,
                    llm_preference=payload.llm_preference,
                    target_duration_seconds=payload.target_duration_seconds,
                ),
            )
            return ContentPipelineResponse(
                outlier_id=outlier_resp.id,
                script_id=script_resp.id,
                outlier_score=outlier_resp.outlier_score,
                engagement_rate=outlier_resp.engagement_rate,
                composite_score=composite_score,
                structure=outlier_resp.structure,
                script_title=script_resp.script_title,
                script_preview=(script_resp.script_body or "")[:280],
                llm_calls=2,
                mode="dual_pass",
            )

        outlier = create_outlier(
            db,
            analyze_req,
            engagement_rate=engagement_rate,
            outlier_score=outlier_score,
            structure_hook=structure.hook,
            structure_tension=structure.tension,
            structure_resolution=structure.resolution,
            analysis_notes=structure.analysis_notes,
        )

        script = create_generated_script(
            db,
            ScriptGenerateRequest(
                tenant_id=payload.tenant_id,
                outlier_id=outlier.id,
                niche=payload.niche,
                brand_voice=payload.brand_voice,
                remix_level=payload.remix_level,
                product_focus=payload.product_focus,
                llm_preference=payload.llm_preference,
            ),
            script_title=remixed["script_title"],
            script_body=remixed["script_body"],
            hook=remixed["hook"],
            tension=remixed["tension"],
            resolution=remixed["resolution"],
            cta=remixed["cta"],
            llm_provider=remixed["llm_provider"],
            llm_model=remixed["llm_model"],
            metadata={"raw_parsed": remixed.get("raw_parsed"), "composite_score": composite_score},
        )

        return ContentPipelineResponse(
            outlier_id=outlier.id,
            script_id=script.id,
            outlier_score=outlier_score,
            engagement_rate=engagement_rate,
            composite_score=composite_score,
            structure=structure,
            script_title=remixed["script_title"],
            script_preview=(remixed["script_body"] or "")[:280],
            llm_calls=llm_calls,
            mode=mode,
        )

    # ── Helpers LLM ───────────────────────────────────────────────────────────

    def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
        *,
        preference: str,
        cache_key: Optional[str] = None,
    ) -> tuple[str, str]:
        if cache_key:
            hit = self._cache_get(cache_key)
            if hit and hit.get("raw"):
                return hit["raw"], hit.get("model", "cache")

        pref = (preference or self.DEFAULT_LLM).lower()

        if pref == "gemini":
            text = self._call_gemini(system_prompt, user_message)
            if text:
                return text, "gemini"
            pref = "auto"

        router = get_llm_router()
        if pref in ("openai", "claude", "auto"):
            text, model = router.generate_response(system_prompt, user_message, pref)  # type: ignore[arg-type]
            if text and model != "local-fallback":
                if cache_key:
                    self._cache_set(cache_key, {"raw": text, "model": model})
                return text, model

        text = self._call_gemini(system_prompt, user_message)
        if text:
            if cache_key:
                self._cache_set(cache_key, {"raw": text, "model": "gemini"})
            return text, "gemini"

        raise ContentLLMError(
            "Ningún proveedor LLM disponible — configura OPENAI_API_KEY, ANTHROPIC_API_KEY o GEMINI_API_KEY"
        )

    @staticmethod
    def _cache_get(key: str) -> Optional[dict[str, Any]]:
        entry = _LLM_CACHE.get(key)
        if not entry:
            return None
        expires, data = entry
        if time.time() > expires:
            _LLM_CACHE.pop(key, None)
            return None
        return data

    @staticmethod
    def _cache_set(key: str, data: dict[str, Any]) -> None:
        _LLM_CACHE[key] = (time.time() + _CACHE_TTL, data)
        if len(_LLM_CACHE) > 500:
            oldest = min(_LLM_CACHE, key=lambda k: _LLM_CACHE[k][0])
            _LLM_CACHE.pop(oldest, None)

    @staticmethod
    def _call_gemini(system_prompt: str, user_message: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return ""

        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model_name = os.getenv("CONTENT_GEMINI_MODEL", "gemini-2.0-flash")
            model = genai.GenerativeModel(model_name)
            prompt = f"{system_prompt}\n\n---\n\n{user_message}"
            response = model.generate_content(prompt)
            return (response.text or "").strip()
        except Exception as exc:
            logger.warning("[ContentRemix] Gemini falló: %s", exc)
            return ""

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            raise ContentLLMError("El LLM devolvió una respuesta vacía")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(text)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

        raise ContentLLMError(f"No se pudo parsear JSON del LLM: {text[:300]}")

    @staticmethod
    def _outlier_to_response(outlier: ViralOutlier, structure: ContentStructure) -> OutlierAnalyzeResponse:
        return OutlierAnalyzeResponse(
            id=outlier.id,
            tenant_id=outlier.tenant_id,
            profile_id=outlier.profile_id,
            platform=outlier.platform,
            video_url=outlier.video_url,
            views=outlier.views,
            likes=outlier.likes,
            comments=outlier.comments,
            shares=outlier.shares,
            engagement_rate=outlier.engagement_rate,
            outlier_score=outlier.outlier_score,
            structure=structure,
            analyzed_at=outlier.analyzed_at,
            created_at=outlier.created_at,
        )


_service: Optional[ContentRemixService] = None


def get_content_remix_service() -> ContentRemixService:
    global _service
    if _service is None:
        _service = ContentRemixService()
    return _service
