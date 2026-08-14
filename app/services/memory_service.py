"""
app/services/memory_service.py
────────────────────────────────────────────────────────────────────────────────
Capa de memoria persistente del cliente — powered by mem0ai (OSS).

Extrae hechos duraderos de cada interacción (talla, presupuesto, preferencias)
y los recupera por búsqueda semántica para inyectar en el System Prompt.

Requisitos:
  - pip install mem0ai
  - OPENAI_API_KEY en .env (extracción de hechos + embeddings)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Directorio local donde mem0 persiste vectores e historial
_DEFAULT_STORAGE = Path(
    os.getenv("MEM0_STORAGE_DIR", "app/storage_vault/mem0")
)


class CustomerMemoryManager:
    """
    Gestor de memoria a largo plazo por cliente (user_id = teléfono, lead_id, etc.).

    Usa mem0ai para:
      - Extraer automáticamente hechos de cada turno de conversación.
      - Buscar recuerdos relevantes ante una nueva consulta.
    """

    def __init__(self, *, storage_dir: Path | None = None) -> None:
        self._openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._storage_dir = storage_dir or _DEFAULT_STORAGE
        self._memory: Any = None
        self._available = False

        if not self._openai_key:
            logger.warning(
                "[Memory] OPENAI_API_KEY no configurada — memoria desactivada. "
                "Define la variable en .env para habilitar mem0ai."
            )
            return

        # mem0 lee OPENAI_API_KEY del entorno al inicializar
        os.environ.setdefault("OPENAI_API_KEY", self._openai_key)

        try:
            from mem0 import Memory

            self._storage_dir.mkdir(parents=True, exist_ok=True)
            qdrant_path = self._storage_dir / "qdrant"

            # Configuración OSS: almacenamiento local persistente en el proyecto
            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "path": str(qdrant_path),
                        "collection_name": "supervendedor_client_memories",
                    },
                },
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": os.getenv("MEM0_LLM_MODEL", "gpt-4.1-mini"),
                        "temperature": 0.1,
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": os.getenv(
                            "MEM0_EMBED_MODEL", "text-embedding-3-small"
                        ),
                    },
                },
            }

            self._memory = Memory.from_config(config)
            self._available = True
            logger.info("[Memory] CustomerMemoryManager listo — storage=%s", self._storage_dir)

        except ImportError:
            logger.error(
                "[Memory] Paquete 'mem0ai' no instalado. Ejecuta: pip install mem0ai"
            )
        except Exception as exc:
            logger.exception("[Memory] Error inicializando mem0: %s", exc)

    @property
    def is_available(self) -> bool:
        """True si mem0 está inicializado y operativo."""
        return self._available and self._memory is not None

    def save_interaction(
        self,
        user_id: str,
        user_message: str,
        bot_message: str | None = None,
    ) -> dict[str, Any]:
        """
        Extrae y persiste hechos del turno de conversación.

        mem0 analiza el mensaje del usuario (y opcionalmente la respuesta del bot)
        y guarda facts atómicos: preferencias, tallas, presupuesto, objeciones, etc.

        Args:
            user_id:      Identificador único del cliente (ej. teléfono WhatsApp).
            user_message: Lo que escribió/dijo el cliente.
            bot_message:  Respuesta del bot en ese turno (opcional, enriquece contexto).

        Returns:
            Resultado de mem0.add() o dict con ok=False si la memoria no está disponible.
        """
        if not self.is_available:
            return {
                "ok": False,
                "error": "Memoria no disponible — revisa OPENAI_API_KEY y pip install mem0ai",
            }

        user_id = (user_id or "").strip()
        user_message = (user_message or "").strip()
        if not user_id or not user_message:
            return {"ok": False, "error": "user_id y user_message son obligatorios"}

        # Formato de conversación que mem0 usa para extracción automática de hechos
        messages: list[dict[str, str]] = [
            {"role": "user", "content": user_message},
        ]
        if bot_message and bot_message.strip():
            messages.append({"role": "assistant", "content": bot_message.strip()})

        try:
            result = self._memory.add(messages, user_id=user_id)
            logger.debug("[Memory] Guardado user_id=%s | facts=%s", user_id, result)
            return {"ok": True, "result": result}
        except Exception as exc:
            logger.exception("[Memory] save_interaction falló para user_id=%s", user_id)
            return {"ok": False, "error": str(exc)}

    def get_memories_context(self, user_id: str, query: str) -> str:
        """
        Busca memorias semánticamente relevantes y devuelve texto listo para el System Prompt.

        Args:
            user_id: Identificador del cliente.
            query:   Pregunta o mensaje actual (ancla la búsqueda semántica).

        Returns:
            Bloque formateado para inyectar en el prompt, o cadena vacía si no hay resultados.
        """
        if not self.is_available:
            return ""

        user_id = (user_id or "").strip()
        query = (query or "").strip()
        if not user_id:
            return ""

        # Si no hay query, buscamos contexto general del perfil del cliente
        search_query = query or "preferencias, talla, presupuesto, productos de interés del cliente"

        try:
            raw = self._memory.search(
                search_query,
                filters={"user_id": user_id},
                limit=int(os.getenv("MEM0_SEARCH_LIMIT", "5")),
            )
        except TypeError:
            # Compatibilidad con versiones que usan user_id como kwarg directo
            try:
                raw = self._memory.search(
                    search_query,
                    user_id=user_id,
                    limit=int(os.getenv("MEM0_SEARCH_LIMIT", "5")),
                )
            except Exception as exc:
                logger.exception("[Memory] search falló user_id=%s", user_id)
                return ""
        except Exception as exc:
            logger.exception("[Memory] search falló user_id=%s", user_id)
            return ""

        entries = _extract_search_results(raw)
        if not entries:
            return ""

        lines = ["=== MEMORIA DEL CLIENTE (recuerdos previos) ==="]
        for item in entries:
            text = _memory_text(item)
            if text:
                score = item.get("score")
                if score is not None:
                    lines.append(f"- {text} (relevancia: {score:.2f})")
                else:
                    lines.append(f"- {text}")
        lines.append("=== FIN MEMORIA ===")

        return "\n".join(lines)

    def get_all_memories(self, user_id: str) -> list[dict[str, Any]]:
        """Devuelve todas las memorias almacenadas de un cliente (útil para debug/admin)."""
        if not self.is_available:
            return []

        try:
            raw = self._memory.get_all(filters={"user_id": user_id})
        except TypeError:
            try:
                raw = self._memory.get_all(user_id=user_id)
            except Exception:
                return []
        except Exception:
            return []

        if isinstance(raw, dict):
            return raw.get("results") or raw.get("memories") or []
        if isinstance(raw, list):
            return raw
        return []


def _extract_search_results(raw: Any) -> list[dict[str, Any]]:
    """Normaliza la respuesta de mem0.search() entre versiones del SDK."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return raw.get("results") or raw.get("memories") or []
    if isinstance(raw, list):
        return raw
    return []


def _memory_text(item: dict[str, Any]) -> str:
    """Extrae el texto legible de un registro de memoria."""
    for key in ("memory", "text", "content", "data"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# Singleton opcional para reutilizar la misma instancia en routers/agentes
_manager: CustomerMemoryManager | None = None


def get_customer_memory() -> CustomerMemoryManager:
    """Instancia compartida del gestor de memoria (lazy init)."""
    global _manager
    if _manager is None:
        _manager = CustomerMemoryManager()
    return _manager
