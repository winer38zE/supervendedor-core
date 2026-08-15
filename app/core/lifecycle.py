"""
app/core/lifecycle.py — Arranque y apagado ED NET PRO 3.0
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.config import log_startup_warnings

logger = logging.getLogger(__name__)

_followup_task: asyncio.Task | None = None


async def on_startup() -> None:
    """Inicialización unificada de catálogo, content DB y schedulers."""
    global _followup_task
    log_startup_warnings()

    try:
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        count = bridge.refresh()
        logger.info("[Startup] Catalog Bridge: %d productos cargados", count)
    except Exception as exc:
        logger.warning("[Startup] Catalog Bridge error: %s", exc)

    try:
        from app.database.sqlalchemy_session import init_content_db

        init_content_db()
    except Exception as exc:
        logger.warning("[Startup] Content DB error: %s", exc)

    if os.environ.get("FOLLOWUP_SCHEDULER_ENABLED", "true").lower() == "true":
        from app.agents.closing_followup_agent import followup_scheduler_loop

        interval = float(os.environ.get("FOLLOWUP_INTERVAL_HOURS", "6"))
        _followup_task = asyncio.create_task(followup_scheduler_loop(interval))
        logger.info("[Startup] Followup scheduler cada %sh", interval)


async def on_shutdown() -> None:
    """Cancela tareas en background al apagar."""
    global _followup_task
    if _followup_task and not _followup_task.done():
        _followup_task.cancel()
        try:
            await _followup_task
        except asyncio.CancelledError:
            pass
