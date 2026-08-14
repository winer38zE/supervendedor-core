"""
app/services/whatsapp_sender.py
────────────────────────────────────────────────────────────────────────────────
Envío centralizado de WhatsApp (Evolution API) — usado por gupshup y followup.
"""

from __future__ import annotations

import requests

from app.config import settings


def send_whatsapp_text(telefono: str, text: str) -> bool:
    """Envía texto a número E.164/local sin @s.whatsapp.net."""
    numero = telefono.split("@")[0].replace("+", "").strip()
    url = settings.EVOLUTION_API_URL
    api_key = settings.EVOLUTION_API_KEY
    instance = settings.EVOLUTION_INSTANCE

    if not url or not api_key:
        print(f"[WhatsApp MOCK] → {numero}: {text[:120]}")
        return True

    endpoint = f"{url.rstrip('/')}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"number": numero, "text": text}

    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        print(f"[WhatsApp] → {numero} | HTTP {r.status_code}")
        return r.status_code < 400
    except Exception as e:
        print(f"[WhatsApp ERROR] {e}")
        return False


def send_whatsapp_image(telefono: str, image_url: str, caption: str = "") -> bool:
    """Envía imagen por URL si Evolution lo soporta."""
    numero = telefono.split("@")[0].replace("+", "").strip()
    url = settings.EVOLUTION_API_URL
    api_key = settings.EVOLUTION_API_KEY
    instance = settings.EVOLUTION_INSTANCE

    if not url or not api_key or not image_url:
        if caption:
            return send_whatsapp_text(telefono, caption)
        return False

    endpoint = f"{url.rstrip('/')}/message/sendMedia/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {
        "number": numero,
        "mediatype": "image",
        "media": image_url,
        "caption": caption,
    }

    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        return r.status_code < 400
    except Exception:
        return send_whatsapp_text(telefono, caption or image_url)
