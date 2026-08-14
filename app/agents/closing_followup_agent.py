"""
app/agents/closing_followup_agent.py — CRM Guardian / reactivación de leads estancados.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.funnel import FunnelStage

logger = logging.getLogger(__name__)

STALE_HOURS_DEFAULT = int(os.environ.get("FOLLOWUP_STALE_HOURS", "18"))
MIN_HOURS_BETWEEN_FOLLOWUPS = int(os.environ.get("MIN_HOURS_BETWEEN_FOLLOWUPS", "24"))
OWNER_ID = os.environ.get("OWNER_ID", "edwuar")

_recent_followups: dict[str, datetime] = {}


class ClosingFollowupAgent:

    def __init__(self, tenant_id: str = OWNER_ID, stale_hours: int = STALE_HOURS_DEFAULT):
        self.tenant_id = tenant_id
        self.stale_hours = stale_hours

    async def run_followup_cycle(self) -> dict[str, Any]:
        stale_leads = self._fetch_stale_leads()
        sent = 0
        skipped = 0
        errors = 0
        details: list[dict] = []

        for lead in stale_leads:
            telefono = lead.get("telefono", "")
            lead_id = lead.get("id", telefono)

            skip_reason = self._should_skip_followup(lead_id, telefono, lead)
            if skip_reason:
                logger.info(f"[Followup] Skip {lead_id}: {skip_reason}")
                skipped += 1
                details.append({"lead_id": lead_id, "telefono": telefono, "skipped": skip_reason})
                continue

            try:
                msg = self._build_reactivation_message(lead)
                ok = await self._send_whatsapp(telefono, msg)
                if ok:
                    sent += 1
                    self._mark_followup_sent(lead_id, telefono, lead)
                    details.append({"lead_id": lead_id, "telefono": telefono, "sent": True})
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"[Followup] {telefono}: {e}")
                errors += 1

        return {
            "scanned": len(stale_leads),
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
            "details": details,
        }

    def _should_skip_followup(self, lead_id: str, telefono: str, lead: dict) -> Optional[str]:
        now = datetime.now(timezone.utc)
        min_delta = timedelta(hours=MIN_HOURS_BETWEEN_FOLLOWUPS)

        meta = lead.get("metadata") or {}
        last_db = meta.get("last_followup_sent_at") or meta.get("last_followup_at")
        if last_db:
            try:
                last_dt = datetime.fromisoformat(str(last_db).replace("Z", "+00:00"))
                if now - last_dt < min_delta:
                    return f"último followup hace {(now - last_dt).total_seconds() / 3600:.1f}h (< {MIN_HOURS_BETWEEN_FOLLOWUPS}h)"
            except ValueError:
                pass

        mem_key = lead_id or telefono
        last_mem = _recent_followups.get(mem_key)
        if last_mem and now - last_mem < min_delta:
            return f"cooldown en memoria ({MIN_HOURS_BETWEEN_FOLLOWUPS}h)"

        return None

    def _fetch_stale_leads(self) -> list[dict]:
        from app.database.supabase_client import get_client

        db = get_client()
        if not db:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=self.stale_hours)).isoformat()
        estados = [FunnelStage.NEGOCIANDO.value, FunnelStage.AGENDA_PENDIENTE.value]

        try:
            res = (
                db.table("leads_crm")
                .select("id, telefono, nombre, estado, notas, updated_at, metadata")
                .eq("tenant_id", self.tenant_id)
                .in_("estado", estados)
                .lt("updated_at", cutoff)
                .limit(100)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"[Followup] fetch error: {e}")
            return []

    def _build_reactivation_message(self, lead: dict) -> str:
        estado = lead.get("estado", "")
        nombre = lead.get("nombre") or "amigo/a"

        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        featured = bridge.get_featured_product() or {}
        titulo = featured.get("titulo", "enterizo deportivo trending")
        precio = featured.get("precio_reventa") or featured.get("target_price", 0)

        if estado == FunnelStage.AGENDA_PENDIENTE.value:
            return (
                f"Hola {nombre} 👋\n"
                f"Te escribo porque quedó pendiente *agendar tu cita*.\n"
                f"Tengo *2 cupos* esta semana — ¿prefieres mañana o tarde?\n"
                f"Responde con el día y te confirmo al instante."
            )

        return (
            f"Hola {nombre} 🔥\n"
            f"Tu *{titulo}* sigue en *reserva temporal* por 24h más "
            f"al precio de *${precio:,.0f} COP*.\n"
            f"⚠️ Quedan pocas unidades del catálogo de la semana.\n"
            f"Pago contra entrega en Cúcuta — ¿Lo confirmamos hoy?"
        )

    async def _send_whatsapp(self, telefono: str, text: str) -> bool:
        from app.services.whatsapp_sender import send_whatsapp_text
        return await asyncio.to_thread(send_whatsapp_text, telefono, text)

    def _mark_followup_sent(self, lead_id: str, telefono: str, lead: dict) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        _recent_followups[lead_id or telefono] = datetime.now(timezone.utc)

        from app.database.supabase_client import get_client

        db = get_client()
        if not db or not lead.get("id"):
            return
        try:
            meta = lead.get("metadata") or {}
            meta["last_followup_sent_at"] = now_iso
            meta["last_followup_at"] = now_iso
            db.table("leads_crm").update({
                "metadata": meta,
                "notas": (lead.get("notas") or "") + "\n[Followup] Reactivación enviada.",
            }).eq("id", lead["id"]).execute()
        except Exception as e:
            logger.warning(f"[Followup] mark sent error: {e}")


_agent_instance: Optional[ClosingFollowupAgent] = None


def get_followup_agent() -> ClosingFollowupAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ClosingFollowupAgent()
    return _agent_instance


async def followup_scheduler_loop(interval_hours: float = 6.0) -> None:
    agent = get_followup_agent()
    while True:
        try:
            result = await agent.run_followup_cycle()
            logger.info(f"[FollowupScheduler] {result}")
        except Exception as e:
            logger.error(f"[FollowupScheduler] {e}")
        await asyncio.sleep(interval_hours * 3600)
