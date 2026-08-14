"""
app/services/llm_router.py
────────────────────────────────────────────────────────────────────────────────
Orquestador híbrido de modelos — OpenAI + Anthropic.

Enruta mensajes simples a gpt-4o-mini y conversaciones complejas
(objeciones, reclamos, negociación) a Claude Sonnet, con fallback automático.

Variables:
  OPENAI_API_KEY
  ANTHROPIC_API_KEY
"""

from __future__ import annotations

import logging
import os
import re
from typing import Literal, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ModelPreference = Literal["auto", "openai", "claude"]

OPENAI_CHAT_MODEL = os.getenv("LLM_OPENAI_MODEL", "gpt-4o-mini")
CLAUDE_FALLBACK_MODEL = "claude-3-5-sonnet-20241022"
COMPLEXITY_CHAR_THRESHOLD = int(os.getenv("LLM_COMPLEXITY_CHAR_THRESHOLD", "180"))


def _claude_model_name() -> str:
    return os.getenv("LLM_CLAUDE_MODEL", "claude-3-5-sonnet-latest")

# Señales de mensaje complejo (ventas / soporte)
_COMPLEX_KEYWORDS = [
    r"\bcaro\b", r"\bcara\b", r"precio", r"descuento", r"rebaja", r"negoci",
    r"ofrezco", r"propongo", r"no me convence", r"no me interesa",
    r"reclamo", r"queja", r"devol", r"garant", r"estafa", r"fraude",
    r"no lleg", r"no recib", r"demora", r"tard", r"cancel",
    r"objec", r"pero ", r"sin embargo", r"aunque ",
    r"comprobante", r"transferencia", r"nequi", r"daviplata",
    r"cuanto cuesta", r"cuánto cuesta", r"ultimo precio", r"último precio",
]


class LLMRouterService:
    """
    Router inteligente entre OpenAI y Anthropic según complejidad del mensaje.

    Uso típico desde chat.py:
        router = get_llm_router()
        text, model = router.generate_response(system_prompt, user_message, "auto")
    """

    def __init__(self) -> None:
        self._openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self._openai_client = None
        self._anthropic_client = None

        if self._openai_key:
            try:
                from openai import OpenAI

                self._openai_client = OpenAI(api_key=self._openai_key)
            except Exception as exc:
                logger.warning("[LLMRouter] OpenAI no disponible: %s", exc)

        if self._anthropic_key:
            try:
                import anthropic

                self._anthropic_client = anthropic.Anthropic(api_key=self._anthropic_key)
            except Exception as exc:
                logger.warning("[LLMRouter] Anthropic no disponible: %s", exc)

    @property
    def openai_ready(self) -> bool:
        return self._openai_client is not None

    @property
    def anthropic_ready(self) -> bool:
        return self._anthropic_client is not None

    def is_complex_message(self, text: str) -> bool:
        """
        Detecta si el mensaje requiere razonamiento avanzado (Claude).

        Criterios:
          - Longitud > 180 caracteres
          - Palabras clave de objeción, reclamo o negociación de precio
        """
        normalized = (text or "").strip().lower()
        if not normalized:
            return False

        if len(normalized) > COMPLEXITY_CHAR_THRESHOLD:
            return True

        for pattern in _COMPLEX_KEYWORDS:
            if re.search(pattern, normalized):
                return True

        return False

    def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        model_preference: ModelPreference = "auto",
    ) -> Tuple[str, str]:
        """
        Genera respuesta del agente de ventas.

        Args:
            system_prompt:    Prompt de sistema (incluye Mem0, catálogo, etc.).
            user_message:     Mensaje del cliente ya normalizado.
            model_preference: 'auto' | 'openai' | 'claude'.

        Returns:
            (response_text, model_used)
        """
        preference = (model_preference or "auto").lower()
        if preference not in ("auto", "openai", "claude"):
            preference = "auto"

        use_claude = preference == "claude" or (
            preference == "auto" and self.is_complex_message(user_message)
        )

        if use_claude and self.anthropic_ready:
            try:
                reply, claude_model = self._call_claude(system_prompt, user_message)
                if reply:
                    return reply, claude_model
            except Exception as exc:
                logger.warning(
                    "[LLMRouter] Claude falló — fallback a OpenAI: %s", exc
                )

        if preference == "claude" and not self.anthropic_ready:
            logger.warning("[LLMRouter] Claude solicitado pero ANTHROPIC_API_KEY ausente")

        if self.openai_ready:
            try:
                reply = self._call_openai(system_prompt, user_message)
                if reply:
                    model_label = OPENAI_CHAT_MODEL
                    if use_claude and self.anthropic_ready:
                        model_label = f"{OPENAI_CHAT_MODEL} (fallback)"
                    return reply, model_label
            except Exception as exc:
                logger.error("[LLMRouter] OpenAI falló: %s", exc)

        # Último recurso: pipeline local sin API
        return self._fallback_local(user_message), "local-fallback"

    def _call_openai(self, system_prompt: str, user_message: str) -> str:
        completion = self._openai_client.chat.completions.create(
            model=OPENAI_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return (completion.choices[0].message.content or "").strip()

    def _call_claude(self, system_prompt: str, user_message: str) -> Tuple[str, str]:
        model_name = _claude_model_name()
        candidates = [model_name]
        if model_name != CLAUDE_FALLBACK_MODEL:
            candidates.append(CLAUDE_FALLBACK_MODEL)

        last_exc: Optional[Exception] = None
        for idx, model in enumerate(candidates):
            try:
                reply = self._call_claude_with_model(system_prompt, user_message, model)
                if reply:
                    return reply, model
            except Exception as exc:
                last_exc = exc
                if self._is_claude_model_error(exc) and idx < len(candidates) - 1:
                    logger.warning(
                        "[LLMRouter] Modelo '%s' no disponible (404) — reintentando con '%s'",
                        model,
                        candidates[idx + 1],
                    )
                    continue
                raise

        if last_exc:
            raise last_exc
        return "", model_name

    @staticmethod
    def _is_claude_model_error(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status == 404:
            return True
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error") or {}
            if err.get("type") == "not_found_error":
                return True
        msg = str(exc).lower()
        return "not_found_error" in msg or ("404" in msg and "model" in msg)

    def _call_claude_with_model(
        self, system_prompt: str, user_message: str, model_name: str
    ) -> str:
        message = self._anthropic_client.messages.create(
            model=model_name,
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        parts = []
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts).strip()

    @staticmethod
    def _fallback_local(user_message: str) -> str:
        """Pipeline de ventas existente cuando no hay APIs disponibles."""
        try:
            from app.sales_pipeline import negotiate_response

            return negotiate_response(user_message)
        except Exception:
            return (
                "Gracias por escribirnos. Un asesor de ED NET PRO te contactará pronto. "
                "¿Te interesa ver nuestro catálogo de ropa deportiva?"
            )


_router: Optional[LLMRouterService] = None


def get_llm_router() -> LLMRouterService:
    """Singleton del router híbrido."""
    global _router
    if _router is None:
        _router = LLMRouterService()
    return _router
