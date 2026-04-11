"""
app/routers/gupshup_handler.py — Single Tenant
────────────────────────────────────────────────────────────────────────────────
Webhook de WhatsApp (Evolution API).
Implementa el embudo gamificado:

  Nivel 1 — Prospecto    : Zeus saluda, Athena califica
  Nivel 2 — Calificado   : Athena confirma interés, Hermes entra
  Nivel 3 — Negociando   : Hermes cierra o mueve a agenda
  Nivel 4 — Agenda       : Se recogen fecha/hora y se crea cita
  Nivel 5 — Cerrado      : Deal cerrado, post-venta
"""

from fastapi import APIRouter, Request, BackgroundTasks
from app.orchestrator import ZeusOrchestrator
from app.funnel import FunnelEngine, FunnelStage
from app.config import settings
import requests

router = APIRouter()
zeus   = ZeusOrchestrator()

OWNER_ID = settings.OWNER_ID

# Palabras clave que indican intención de agendar
_KEYWORDS_AGENDA = {
    "cuando", "cuándo", "cita", "agenda", "reunion", "reunión",
    "disponible", "horario", "fecha", "hora", "día", "semana",
    "lunes", "martes", "miercoles", "jueves", "viernes",
}


# ── Webhook principal ─────────────────────────────────────────────────────────

@router.post("/webhook")
async def handle_evolution(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    if data.get("event") == "messages.upsert":
        msg_data     = data.get("data", {})
        remote_jid   = msg_data.get("key", {}).get("remoteJid", "")
        from_me      = msg_data.get("key", {}).get("fromMe", False)
        user_message = (
            msg_data.get("message", {}).get("conversation")
            or msg_data.get("message", {}).get("extendedTextMessage", {}).get("text")
        )

        if user_message and not from_me and remote_jid:
            telefono = remote_jid.split("@")[0]
            funnel   = FunnelEngine(owner_id=OWNER_ID)
            stage    = funnel.get_stage(telefono)

            response_text = await _dispatch(telefono, user_message, stage, funnel)

            if response_text:
                _send_whatsapp(remote_jid, response_text)

            # Evolucionar el knowledge en background tras cada mensaje
            background_tasks.add_task(_try_evolve_knowledge, OWNER_ID)

    return {"status": "ok"}


# ── Dispatch por etapa ────────────────────────────────────────────────────────

async def _dispatch(
    telefono: str,
    mensaje: str,
    stage: FunnelStage,
    funnel: FunnelEngine,
) -> str:

    if stage == FunnelStage.CERRADO:
        return "Gracias por tu confianza. Nos vemos en la cita. Si necesitas algo mas, escribeme."

    if stage == FunnelStage.DESCARTADO:
        return "Entendido, no hay problema. Cuando quieras conocer mas de nuestros servicios aqui estoy."

    if stage == FunnelStage.AGENDA_PENDIENTE:
        return await _handle_agenda(telefono, mensaje, funnel)

    if stage == FunnelStage.NEGOCIANDO:
        return await _handle_negociando(telefono, mensaje, funnel)

    if stage == FunnelStage.CALIFICADO:
        return await _handle_calificado(telefono, mensaje, funnel)

    # PROSPECTO (default)
    return await _handle_prospecto(telefono, mensaje, funnel)


# ── Handlers por etapa ────────────────────────────────────────────────────────

async def _handle_prospecto(
    telefono: str, mensaje: str, funnel: FunnelEngine
) -> str:
    """Nivel 1 — Zeus saluda, Athena evalúa el interés."""
    from app.agents.athena_analyst import AthenaAnalyst
    from datetime import datetime

    athena   = AthenaAnalyst()
    momentum = athena.get_sales_momentum(mensaje, datetime.now(), datetime.now())
    status   = momentum["status"]

    # Sin interés real → Zeus responde brevemente sin avanzar etapa
    if status == "CHURN_RISK":
        resp = zeus.process_message(telefono, mensaje, [], client_id="default")
        return resp["content"]

    # Hay interés → avanzar a CALIFICADO
    level_msg = funnel.level_up_message(FunnelStage.CALIFICADO)
    funnel.advance_stage(
        telefono,
        FunnelStage.CALIFICADO,
        notas=f"Athena: {status} | {momentum['advice']}",
        lead_score=_momentum_to_score(status),
    )
    resp = zeus.process_message(telefono, mensaje, [], client_id="default")
    return f"{level_msg}\n\n{resp['content']}" if level_msg else resp["content"]


async def _handle_calificado(
    telefono: str, mensaje: str, funnel: FunnelEngine
) -> str:
    """Nivel 2 → 3 — Hermes entra a negociar."""
    from app.agents.hermes_negotiator import HermesNegotiator

    level_msg = funnel.level_up_message(FunnelStage.NEGOCIANDO)
    funnel.advance_stage(
        telefono, FunnelStage.NEGOCIANDO,
        notas="Hermes activado"
    )

    hermes    = HermesNegotiator(target_price=500.0, reserve_price=300.0)
    respuesta = hermes.generate_response({"action": "counter", "price": 450.0})
    return f"{level_msg}\n\n{respuesta}" if level_msg else respuesta


async def _handle_negociando(
    telefono: str, mensaje: str, funnel: FunnelEngine
) -> str:
    """Nivel 3 — Hermes cierra o mueve a agenda si detecta intención."""
    from app.agents.hermes_negotiator import HermesNegotiator

    palabras = set(mensaje.lower().split())
    if palabras & _KEYWORDS_AGENDA:
        level_msg = funnel.level_up_message(FunnelStage.AGENDA_PENDIENTE)
        funnel.advance_stage(
            telefono, FunnelStage.AGENDA_PENDIENTE,
            notas="Lead listo para agendar"
        )
        return (
            f"{level_msg}\n\n"
            "Excelente, ya casi cerramos esto.\n"
            "Para agendar la reunion solo necesito:\n"
            "- *Que dia* te queda mejor (ej: martes, jueves)\n"
            "- *Manana o tarde*\n\n"
            "Escribeme algo como: _'martes en la tarde'_"
        )

    hermes    = HermesNegotiator(target_price=500.0, reserve_price=300.0)
    respuesta = hermes.generate_response({"action": "counter", "price": 450.0})
    return respuesta


async def _handle_agenda(
    telefono: str, mensaje: str, funnel: FunnelEngine
) -> str:
    """Nivel 4 — Confirmar y crear la cita en Google Calendar."""
    from app.services.google_calendar import crear_evento

    result = crear_evento(
        nombre=telefono,
        fecha=mensaje,
        hora="",
        titulo="Reunion ED NET PRO — Prospecto",
        client_id="default",
    )

    if result.get("success"):
        level_msg = funnel.level_up_message(FunnelStage.CERRADO)
        funnel.advance_stage(
            telefono, FunnelStage.CERRADO,
            notas=f"Cita: {result.get('start_iso', '')}"
        )
        return (
            f"{level_msg}\n\n"
            f"Cita confirmada para el {result.get('start_iso', 'la fecha acordada')}.\n"
            "Recibirás un recordatorio. Nos vemos pronto."
        )

    return (
        "Perfecto, ya casi esta listo.\n"
        "Confirma la fecha y hora exacta, por ejemplo:\n"
        "*'martes 15 de abril a las 3pm'*"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _momentum_to_score(status: str) -> int:
    return {"HOT_LEAD": 9, "WARM_LEAD": 6, "CHURN_RISK": 2}.get(status, 5)


def _try_evolve_knowledge(owner_id: str) -> None:
    """Intenta evolucionar el knowledge en background (silencioso)."""
    try:
        from app.agents.business_evolver import evolve_business_logic
        evolve_business_logic(client_id=owner_id, tenant_id=owner_id)
    except Exception as e:
        print(f"[Evolver background] {e}")


def _send_whatsapp(remote_jid: str, text: str) -> None:
    """Envía mensaje via Evolution API. En dev imprime en consola."""
    url      = settings.EVOLUTION_API_URL
    api_key  = settings.EVOLUTION_API_KEY
    instance = settings.EVOLUTION_INSTANCE

    if not url or not api_key:
        numero = remote_jid.split("@")[0]
        print(f"[WhatsApp MOCK] → {numero}: {text[:120]}")
        return

    numero   = remote_jid.split("@")[0]
    endpoint = f"{url.rstrip('/')}/message/sendText/{instance}"
    headers  = {"apikey": api_key, "Content-Type": "application/json"}
    payload  = {"number": numero, "text": text}

    try:
        r = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        print(f"[WhatsApp] → {numero} | HTTP {r.status_code}")
    except Exception as e:
        print(f"[WhatsApp ERROR] {e}")
