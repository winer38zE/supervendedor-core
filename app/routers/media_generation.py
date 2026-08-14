"""
media_generation.py
Router FastAPI para generar VIDEO (Google Veo 3.1) e IMÁGENES (Google Imagen)
usando la Gemini API. Pensado para integrarse al proyecto ED NET PRO.

Instalación:
    pip install fastapi httpx python-dotenv

Variables de entorno necesarias (.env):
    GEMINI_API_KEY=tu_api_key_de_google_ai_studio

Cómo montarlo en tu app principal (main.py):
    from media_generation import router as media_router
    app.include_router(media_router, prefix="/media", tags=["media"])
"""

import os
import time
import base64
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

if not GEMINI_API_KEY:
    # No tumbamos el import, pero avisamos apenas se use un endpoint.
    print("[media_generation] ADVERTENCIA: falta GEMINI_API_KEY en el entorno.")


def _headers() -> dict:
    return {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# VIDEO — Veo 3.1
# ---------------------------------------------------------------------------

class VideoRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    resolution: Optional[str] = "720p"     # "720p" | "1080p" | "4k"
    model: Optional[str] = "veo-3.1-generate-preview"


class VideoResponse(BaseModel):
    video_uri: str
    operation_name: str


@router.post("/generate/video", response_model=VideoResponse)
async def generate_video(req: VideoRequest):
    """
    Genera un video con Veo 3.1. Es un proceso asíncrono en la API de Google:
    1. Se lanza la generación (predictLongRunning) y devuelve un "operation name".
    2. Se hace polling cada N segundos hasta que 'done' sea true.
    3. Se devuelve la URI del video generado.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(500, "Falta configurar GEMINI_API_KEY")

    instance = {"prompt": req.prompt}
    payload = {
        "instances": [instance],
    }
    if req.negative_prompt or req.resolution:
        payload["parameters"] = {}
        if req.negative_prompt:
            payload["parameters"]["negativePrompt"] = req.negative_prompt
        if req.resolution:
            payload["parameters"]["resolution"] = req.resolution

    async with httpx.AsyncClient(timeout=60) as client:
        create_resp = await client.post(
            f"{BASE_URL}/models/{req.model}:predictLongRunning",
            headers=_headers(),
            json=payload,
        )

    if create_resp.status_code != 200:
        raise HTTPException(create_resp.status_code, create_resp.text)

    operation_name = create_resp.json().get("name")
    if not operation_name:
        raise HTTPException(502, "La API no devolvió operation name")

    # --- Polling ---
    video_uri = await _poll_video_operation(operation_name)

    return VideoResponse(video_uri=video_uri, operation_name=operation_name)


async def _poll_video_operation(operation_name: str, max_wait_seconds: int = 300, interval: int = 10) -> str:
    waited = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while waited < max_wait_seconds:
            resp = await client.get(f"{BASE_URL}/{operation_name}", headers=_headers())
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)

            data = resp.json()
            if data.get("done"):
                try:
                    samples = data["response"]["generateVideoResponse"]["generatedSamples"]
                    return samples[0]["video"]["uri"]
                except (KeyError, IndexError):
                    raise HTTPException(502, f"Respuesta inesperada de la API: {data}")

            time.sleep(interval)  # ok en contexto async simple; para prod usar asyncio.sleep
            waited += interval

    raise HTTPException(504, "Timeout esperando el video (revisa el operation_name manualmente)")


@router.get("/generate/video/status/{operation_id:path}")
async def check_video_status(operation_id: str):
    """Consulta manual del estado de una operación (por si el polling automático hace timeout)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/{operation_id}", headers=_headers())
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


# ---------------------------------------------------------------------------
# IMAGEN — Nano Banana / Nano Banana Pro (Gemini native image generation)
# ---------------------------------------------------------------------------
# Nano Banana      -> gemini-2.5-flash-image   (rápido/barato, alto volumen, bocetos)
# Nano Banana Pro   -> gemini-3-pro-image-preview (mejor consistencia de marca/personaje,
#                                                    mejor texto renderizado, piezas finales)
# Ambos usan el mismo método generateContent (no 'predict').

IMAGE_MODELS = {
    "fast": "gemini-2.5-flash-image",
    "pro": "gemini-3-pro-image-preview",
}


class ImageRequest(BaseModel):
    prompt: str
    tier: Optional[str] = "fast"           # "fast" (Nano Banana) | "pro" (Nano Banana Pro)
    reference_images_base64: Optional[list[str]] = None  # para mantener consistencia de marca/personaje
    aspect_ratio: Optional[str] = "1:1"    # "1:1" | "16:9" | "9:16" | "4:3" | "3:4"


class ImageResponse(BaseModel):
    images_base64: list[str]
    model_used: str


@router.post("/generate/image", response_model=ImageResponse)
async def generate_image(req: ImageRequest):
    """
    Genera imágenes con Nano Banana o Nano Banana Pro vía generateContent.
    Para consistencia de marca entre piezas de un mismo cliente, manda
    reference_images_base64 con logo/producto/imagen previa aprobada: el
    modelo mantiene el mismo estilo/personaje/producto entre generaciones.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(500, "Falta configurar GEMINI_API_KEY")

    model = IMAGE_MODELS.get(req.tier, IMAGE_MODELS["fast"])

    parts = [{"text": req.prompt}]
    if req.reference_images_base64:
        for img_b64 in req.reference_images_base64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": img_b64,
                }
            })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "imageConfig": {"aspectRatio": req.aspect_ratio}
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{BASE_URL}/models/{model}:generateContent",
            headers=_headers(),
            json=payload,
        )

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)

    data = resp.json()
    try:
        candidate_parts = data["candidates"][0]["content"]["parts"]
        images = [
            p["inlineData"]["data"]
            for p in candidate_parts
            if "inlineData" in p
        ]
        if not images:
            raise KeyError("sin inlineData en la respuesta")
    except (KeyError, IndexError, TypeError):
        raise HTTPException(502, f"Respuesta inesperada de la API: {data}")

    return ImageResponse(images_base64=images, model_used=model)


@router.post("/generate/image/save")
async def generate_image_and_save(req: ImageRequest, output_dir: str = "/tmp/ednetpro_media"):
    """
    Igual que /generate/image pero guarda los archivos en disco (útil para que
    n8n después los tome y los suba a Meta Ads / YouTube).
    """
    os.makedirs(output_dir, exist_ok=True)
    result = await generate_image(req)

    saved_paths = []
    for i, b64 in enumerate(result.images_base64):
        path = os.path.join(output_dir, f"image_{int(time.time())}_{i}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        saved_paths.append(path)

    return {"saved_paths": saved_paths, "model_used": result.model_used}