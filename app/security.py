"""
app/security.py — Autenticación centralizada (API interna, webhooks, admin).
"""

from __future__ import annotations

import logging

from fastapi import Header, HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)


async def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """
    Valida header X-API-Key contra INTERNAL_API_KEY.
    En development, si INTERNAL_API_KEY no está configurada, permite el acceso con warning.
    """
    expected = (settings.INTERNAL_API_KEY or "").strip()

    if not expected:
        if settings.ENV == "production":
            logger.error("[Security] INTERNAL_API_KEY no configurada en producción")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="INTERNAL_API_KEY no configurada en el servidor",
            )
        logger.warning("[Security] INTERNAL_API_KEY vacía — acceso permitido solo en development")
        return

    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente (header X-API-Key)",
        )


async def require_master_key(x_master_key: str = Header(..., alias="x-master-key")) -> str:
    """
    Admin SAAS — header x-master-key contra MASTER_KEY.
    En producción sin MASTER_KEY configurada → 503.
    """
    expected = (settings.MASTER_KEY or "").strip()

    if not expected:
        if settings.ENV == "production":
            logger.error("[Security] MASTER_KEY no configurada en producción")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MASTER_KEY no configurada en el servidor",
            )
        logger.warning("[Security] MASTER_KEY vacía — usando clave de desarrollo insegura")
        expected = "ednetpro_2026"

    if x_master_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Clave maestra inválida.",
        )
    return x_master_key


def verify_evolution_webhook(request: Request) -> None:
    """WhatsApp/Evolution — header apikey o x-api-key."""
    expected = (settings.EVOLUTION_API_KEY or "").strip()
    if not expected:
        if settings.ENV == "production":
            logger.error("[Security] EVOLUTION_API_KEY no configurada en producción")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="EVOLUTION_API_KEY no configurada en el servidor",
            )
        return

    incoming = (request.headers.get("apikey") or request.headers.get("x-api-key") or "").strip()
    if incoming != expected:
        raise HTTPException(status_code=401, detail="Webhook Evolution no autorizado")


def verify_vapi_webhook(request: Request) -> None:
    """Vapi — header x-vapi-secret o Authorization Bearer."""
    secret = (settings.VAPI_WEBHOOK_SECRET or "").strip()
    if not secret:
        if settings.ENV == "production":
            logger.error("[Security] VAPI_WEBHOOK_SECRET no configurado en producción")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="VAPI_WEBHOOK_SECRET no configurado en el servidor",
            )
        return

    incoming = (
        request.headers.get("x-vapi-secret")
        or request.headers.get("authorization")
        or ""
    ).strip()
    if incoming.replace("Bearer ", "") != secret:
        raise HTTPException(status_code=401, detail="Webhook Vapi no autorizado")
