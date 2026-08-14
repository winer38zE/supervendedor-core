"""
Idempotencia de webhooks — evita procesar el mismo evento dos veces.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 86400  # 24 h
_lock = threading.Lock()
_memory: dict[str, float] = {}  # event_key -> monotonic expiry


def _cleanup_expired() -> None:
    now = time.monotonic()
    expired = [k for k, exp in _memory.items() if exp <= now]
    for k in expired:
        del _memory[k]


def _memory_key(source: str, event_id: str) -> str:
    return f"{source}:{event_id}"


def is_processed(source: str, event_id: str) -> bool:
    if not event_id:
        return False

    key = _memory_key(source, event_id)

    with _lock:
        _cleanup_expired()
        if key in _memory:
            return True

    # PocketBase (opcional)
    try:
        from app.database.pocketbase_client import list_records
        existing = list_records(
            "processed_events",
            filter_expr=f"(source={_pb_quote(source)}&&event_id={_pb_quote(event_id)})",
            per_page=1,
        )
        if existing:
            with _lock:
                _memory[key] = time.monotonic() + _TTL_SECONDS
            return True
    except Exception:
        pass

    return False


def mark_processed(source: str, event_id: str) -> None:
    if not event_id:
        return

    key = _memory_key(source, event_id)
    with _lock:
        _memory[key] = time.monotonic() + _TTL_SECONDS

    try:
        from app.database.pocketbase_client import create_record
        create_record("processed_events", {
            "source": source,
            "event_id": event_id,
        })
    except Exception as e:
        logger.debug(f"[ProcessedEvents] PocketBase opcional: {e}")


def extract_whatsapp_event_id(payload: dict) -> Optional[str]:
    msg_data = payload.get("data", {}) or {}
    key = msg_data.get("key", {}) or {}
    msg_id = key.get("id")
    if msg_id:
        return str(msg_id)
    remote = key.get("remoteJid", "")
    ts = msg_data.get("messageTimestamp") or payload.get("timestamp")
    if remote and ts:
        return f"{remote}:{ts}"
    return None


def extract_vapi_event_id(payload: dict) -> Optional[str]:
    message = payload.get("message", {}) or {}
    call = message.get("call", {}) or {}
    call_id = call.get("id") or message.get("callId")
    msg_type = message.get("type", "unknown")
    if call_id:
        return f"{call_id}:{msg_type}"
    msg_id = message.get("id")
    if msg_id:
        return str(msg_id)
    return None


def _pb_quote(value: str) -> str:
    return "'" + str(value).replace("'", "\\'") + "'"
