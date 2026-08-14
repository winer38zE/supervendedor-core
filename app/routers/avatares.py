"""
app/routers/avatares.py
────────────────────────────────────────────────────────────────────────────────
Generación asíncrona de avatares de video hiperrealistas:
  1. ElevenLabs TTS (voz clonada)
  2. Replicate lip-sync (imagen + audio → video)

Montaje en main.py:
    app.include_router(avatares.router, prefix="/api/v1/avatares", tags=["Avatares"])
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl

from app.security import verify_api_key
from app.services.avatar_job_store import (
    create_job,
    get_job,
    notify_webhook,
    update_job,
    utc_now_iso,
)
from app.services.elevenlabs_service import ElevenLabsError, generate_speech
from app.services.replicate_service import ReplicateError, generate_avatar_video

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AvatarRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Guión a sintetizar")
    voice_id: str = Field(..., min_length=1, description="ID de voz clonada en ElevenLabs")
    image_url: HttpUrl = Field(..., description="URL pública de la imagen base del avatar")
    webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="URL opcional para recibir POST cuando el job termine (completed/failed)",
    )


class AvatarJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


class AvatarJobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    video_url: Optional[str] = None
    audio_path: Optional[str] = None
    error: Optional[str] = None
    webhook_url: Optional[str] = None


async def _run_avatar_pipeline(job_id: str, payload: AvatarRequest) -> None:
    """Pipeline completo ejecutado en segundo plano."""
    try:
        update_job(job_id, status=JobStatus.PROCESSING)

        audio_path = await generate_speech(
            text=payload.text,
            voice_id=payload.voice_id,
        )
        update_job(job_id, audio_path=str(audio_path))

        video_url = await generate_avatar_video(
            image_url=str(payload.image_url),
            audio_path=audio_path,
        )

        job = update_job(
            job_id,
            status=JobStatus.COMPLETED,
            video_url=video_url,
            error=None,
        )
        logger.info("[Avatares] Job %s completado: %s", job_id, video_url)
        if job:
            await notify_webhook(job)

    except ElevenLabsError as exc:
        logger.error("[Avatares] Job %s — error ElevenLabs: %s", job_id, exc)
        job = update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        if job:
            await notify_webhook(job)

    except ReplicateError as exc:
        logger.error("[Avatares] Job %s — error Replicate: %s", job_id, exc)
        job = update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        if job:
            await notify_webhook(job)

    except Exception as exc:
        logger.exception("[Avatares] Job %s — error inesperado", job_id)
        job = update_job(job_id, status=JobStatus.FAILED, error=f"Error interno: {exc}")
        if job:
            await notify_webhook(job)


@router.post(
    "/generar",
    response_model=AvatarJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generar avatar de video (async)",
)
async def generar_avatar(
    payload: AvatarRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Encola la generación de un avatar de video:
    texto → ElevenLabs (MP3) → Replicate (lip-sync).

    Devuelve de inmediato un `job_id` para consultar el estado en GET /generar/{job_id}.
    Si se envía `webhook_url`, recibirás un POST al finalizar (completed o failed).
    """
    job_id = uuid.uuid4().hex
    now = utc_now_iso()

    create_job(
        {
            "job_id": job_id,
            "status": JobStatus.QUEUED,
            "created_at": now,
            "updated_at": now,
            "video_url": None,
            "audio_path": None,
            "error": None,
            "webhook_url": str(payload.webhook_url) if payload.webhook_url else None,
            "request": payload.model_dump(mode="json"),
        }
    )

    background_tasks.add_task(_run_avatar_pipeline, job_id, payload)

    body = AvatarJobResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        message="Generación de avatar encolada. Consulta GET /api/v1/avatares/generar/{job_id}.",
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body.model_dump())


@router.get(
    "/generar/{job_id}",
    response_model=AvatarJobStatusResponse,
    summary="Consultar estado de un job de avatar",
)
async def consultar_avatar(job_id: str) -> AvatarJobStatusResponse:
    """Devuelve el estado, URL del video o error del job solicitado (memoria o PocketBase)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' no encontrado")

    return AvatarJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        video_url=job.get("video_url"),
        audio_path=job.get("audio_path"),
        error=job.get("error"),
        webhook_url=job.get("webhook_url"),
    )
