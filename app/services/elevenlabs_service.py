"""
app/services/elevenlabs_service.py
────────────────────────────────────────────────────────────────────────────────
Síntesis de voz con voces clonadas vía ElevenLabs API.

Requisitos:
  - ELEVENLABS_API_KEY en .env
  - httpx (ya incluido en requirements.txt)
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_TEMP_DIR = Path(
    os.getenv("AVATAR_TEMP_DIR", "app/storage_vault/avatar_temp")
)


class ElevenLabsError(Exception):
    """Error al invocar la API de ElevenLabs."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_api_key() -> str:
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise ElevenLabsError(
            "ELEVENLABS_API_KEY no configurada en el entorno",
            status_code=503,
        )
    return api_key


def _ensure_temp_dir() -> Path:
    DEFAULT_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_TEMP_DIR


async def generate_speech(
    text: str,
    voice_id: str,
    *,
    model_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    Genera un archivo MP3 a partir de texto usando una voz clonada de ElevenLabs.

    Args:
        text: Texto a sintetizar.
        voice_id: ID de la voz clonada en ElevenLabs.
        model_id: Modelo TTS (por defecto eleven_multilingual_v2).
        output_dir: Carpeta destino del audio temporal.

    Returns:
        Ruta absoluta del archivo .mp3 generado.

    Raises:
        ElevenLabsError: Si faltan credenciales, parámetros o la API falla.
    """
    cleaned_text = (text or "").strip()
    cleaned_voice = (voice_id or "").strip()
    if not cleaned_text:
        raise ElevenLabsError("El campo 'text' no puede estar vacío", status_code=422)
    if not cleaned_voice:
        raise ElevenLabsError("El campo 'voice_id' no puede estar vacío", status_code=422)

    api_key = _get_api_key()
    folder = output_dir or _ensure_temp_dir()
    folder.mkdir(parents=True, exist_ok=True)

    filename = f"tts_{uuid.uuid4().hex[:12]}.mp3"
    output_path = folder / filename

    payload = {
        "text": cleaned_text,
        "model_id": (model_id or os.getenv("ELEVENLABS_MODEL_ID") or DEFAULT_MODEL_ID).strip(),
        "voice_settings": {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.5")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75")),
        },
    }

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    url = ELEVENLABS_TTS_URL.format(voice_id=cleaned_voice)
    timeout = float(os.getenv("ELEVENLABS_TIMEOUT_SECONDS", "120"))

    logger.info("[ElevenLabs] Generando audio voice_id=%s chars=%d", cleaned_voice, len(cleaned_text))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ElevenLabsError("Timeout al conectar con ElevenLabs") from exc
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Error de red con ElevenLabs: {exc}") from exc

    if response.status_code != 200:
        detail = response.text[:500]
        logger.error(
            "[ElevenLabs] Error HTTP %s: %s",
            response.status_code,
            detail,
        )
        raise ElevenLabsError(
            f"ElevenLabs respondió {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    if not response.content:
        raise ElevenLabsError("ElevenLabs devolvió un audio vacío", status_code=502)

    output_path.write_bytes(response.content)
    logger.info("[ElevenLabs] Audio guardado en %s (%d bytes)", output_path, len(response.content))
    return output_path.resolve()
