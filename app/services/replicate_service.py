"""
app/services/replicate_service.py
────────────────────────────────────────────────────────────────────────────────
Animación facial / lip-sync con modelos alojados en Replicate.

Modelo por defecto: wan-video/wan-2.2-s2v (imagen + audio → video).
Configurable vía REPLICATE_AVATAR_MODEL en .env.

Requisitos:
  - REPLICATE_API_TOKEN en .env
  - httpx
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REPLICATE_API_BASE = "https://api.replicate.com/v1"
DEFAULT_AVATAR_MODEL = "wan-video/wan-2.2-s2v"


class ReplicateError(Exception):
    """Error al invocar la API de Replicate."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_api_token() -> str:
    token = (os.getenv("REPLICATE_API_TOKEN") or "").strip()
    if not token:
        raise ReplicateError(
            "REPLICATE_API_TOKEN no configurado en el entorno",
            status_code=503,
        )
    return token


def _auth_headers(token: str, *, prefer_wait: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if prefer_wait:
        headers["Prefer"] = "wait"
    return headers


async def _upload_local_file(client: httpx.AsyncClient, token: str, file_path: Path) -> str:
    """Sube un archivo local a Replicate Files y devuelve la URL pública."""
    if not file_path.is_file():
        raise ReplicateError(f"Archivo de audio no encontrado: {file_path}", status_code=422)

    mime = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "application/octet-stream"
    headers = {"Authorization": f"Bearer {token}"}

    with file_path.open("rb") as handle:
        response = await client.post(
            f"{REPLICATE_API_BASE}/files",
            headers=headers,
            files={"content": (file_path.name, handle, mime)},
        )

    if response.status_code not in (200, 201):
        raise ReplicateError(
            f"Replicate Files respondió {response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
        )

    payload = response.json()
    file_url = (payload.get("urls") or {}).get("get")
    if not file_url:
        raise ReplicateError("Replicate Files no devolvió URL del audio", status_code=502)

    logger.info("[Replicate] Audio subido: %s", file_url)
    return file_url


def _build_model_input(model: str, image_url: str, audio_url: str) -> dict[str, str]:
    """Mapea inputs según el modelo configurado."""
    model_key = model.lower()

    if "aniportrait" in model_key:
        return {"ref_img": image_url, "audio": audio_url}

    # wan-2.2-s2v, live-portrait variants y modelos genéricos image+audio
    return {"image": image_url, "audio": audio_url}


async def _poll_prediction(
    client: httpx.AsyncClient,
    token: str,
    prediction_url: str,
    *,
    poll_interval: float,
    max_wait_seconds: float,
) -> dict[str, Any]:
    elapsed = 0.0

    while elapsed < max_wait_seconds:
        response = await client.get(prediction_url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            raise ReplicateError(
                f"Error consultando predicción: {response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            )

        data = response.json()
        status = data.get("status")

        if status == "succeeded":
            return data
        if status in {"failed", "canceled"}:
            error_detail = data.get("error") or "Predicción fallida en Replicate"
            raise ReplicateError(str(error_detail), status_code=502)

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise ReplicateError(
        f"Timeout esperando video de Replicate ({max_wait_seconds}s)",
        status_code=504,
    )


def _extract_video_url(output: Any) -> str:
    """Normaliza la salida de Replicate (string, lista o dict)."""
    if isinstance(output, str) and output.strip():
        return output.strip()

    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.strip():
                return item.strip()

    if isinstance(output, dict):
        for key in ("video", "output", "url", "mp4"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    raise ReplicateError(
        f"Formato de salida de Replicate no reconocido: {output!r}",
        status_code=502,
    )


async def generate_avatar_video(
    image_url: str,
    audio_path: Path,
    *,
    model: Optional[str] = None,
) -> str:
    """
    Genera un video con lip-sync a partir de una imagen base y un audio local.

    Args:
        image_url: URL pública HTTP(S) de la imagen del avatar.
        audio_path: Ruta local del MP3 generado por ElevenLabs.
        model: Modelo Replicate (owner/name). Por defecto REPLICATE_AVATAR_MODEL.

    Returns:
        URL del video generado.

    Raises:
        ReplicateError: Si faltan credenciales, parámetros o la API falla.
    """
    cleaned_image = (image_url or "").strip()
    if not cleaned_image:
        raise ReplicateError("El campo 'image_url' no puede estar vacío", status_code=422)
    if not cleaned_image.startswith(("http://", "https://")):
        raise ReplicateError("'image_url' debe ser una URL HTTP(S) pública", status_code=422)

    token = _get_api_token()
    model_name = (model or os.getenv("REPLICATE_AVATAR_MODEL") or DEFAULT_AVATAR_MODEL).strip()
    timeout = float(os.getenv("REPLICATE_TIMEOUT_SECONDS", "30"))
    poll_interval = float(os.getenv("REPLICATE_POLL_INTERVAL_SECONDS", "3"))
    max_wait = float(os.getenv("REPLICATE_MAX_WAIT_SECONDS", "600"))

    logger.info(
        "[Replicate] Iniciando avatar model=%s image=%s audio=%s",
        model_name,
        cleaned_image[:80],
        audio_path.name,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            audio_url = await _upload_local_file(client, token, audio_path)
            model_input = _build_model_input(model_name, cleaned_image, audio_url)

            create_response = await client.post(
                f"{REPLICATE_API_BASE}/predictions",
                headers=_auth_headers(token),
                json={"model": model_name, "input": model_input},
            )

            if create_response.status_code not in (200, 201):
                raise ReplicateError(
                    f"Replicate respondió {create_response.status_code}: {create_response.text[:500]}",
                    status_code=create_response.status_code,
                )

            prediction = create_response.json()
            status = prediction.get("status")

            if status != "succeeded":
                prediction_url = prediction.get("urls", {}).get("get")
                if not prediction_url:
                    raise ReplicateError(
                        "Replicate no devolvió URL de seguimiento de la predicción",
                        status_code=502,
                    )
                prediction = await _poll_prediction(
                    client,
                    token,
                    prediction_url,
                    poll_interval=poll_interval,
                    max_wait_seconds=max_wait,
                )

            video_url = _extract_video_url(prediction.get("output"))
            logger.info("[Replicate] Video generado: %s", video_url)
            return video_url

    except httpx.TimeoutException as exc:
        raise ReplicateError("Timeout al conectar con Replicate") from exc
    except httpx.HTTPError as exc:
        raise ReplicateError(f"Error de red con Replicate: {exc}") from exc
