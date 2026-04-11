# app/services/google_calendar.py
"""
Servicio de Google Calendar para ED NET PRO.

Autenticación (en orden de prioridad):
  1. GOOGLE_CREDENTIALS_JSON  — JSON de Service Account como string en variable de entorno.
  2. GOOGLE_TOKEN_JSON        — JSON de token OAuth2 como string en variable de entorno.
  3. credentials.json         — Archivo de Service Account en la raíz del proyecto (dev local).
  4. MOCK MODE                — Si no hay credenciales, simula el evento y retorna OK.

El Service Account debe tener acceso al calendario:
  Google Calendar → Compartir con → <email del service account> (rol: Hacer cambios en eventos)
"""

import json
import os
import re
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateparser
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
CALENDAR_ID    = os.environ.get("GOOGLE_CALENDAR_ID", "zeinn05.1983@gmail.com")
TIMEZONE       = os.environ.get("CALENDAR_TIMEZONE", "America/Bogota")
EVENT_DURATION = int(os.environ.get("CALENDAR_EVENT_DURATION_MIN", 60))   # minutos
SCOPES         = ["https://www.googleapis.com/auth/calendar"]


# ── Autenticación ──────────────────────────────────────────────────────────────

def _build_service():
    """
    Construye y devuelve el cliente autenticado de Google Calendar.
    Lanza RuntimeError en modo mock (sin credenciales).
    """
    # Opción 1: Service Account desde variable de entorno
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info  = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("calendar", "v3", credentials=creds)

    # Opción 2: Token OAuth2 desde variable de entorno
    token_json = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
        return build("calendar", "v3", credentials=creds)

    # Opción 3: Archivo credentials.json local
    creds_file = "credentials.json"
    if os.path.isfile(creds_file):
        creds = service_account.Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        return build("calendar", "v3", credentials=creds)

    raise RuntimeError("MOCK_MODE")


# ── Parseo de fecha y hora ─────────────────────────────────────────────────────

_TIME_REPLACEMENTS = {
    r"\b(\d{1,2})\s*de\s*la\s*tarde\b":  lambda m: f"{int(m.group(1)) + 12}:00",
    r"\b(\d{1,2})\s*de\s*la\s*mañana\b": lambda m: f"{int(m.group(1))}:00",
    r"\b(\d{1,2})\s*pm\b":               lambda m: f"{int(m.group(1)) + 12}:00",
    r"\b(\d{1,2})\s*am\b":               lambda m: f"{int(m.group(1))}:00",
}


def _parse_datetime(fecha: str, hora: str) -> datetime:
    """
    Convierte strings de fecha y hora (incluyendo lenguaje natural en español)
    a un objeto datetime con zona horaria.

    Ejemplos válidos:
      fecha="2026-03-25"  hora="10:30"
      fecha="mañana"      hora="3 de la tarde"
      fecha="el lunes"    hora="9am"
    """
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Normalizar hora: "3 de la tarde" → "15:00", "9am" → "9:00"
    hora_normalizada = hora.strip().lower()
    for pattern, replacer in _TIME_REPLACEMENTS.items():
        hora_normalizada = re.sub(pattern, replacer, hora_normalizada, flags=re.IGNORECASE)

    combined = f"{fecha} {hora_normalizada}"

    parsed = dateparser.parse(
        combined,
        languages=["es", "en"],
        settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE":          TIMEZONE,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE":     now,
        },
    )

    if parsed is None:
        # Último fallback: mañana a la hora dada
        fallback_hora = dateparser.parse(hora_normalizada, languages=["es", "en"])
        hora_obj = fallback_hora.time() if fallback_hora else datetime.strptime("10:00", "%H:%M").time()
        parsed = datetime.combine(now.date() + timedelta(days=1), hora_obj).replace(tzinfo=tz)

    return parsed


# ── Función principal ──────────────────────────────────────────────────────────

def crear_evento(
    nombre:     str,
    fecha:      str,
    hora:       str,
    titulo:     str | None = None,
    descripcion: str | None = None,
    client_id:  str = "default",
) -> dict:
    """
    Crea un evento en Google Calendar.

    Args:
        nombre:      Nombre del cliente.
        fecha:       Fecha (ISO o lenguaje natural en español).
        hora:        Hora (HH:MM o lenguaje natural).
        titulo:      Título del evento. Si es None, se genera automáticamente.
        descripcion: Descripción adicional del evento.
        client_id:   ID del negocio (usado para personalizar el título).

    Returns:
        dict con keys:
          - success (bool)
          - event_id (str)     — ID de Google Calendar
          - event_link (str)   — URL del evento
          - start_iso (str)    — Fecha/hora inicio en ISO
          - mock (bool)        — True si fue simulado (sin credenciales)
          - error (str)        — Presente solo si success=False
    """
    try:
        start_dt = _parse_datetime(fecha, hora)
    except Exception as e:
        return {"success": False, "error": f"No se pudo interpretar la fecha/hora: {e}"}

    end_dt       = start_dt + timedelta(minutes=EVENT_DURATION)
    event_titulo = titulo or f"Cita — {nombre} [{client_id}]"
    event_desc   = descripcion or f"Cita agendada vía ED NET PRO para el cliente: {nombre}"

    event_body = {
        "summary":     event_titulo,
        "description": event_desc,
        "start":       {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end":         {"dateTime": end_dt.isoformat(),   "timeZone": TIMEZONE},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email",  "minutes": 60},
                {"method": "popup",  "minutes": 15},
            ],
        },
    }

    # ── Intentar con Google Calendar real ─────────────────────────────────────
    try:
        service = _build_service()
        created = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        logger.info("Evento creado: %s | %s", created.get("id"), start_dt.isoformat())
        return {
            "success":    True,
            "event_id":   created.get("id", ""),
            "event_link": created.get("htmlLink", ""),
            "start_iso":  start_dt.isoformat(),
            "mock":       False,
        }

    except RuntimeError as e:
        if str(e) == "MOCK_MODE":
            # Sin credenciales → simular evento
            mock_id = f"mock_{nombre.replace(' ', '_').lower()}_{start_dt.strftime('%Y%m%d%H%M')}"
            logger.warning("[MOCK] Evento simulado: %s @ %s", mock_id, start_dt.isoformat())
            return {
                "success":    True,
                "event_id":   mock_id,
                "event_link": "https://calendar.google.com (modo local)",
                "start_iso":  start_dt.isoformat(),
                "mock":       True,
            }
        return {"success": False, "error": str(e)}

    except HttpError as e:
        logger.error("Google Calendar HttpError: %s", e)
        return {"success": False, "error": f"Google Calendar: {e.reason}"}

    except Exception as e:
        logger.error("Error inesperado en Google Calendar: %s", e)
        return {"success": False, "error": str(e)}
