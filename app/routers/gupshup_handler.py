"""
app/routers/gupshup_handler.py — Single Tenant
────────────────────────────────────────────────────────────────────────────────
Webhook WhatsApp (Evolution API) con pipeline integrado:

  Catalog Bridge → Objection Killer → Hermes (ZOPA dinámica)
  Hephaestus bajo demanda (catálogo/imágenes/PDF)
  Business Evolver throttled (sin ejecución redundante por mensaje)
"""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import settings
from app.security import verify_evolution_webhook
from app.funnel import FunnelEngine, FunnelStage
from app.orchestrator import ZeusOrchestrator
from app.sales_pipeline import negotiate_response
from app.services.whatsapp_sender import send_whatsapp_image, send_whatsapp_text

router = APIRouter()
zeus = ZeusOrchestrator()
OWNER_ID = settings.OWNER_ID

_KEYWORDS_AGENDA = {
    "cuando", "cuándo", "cita", "agenda", "reunion", "reunión",
    "disponible", "horario", "fecha", "hora", "día", "semana",
    "lunes", "martes", "miercoles", "jueves", "viernes",
}

# Throttle business_evolver: máx 1 vez cada 30 min por tenant
_evolve_last_run: dict[str, float] = {}
_EVOLVE_MIN_INTERVAL_S = 1800


@router.post("/webhook")
async def handle_evolution(request: Request, background_tasks: BackgroundTasks):
    verify_evolution_webhook(request)

    data = await request.json()

    from app.services.processed_events import (
        extract_whatsapp_event_id,
        is_processed,
        mark_processed,
    )

    event_id = extract_whatsapp_event_id(data)
    if event_id and is_processed("whatsapp", event_id):
        return {"status": "ok", "duplicate": True}

    if data.get("event") == "messages.upsert":
        msg_data = data.get("data", {})
        remote_jid = msg_data.get("key", {}).get("remoteJid", "")
        from_me = msg_data.get("key", {}).get("fromMe", False)
        user_message = (
            msg_data.get("message", {}).get("conversation")
            or msg_data.get("message", {}).get("extendedTextMessage", {}).get("text")
        )

        if user_message and not from_me and remote_jid:
            telefono = remote_jid.split("@")[0]
            funnel = FunnelEngine(owner_id=OWNER_ID)
            stage = funnel.get_stage(telefono)

            background_tasks.add_task(_touch_lead_activity, telefono)

            # Hephaestus: catálogo / imágenes / PDF bajo demanda (cualquier etapa activa)
            hepha_response = await _try_hephaestus(user_message, telefono, remote_jid)
            if hepha_response:
                background_tasks.add_task(_maybe_evolve_knowledge, OWNER_ID)
                if event_id:
                    mark_processed("whatsapp", event_id)
                return {"status": "ok"}

            response_text = await _dispatch(telefono, user_message, stage, funnel)

            if response_text:
                send_whatsapp_text(remote_jid, response_text)

            background_tasks.add_task(_maybe_evolve_knowledge, OWNER_ID)

    if event_id:
        mark_processed("whatsapp", event_id)

    return {"status": "ok"}


async def _try_hephaestus(user_message: str, telefono: str, remote_jid: str) -> bool:
    from app.agents.hephaestus_creator import HephaestusCreator

    hepha = HephaestusCreator()
    delivery = hepha.fulfill_catalog_request(user_message, telefono)
    if not delivery:
        return False

    text = delivery.get("text", "")
    image_url = delivery.get("image_url", "")

    if image_url:
        send_whatsapp_image(remote_jid, image_url, caption=text)
    elif text:
        send_whatsapp_text(remote_jid, text)
    return True


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

    return await _handle_prospecto(telefono, mensaje, funnel)


async def _handle_prospecto(telefono: str, mensaje: str, funnel: FunnelEngine) -> str:
    from app.agents.athena_analyst import AthenaAnalyst

    athena = AthenaAnalyst()
    momentum = athena.get_sales_momentum(mensaje, datetime.now(), datetime.now())
    status = momentum["status"]

    if status == "CHURN_RISK":
        resp = zeus.process_message(telefono, mensaje, [], client_id="default")
        return resp["content"]

    level_msg = funnel.level_up_message(FunnelStage.CALIFICADO)
    funnel.advance_stage(
        telefono,
        FunnelStage.CALIFICADO,
        notas=f"Athena: {status} | {momentum['advice']}",
        lead_score=_momentum_to_score(status),
    )
    resp = zeus.process_message(telefono, mensaje, [], client_id="default")
    return f"{level_msg}\n\n{resp['content']}" if level_msg else resp["content"]


async def _handle_calificado(telefono: str, mensaje: str, funnel: FunnelEngine) -> str:
    level_msg = funnel.level_up_message(FunnelStage.NEGOCIANDO)
    funnel.advance_stage(telefono, FunnelStage.NEGOCIANDO, notas="Hermes + Catalog Bridge activados")

    respuesta = negotiate_response(mensaje)
    return f"{level_msg}\n\n{respuesta}" if level_msg else respuesta


async def _handle_negociando(telefono: str, mensaje: str, funnel: FunnelEngine) -> str:
    palabras = set(mensaje.lower().split())
    if palabras & _KEYWORDS_AGENDA:
        level_msg = funnel.level_up_message(FunnelStage.AGENDA_PENDIENTE)
        funnel.advance_stage(
            telefono,
            FunnelStage.AGENDA_PENDIENTE,
            notas="Lead listo para agendar",
        )
        return (
            f"{level_msg}\n\n"
            "Excelente, ya casi cerramos esto.\n"
            "Para agendar la reunion solo necesito:\n"
            "- *Que dia* te queda mejor (ej: martes, jueves)\n"
            "- *Manana o tarde*\n\n"
            "Escribeme algo como: _'martes en la tarde'_"
        )

    return negotiate_response(mensaje)


async def _handle_agenda(telefono: str, mensaje: str, funnel: FunnelEngine) -> str:
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
            telefono,
            FunnelStage.CERRADO,
            notas=f"Cita: {result.get('start_iso', '')}",
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


def _momentum_to_score(status: str) -> int:
    return {"HOT_LEAD": 9, "WARM_LEAD": 6, "CHURN_RISK": 2}.get(status, 5)


def _maybe_evolve_knowledge(owner_id: str) -> None:
    """Evolución throttled — evita llamadas redundantes por cada mensaje."""
    now = time.time()
    last = _evolve_last_run.get(owner_id, 0)
    if now - last < _EVOLVE_MIN_INTERVAL_S:
        return
    _evolve_last_run[owner_id] = now
    try:
        from app.agents.business_evolver import evolve_business_logic
        evolve_business_logic(client_id=owner_id, tenant_id=owner_id)
    except Exception as e:
        print(f"[Evolver background] {e}")


def _touch_lead_activity(telefono: str) -> None:
    """Actualiza updated_at para que followup no dispare en conversaciones activas."""
    try:
        from datetime import timezone
        from app.database.supabase_client import get_client

        db = get_client()
        if not db:
            return
        db.table("leads_crm").update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("tenant_id", OWNER_ID).eq("telefono", telefono).execute()
    except Exception:
        pass
