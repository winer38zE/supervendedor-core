"""
app/funnel.py
────────────────────────────────────────────────────────────────────────────────
Motor del Embudo Gamificado de Ventas — Single Tenant (Edwuar)

Stages:
  Prospecto → Calificado (Athena) → Negociando (Hermes) → Agenda Pendiente → Cerrado
"""

from enum import Enum
from typing import Optional
import os

OWNER_ID: str = os.environ.get("OWNER_ID", "edwuar")


class FunnelStage(str, Enum):
    PROSPECTO        = "prospecto"
    CALIFICADO       = "calificado"
    NEGOCIANDO       = "negociando"
    AGENDA_PENDIENTE = "agenda_pendiente"
    CERRADO          = "cerrado"
    DESCARTADO       = "descartado"


STAGE_LEVELS = {
    FunnelStage.PROSPECTO:        1,
    FunnelStage.CALIFICADO:       2,
    FunnelStage.NEGOCIANDO:       3,
    FunnelStage.AGENDA_PENDIENTE: 4,
    FunnelStage.CERRADO:          5,
    FunnelStage.DESCARTADO:       0,
}

STAGE_LABELS = {
    FunnelStage.PROSPECTO:        "Contacto inicial",
    FunnelStage.CALIFICADO:       "Interés confirmado",
    FunnelStage.NEGOCIANDO:       "Negociación activa",
    FunnelStage.AGENDA_PENDIENTE: "Cita casi lista",
    FunnelStage.CERRADO:          "DEAL CLOSED",
    FunnelStage.DESCARTADO:       "No califica",
}

STAGE_BADGES = {
    FunnelStage.PROSPECTO:        "🔍",
    FunnelStage.CALIFICADO:       "✅",
    FunnelStage.NEGOCIANDO:       "🤝",
    FunnelStage.AGENDA_PENDIENTE: "📅",
    FunnelStage.CERRADO:          "🎯",
    FunnelStage.DESCARTADO:       "❌",
}


class FunnelEngine:
    """
    Gestiona el estado del embudo por lead (telefono).
    Lee y escribe el campo `estado` en leads_crm de Supabase.
    Si Supabase no está disponible, opera en modo in-memory (dev).
    """

    _memory: dict[str, FunnelStage] = {}   # fallback en memoria para dev

    def __init__(self, owner_id: str = OWNER_ID):
        self.owner_id = owner_id

    # ── Lectura ───────────────────────────────────────────────────────────────

    def get_stage(self, telefono: str) -> FunnelStage:
        """Obtiene la etapa actual del lead desde Supabase (o memoria)."""
        try:
            from app.database.supabase_client import get_client
            db = get_client()
            if db:
                res = (
                    db.table("leads_crm")
                    .select("estado")
                    .eq("tenant_id", self.owner_id)
                    .eq("telefono", telefono)
                    .limit(1)
                    .execute()
                )
                if res.data:
                    estado = res.data[0].get("estado", "prospecto")
                    try:
                        return FunnelStage(estado)
                    except ValueError:
                        return FunnelStage.PROSPECTO
        except Exception as e:
            print(f"[Funnel] get_stage DB error: {e}")

        return FunnelEngine._memory.get(telefono, FunnelStage.PROSPECTO)

    # ── Escritura ─────────────────────────────────────────────────────────────

    def advance_stage(
        self,
        telefono: str,
        new_stage: FunnelStage,
        nombre: str = "",
        notas: str = "",
        lead_score: int = 0,
    ) -> bool:
        """Avanza el lead a la nueva etapa y persiste el cambio."""
        FunnelEngine._memory[telefono] = new_stage  # siempre actualizar memoria

        try:
            from app.database.supabase_client import get_client
            db = get_client()
            if db:
                row = {
                    "tenant_id":  self.owner_id,
                    "telefono":   telefono,
                    "estado":     new_stage.value,
                    "fuente":     "whatsapp",
                }
                if nombre:
                    row["nombre"] = nombre
                if notas:
                    row["notas"] = notas
                if lead_score:
                    row["lead_score"] = lead_score

                db.table("leads_crm").upsert(
                    row, on_conflict="tenant_id,telefono"
                ).execute()
                print(f"[Funnel] {telefono} → {new_stage.value}")
                return True
        except Exception as e:
            print(f"[Funnel] advance_stage DB error: {e}")

        return False

    # ── Gamificación ──────────────────────────────────────────────────────────

    def level_up_message(self, new_stage: FunnelStage) -> str:
        """Retorna el mensaje de nivel desbloqueado (vacío si no aplica)."""
        if new_stage in (FunnelStage.DESCARTADO, FunnelStage.PROSPECTO):
            return ""
        level = STAGE_LEVELS[new_stage]
        badge = STAGE_BADGES[new_stage]
        label = STAGE_LABELS[new_stage]
        return f"{badge} *Nivel {level} desbloqueado — {label}*"

    def stage_info(self, telefono: str) -> dict:
        stage = self.get_stage(telefono)
        return {
            "telefono": telefono,
            "stage":    stage.value,
            "level":    STAGE_LEVELS[stage],
            "label":    STAGE_LABELS[stage],
            "badge":    STAGE_BADGES[stage],
        }
