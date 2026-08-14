"""
app/database/supabase_client.py — Punto único de acceso a la base de datos.

Backend por defecto: PocketBase (VPS).
Alternativa legacy: Supabase (DB_BACKEND=supabase).

Variables PocketBase:
  POCKETBASE_URL, POCKETBASE_EMAIL, POCKETBASE_PASSWORD
"""

import logging
import os

logger = logging.getLogger(__name__)

_client = None


def get_backend() -> str:
    return os.environ.get("DB_BACKEND", "pocketbase").lower().strip()


def get_client():
    """
    Retorna cliente de base de datos según DB_BACKEND.
    PocketBase: adaptador compatible con .table().select().eq().execute()
    Supabase:   cliente supabase-py legacy
    """
    global _client
    if _client is not None:
        return _client

    backend = get_backend()

    if backend == "pocketbase":
        from app.database.pocketbase_adapter import get_pocketbase_client
        _client = get_pocketbase_client()
        logger.info("[DB] Backend PocketBase activo")
        return _client

    # ── Legacy Supabase ───────────────────────────────────────────────────────
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        logger.error("[DB] Supabase seleccionado pero faltan SUPABASE_URL / SUPABASE_KEY")
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
        logger.info("[DB] Backend Supabase activo")
        return _client
    except Exception as e:
        logger.error(f"[DB] Error Supabase: {e}")
        return None


def db_health() -> dict:
    if get_backend() == "pocketbase":
        from app.database.pocketbase_client import health_check
        return health_check()
    return {"backend": "supabase", "configured": bool(os.environ.get("SUPABASE_URL"))}


# ══════════════════════════════════════════════════════════════════════════════
# Operaciones de dominio (backend-agnósticas vía get_client)
# ══════════════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# Operación 1 — leads_crm
# ══════════════════════════════════════════════════════════════════════════════

def upsert_lead_crm(
    tenant_id:  str,
    telefono:   str,
    nombre:     str     = "",
    estado:     str     = "contactado",
    lead_score: int     = 5,
    fuente:     str     = "vapi",
    notas:      str     = "",
    metadata:   dict    = None,
) -> Optional[str]:
    """
    Crea o actualiza un lead en la tabla leads_crm.

    La unicidad es (tenant_id, telefono): si el lead ya existe, actualiza
    estado, lead_score y notas. Si es nuevo, lo inserta.

    Args:
        tenant_id:  ID del tenant (= client_id en Vapi).
        telefono:   Número del lead (normalizado o como viene de Vapi).
        nombre:     Nombre del lead (si está disponible).
        estado:     'nuevo' | 'contactado' | 'calificado' | 'propuesta' | 'cerrado' | 'perdido'
        lead_score: Puntuación 1-10.
        fuente:     Origen del lead.
        notas:      Texto libre con contexto de la llamada.
        metadata:   Dict con datos adicionales (vapi_call_id, duracion, etc.)

    Returns:
        UUID del lead (str) o None si falló.
    """
    db = get_client()
    if not db:
        logger.warning(f"[leads_crm] Sin cliente DB — lead '{telefono}' no guardado.")
        return None

    # Validar estado
    estados_validos = {"nuevo", "contactado", "calificado", "propuesta", "cerrado", "perdido"}
    if estado not in estados_validos:
        estado = "contactado"

    # Clampar score
    lead_score = max(1, min(10, int(lead_score)))

    now = datetime.now(timezone.utc).isoformat()

    fila = {
        "tenant_id":  tenant_id,
        "nombre":     nombre or "",
        "telefono":   telefono or "",
        "fuente":     fuente,
        "lead_score": lead_score,
        "estado":     estado,
        "notas":      notas or "",
        "metadata":   metadata or {},
        "updated_at": now,
    }

    try:
        # upsert: insert si no existe, update si ya existe (por tenant_id + telefono)
        res = (
            db.table("leads_crm")
            .upsert(fila, on_conflict="tenant_id,telefono")
            .execute()
        )
        lead_id = res.data[0]["id"] if res.data else None
        logger.info(
            f"[leads_crm] tenant='{tenant_id}' | tel='{telefono}' | "
            f"estado='{estado}' | score={lead_score} | id={lead_id}"
        )
        return lead_id
    except Exception as e:
        logger.error(f"[leads_crm] Error en upsert: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Operación 2 — historial_llamadas
# ══════════════════════════════════════════════════════════════════════════════

def insert_historial_llamada(
    tenant_id:      str,
    telefono:       str,
    resultado:      str     = "desconocido",
    transcripcion:  str     = "",
    resumen_ia:     str     = "",
    duracion_seg:   int     = 0,
    puntuacion:     int     = 5,
    modo_operacion: str     = "venta",
    vapi_call_id:   str     = "",
    lead_id:        Optional[str] = None,
    metadata:       dict    = None,
) -> Optional[str]:
    """
    Inserta UN nuevo registro en historial_llamadas por cada llamada finalizada.
    Nunca hace upsert — cada llamada es un evento único e inmutable.

    Args:
        tenant_id:      ID del tenant.
        telefono:       Número del llamante.
        resultado:      'cerrado' | 'perdido' | 'no_contesto' | 'desconocido'
        transcripcion:  Texto completo de la conversación.
        resumen_ia:     Resumen/análisis de Vapi o de Claude.
        duracion_seg:   Duración en segundos.
        puntuacion:     Score de la llamada (1-10).
        modo_operacion: Modo del agente que atendió.
        vapi_call_id:   ID de la llamada en Vapi (para trazabilidad).
        lead_id:        UUID del lead en leads_crm (si existe).
        metadata:       Dict con datos extras de Vapi.

    Returns:
        UUID del registro creado o None si falló.
    """
    db = get_client()
    if not db:
        logger.warning(f"[historial] Sin cliente DB — llamada '{vapi_call_id}' no guardada.")
        return None

    resultados_validos = {"cerrado", "perdido", "no_contesto", "desconocido"}
    if resultado not in resultados_validos:
        resultado = "desconocido"

    puntuacion = max(1, min(10, int(puntuacion)))

    fila = {
        "tenant_id":      tenant_id,
        "lead_id":        lead_id,
        "telefono":       telefono or "",
        "resultado":      resultado,
        "transcripcion":  transcripcion or "",
        "resumen_ia":     resumen_ia or "",
        "duracion_seg":   max(0, int(duracion_seg or 0)),
        "puntuacion":     puntuacion,
        "modo_operacion": modo_operacion or "venta",
        "vapi_call_id":   vapi_call_id or "",
        "metadata":       metadata or {},
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }

    try:
        res = db.table("historial_llamadas").insert(fila).execute()
        hist_id = res.data[0]["id"] if res.data else None
        logger.info(
            f"[historial] tenant='{tenant_id}' | call='{vapi_call_id}' | "
            f"resultado='{resultado}' | {duracion_seg}s | id={hist_id}"
        )
        return hist_id
    except Exception as e:
        logger.error(f"[historial] Error en insert: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Operación orquestada — una sola función para Vapi
# ══════════════════════════════════════════════════════════════════════════════

def guardar_llamada_completa(tenant_id: str, call_data: dict) -> dict:
    """
    Orquesta el guardado de una llamada de Vapi completa:
      1. Upsert en leads_crm   (crea/actualiza el lead)
      2. Insert en historial_llamadas (una fila nueva por llamada)

    Args:
        tenant_id: ID del tenant (= client_id en Vapi).
        call_data: Dict con todos los datos de la llamada. Campos esperados:
            telefono        str   — número del lead
            nombre          str   — nombre del lead (puede estar vacío)
            exito           bool  — True si Vapi evaluó la llamada como exitosa
            transcripcion   str   — texto completo de la conversación
            resumen_ia      str   — resumen/análisis de Vapi
            duracion_seg    int   — duración de la llamada en segundos
            vapi_call_id    str   — ID de la llamada en Vapi
            modo_operacion  str   — modo del agente ('venta', 'b2b', etc.)
            puntuacion      int   — score de calidad (1-10)
            metadata        dict  — datos extra de Vapi (opcional)

    Returns:
        {
            "lead_id":        str | None,
            "historial_id":   str | None,
            "lead_estado":    str,
            "lead_score":     int,
        }
    """
    telefono    = call_data.get("telefono", "")
    nombre      = call_data.get("nombre", "")
    exito       = bool(call_data.get("exito", False))
    puntuacion  = int(call_data.get("puntuacion") or (8 if exito else 3))

    # Mapeo de resultado a estado del lead
    estado_lead    = "cerrado"  if exito else "perdido"
    resultado_hist = "cerrado"  if exito else "perdido"

    # Nota automática para el CRM
    duracion = call_data.get("duracion_seg", 0)
    notas = (
        f"Llamada Vapi ({call_data.get('modo_operacion','venta')}) | "
        f"{duracion}s | "
        f"{'VENTA CERRADA' if exito else 'Sin cierre'} | "
        f"ID: {call_data.get('vapi_call_id','')}"
    )
    if call_data.get("resumen_ia"):
        notas += f"\nResumen: {call_data['resumen_ia'][:300]}"

    metadata_lead = {
        "vapi_call_id":   call_data.get("vapi_call_id", ""),
        "modo_operacion": call_data.get("modo_operacion", "venta"),
        "duracion_seg":   duracion,
        **(call_data.get("metadata") or {}),
    }

    # ── 1. Upsert en leads_crm ────────────────────────────────────────────────
    lead_id = upsert_lead_crm(
        tenant_id  = tenant_id,
        telefono   = telefono,
        nombre     = nombre,
        estado     = estado_lead,
        lead_score = puntuacion,
        fuente     = "vapi",
        notas      = notas,
        metadata   = metadata_lead,
    )

    # ── 2. Insert en historial_llamadas ───────────────────────────────────────
    historial_id = insert_historial_llamada(
        tenant_id      = tenant_id,
        telefono       = telefono,
        resultado      = resultado_hist,
        transcripcion  = call_data.get("transcripcion", ""),
        resumen_ia     = call_data.get("resumen_ia", ""),
        duracion_seg   = duracion,
        puntuacion     = puntuacion,
        modo_operacion = call_data.get("modo_operacion", "venta"),
        vapi_call_id   = call_data.get("vapi_call_id", ""),
        lead_id        = lead_id,
        metadata       = call_data.get("metadata") or {},
    )

    return {
        "lead_id":      lead_id,
        "historial_id": historial_id,
        "lead_estado":  estado_lead,
        "lead_score":   puntuacion,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Compatibilidad con el código legado de SupabaseDB
# ══════════════════════════════════════════════════════════════════════════════

class SupabaseDB:
    """
    Clase legada — mantenida para compatibilidad con código existente.
    Para nuevas funciones usar get_client() directamente.
    """

    def __init__(self):
        self.client = get_client()
        if self.client:
            print("[Supabase] SupabaseDB listo.")
        else:
            print("[Supabase] SupabaseDB sin conexion (faltan credenciales).")

    def get_or_create_lead(self, phone: str):
        if not self.client:
            return {"id": "no-db", "phone": phone}
        try:
            res = self.client.table("leads").select("*").eq("phone", phone).execute()
            if res.data:
                return res.data[0]
            new_lead = {"phone": phone, "status": "NUEVO"}
            res = self.client.table("leads").insert(new_lead).execute()
            return res.data[0]
        except Exception:
            return {"id": "error", "phone": phone}

    def save_message(self, lead_id: str, role: str, content: str):
        if not self.client or lead_id in ("no-db", "error"):
            return
        try:
            self.client.table("messages").insert(
                {"lead_id": lead_id, "role": role, "content": content}
            ).execute()
        except Exception:
            pass

    def get_chat_history(self, lead_id: str, limit: int = 5):
        if not self.client or lead_id in ("no-db", "error"):
            return []
        try:
            res = (
                self.client.table("messages")
                .select("role, content")
                .eq("lead_id", lead_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return (res.data or [])[::-1]
        except Exception:
            return []


def guardar_venta(*args, **kwargs) -> bool:
    """
    Wrapper de compatibilidad para el código legado en vapi_handler.
    La firma puede ser:
      - guardar_venta(data: dict)
      - guardar_venta(telefono, monto, fuente, estado, canal)   ← firma antigua
    """
    if len(args) == 1 and isinstance(args[0], dict):
        data = args[0]
    elif len(args) >= 4:
        data = {
            "telefono": args[0],
            "monto":    args[1],
            "fuente":   args[2] if len(args) > 2 else "vapi",
            "estado":   args[3] if len(args) > 3 else "desconocido",
        }
    else:
        data = kwargs

    logger.info(f"[guardar_venta legacy] {data}")
    return True
