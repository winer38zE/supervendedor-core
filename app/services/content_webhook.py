"""
app/services/content_webhook.py
────────────────────────────────────────────────────────────────────────────────
Webhook al completar pipeline de contenido (sin polling en n8n).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


async def notify_content_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    if not webhook_url:
        return

    headers = {"Content-Type": "application/json"}
    secret = (os.getenv("CONTENT_WEBHOOK_SECRET") or os.getenv("AVATAR_WEBHOOK_SECRET") or "").strip()
    if secret:
        headers["X-Content-Webhook-Secret"] = secret

    timeout = float(os.getenv("CONTENT_WEBHOOK_TIMEOUT_SECONDS", "15"))

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(webhook_url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.warning("[Content] Webhook %s → %s", webhook_url, response.status_code)
        else:
            logger.info("[Content] Webhook OK event=%s", payload.get("event"))
    except httpx.HTTPError as exc:
        logger.warning("[Content] Webhook falló: %s", exc)


def notify_content_webhook_sync(webhook_url: str, payload: dict[str, Any]) -> None:
    import asyncio

    try:
        asyncio.run(notify_content_webhook(webhook_url, payload))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(notify_content_webhook(webhook_url, payload))
        finally:
            loop.close()
