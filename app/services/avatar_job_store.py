"""
app/services/avatar_job_store.py
────────────────────────────────────────────────────────────────────────────────
Persistencia de jobs de avatar en PocketBase con caché en memoria.

Colección PocketBase esperada: avatar_jobs (configurable vía AVATAR_JOBS_COLLECTION)
  - job_id      (text, único)
  - status      (text)
  - text        (text)
  - voice_id    (text)
  - image_url   (text)
  - webhook_url (text, opcional)
  - video_url   (text, opcional)
  - audio_path  (text, opcional)
  - error       (text, opcional)
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

COLLECTION = os.getenv("AVATAR_JOBS_COLLECTION", "avatar_jobs")
_memory: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_pb_available: Optional[bool] = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_pb_available() -> bool:
    global _pb_available
    if _pb_available is not None:
        return _pb_available
    try:
        from app.database.pocketbase_client import collection_exists

        _pb_available = collection_exists(COLLECTION)
        if not _pb_available:
            logger.warning(
                "[Avatares] Colección '%s' no encontrada en PocketBase — solo memoria local",
                COLLECTION,
            )
    except Exception as exc:
        logger.warning("[Avatares] PocketBase no disponible: %s", exc)
        _pb_available = False
    return bool(_pb_available)


def _to_pb_payload(job: dict[str, Any]) -> dict[str, Any]:
    request = job.get("request") or {}
    return {
        "job_id": job["job_id"],
        "status": str(job.get("status", "")),
        "text": request.get("text") or job.get("text") or "",
        "voice_id": request.get("voice_id") or job.get("voice_id") or "",
        "image_url": request.get("image_url") or job.get("image_url") or "",
        "webhook_url": job.get("webhook_url") or request.get("webhook_url") or "",
        "video_url": job.get("video_url") or "",
        "audio_path": job.get("audio_path") or "",
        "error": job.get("error") or "",
    }


def _from_pb_record(record: dict[str, Any]) -> dict[str, Any]:
    created = record.get("created") or record.get("created_at") or utc_now_iso()
    updated = record.get("updated") or record.get("updated_at") or created
    return {
        "job_id": record.get("job_id", ""),
        "status": record.get("status", ""),
        "created_at": created if isinstance(created, str) else str(created),
        "updated_at": updated if isinstance(updated, str) else str(updated),
        "video_url": record.get("video_url") or None,
        "audio_path": record.get("audio_path") or None,
        "error": record.get("error") or None,
        "webhook_url": record.get("webhook_url") or None,
        "request": {
            "text": record.get("text", ""),
            "voice_id": record.get("voice_id", ""),
            "image_url": record.get("image_url", ""),
            "webhook_url": record.get("webhook_url") or None,
        },
        "pb_id": record.get("id"),
    }


def _persist_to_pb(job: dict[str, Any]) -> None:
    if not _check_pb_available():
        return

    try:
        from app.database.pocketbase_client import create_record, list_records, update_record

        payload = _to_pb_payload(job)
        existing = list_records(
            COLLECTION,
            filter_expr=f"(job_id='{payload['job_id']}')",
            per_page=1,
            quiet=True,
        )
        if existing:
            update_record(COLLECTION, existing[0]["id"], payload, quiet=True)
        else:
            created = create_record(COLLECTION, payload, quiet=True)
            if created:
                job["pb_id"] = created.get("id")
    except Exception as exc:
        logger.warning("[Avatares] Error persistiendo job %s: %s", job.get("job_id"), exc)


def create_job(job: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _memory[job["job_id"]] = job
    _persist_to_pb(job)
    return job


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        cached = _memory.get(job_id)
    if cached:
        return cached

    if not _check_pb_available():
        return None

    try:
        from app.database.pocketbase_client import list_records

        records = list_records(
            COLLECTION,
            filter_expr=f"(job_id='{job_id}')",
            per_page=1,
            quiet=True,
        )
        if not records:
            return None
        job = _from_pb_record(records[0])
        with _lock:
            _memory[job_id] = job
        return job
    except Exception as exc:
        logger.warning("[Avatares] Error leyendo job %s desde PB: %s", job_id, exc)
        return None


def update_job(job_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    with _lock:
        job = _memory.get(job_id)
        if not job:
            job = {"job_id": job_id, "created_at": utc_now_iso()}
            _memory[job_id] = job
        job.update(fields)
        job["updated_at"] = utc_now_iso()

    _persist_to_pb(job)
    return job


async def notify_webhook(job: dict[str, Any]) -> None:
    """POST al webhook del cliente cuando el job termina (completed o failed)."""
    webhook_url = (job.get("webhook_url") or "").strip()
    if not webhook_url:
        request = job.get("request") or {}
        webhook_url = (request.get("webhook_url") or "").strip()
    if not webhook_url:
        return

    payload = {
        "event": "avatar.job.finished",
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "video_url": job.get("video_url"),
        "audio_path": job.get("audio_path"),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }

    headers = {"Content-Type": "application/json"}
    secret = (os.getenv("AVATAR_WEBHOOK_SECRET") or "").strip()
    if secret:
        headers["X-Avatar-Webhook-Secret"] = secret

    timeout = float(os.getenv("AVATAR_WEBHOOK_TIMEOUT_SECONDS", "15"))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(webhook_url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.warning(
                "[Avatares] Webhook %s respondió %s: %s",
                webhook_url,
                response.status_code,
                response.text[:300],
            )
        else:
            logger.info("[Avatares] Webhook notificado job_id=%s url=%s", job.get("job_id"), webhook_url)
    except httpx.HTTPError as exc:
        logger.warning("[Avatares] Webhook falló job_id=%s: %s", job.get("job_id"), exc)
