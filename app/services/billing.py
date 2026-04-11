"""
app/services/billing.py
────────────────────────────────────────────────────────────────────────────────
Lógica de cobro y control de saldo para la plataforma SaaS prepago.

Reglas de negocio:
  - Trial activo (< 3 días): llamadas GRATIS — el saldo no se toca.
  - Post-trial con saldo > 0: -$0.10 USD por cada llamada exitosa (lead cerrado).
  - Saldo = 0 y trial expirado: bloquear nuevas llamadas hasta recargar.
  - Idempotencia: nunca cobrar dos veces el mismo vapi_call_id.

Integración:
  - vapi_handler.py llama can_make_call() antes de devolver el asistente.
  - vapi_handler.py llama deduct_credit() en end-of-call-report si exito=True.
"""

import logging
from datetime import datetime, timezone
from typing import Tuple

from ..database import get_client

logger = logging.getLogger(__name__)

# ── Tarifa ─────────────────────────────────────────────────────────────────────
COSTO_LLAMADA_USD: float = 0.10   # $0.10 USD por lead cerrado / llamada exitosa


# ══════════════════════════════════════════════════════════════════════════════
# Helpers internos
# ══════════════════════════════════════════════════════════════════════════════

def _get_tenant(tenant_id: str) -> dict | None:
    """Retorna el registro completo del tenant o None si no existe."""
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("tenants").select("*").eq("id", tenant_id).single().execute()
        return res.data
    except Exception as e:
        logger.warning(f"[billing] tenant '{tenant_id}' no encontrado: {e}")
        return None


def _get_wallet(tenant_id: str) -> dict | None:
    db = get_client()
    if not db:
        return None
    try:
        res = db.table("wallets").select("*").eq("tenant_id", tenant_id).single().execute()
        return res.data
    except Exception as e:
        logger.warning(f"[billing] wallet '{tenant_id}' no encontrada: {e}")
        return None


def _is_trial_active(tenant: dict) -> bool:
    """True si el tenant está en trial Y aún no expiró."""
    if tenant.get("estado") != "trial":
        return False
    expira_str = tenant.get("trial_expira_at", "")
    if not expira_str:
        return False
    try:
        expira = datetime.fromisoformat(expira_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < expira
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# API Pública
# ══════════════════════════════════════════════════════════════════════════════

def can_make_call(tenant_id: str) -> Tuple[bool, str]:
    """
    Verifica si el tenant puede realizar llamadas ahora mismo.

    Returns:
        (True, "trial")   — en período de prueba gratuito
        (True, "activo")  — tiene saldo suficiente
        (False, "suspendido")         — cuenta suspendida o cancelada
        (False, "saldo_insuficiente") — sin saldo post-trial
        (False, "tenant_not_found")   — no registrado en la plataforma
        (False, "db_error")           — fallo de conexión (no bloquear en producción)
    """
    tenant = _get_tenant(tenant_id)

    if not tenant:
        # Sin registro en Supabase: permitir en modo legacy/desarrollo
        logger.info(f"[billing] tenant '{tenant_id}' no en SaaS — modo legacy permitido")
        return True, "legacy"

    estado = tenant.get("estado", "")

    if estado in ("suspendido", "cancelado"):
        return False, estado

    if _is_trial_active(tenant):
        return True, "trial"

    wallet = _get_wallet(tenant_id)
    if not wallet:
        return False, "saldo_insuficiente"

    balance = float(wallet.get("balance_usd", 0))
    if balance >= COSTO_LLAMADA_USD:
        return True, "activo"

    return False, "saldo_insuficiente"


def deduct_credit(
    tenant_id: str,
    referencia_id: str = "",
    descripcion: str   = "llamada exitosa",
) -> dict:
    """
    Descuenta $0.10 USD del wallet del tenant de forma atómica e idempotente.

    Args:
        tenant_id:     ID del tenant.
        referencia_id: vapi_call_id — garantiza idempotencia.
        descripcion:   Texto para el libro contable.

    Returns:
        {ok, balance_nuevo, cobrado, razon}
        ok=False si está en trial (no se cobra) o hay error.
    """
    tenant = _get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "razon": "tenant_not_found"}

    # En trial activo no se cobra — es gratis
    if _is_trial_active(tenant):
        logger.info(f"[billing] '{tenant_id}' en trial — llamada gratis")
        return {"ok": True, "cobrado": 0.0, "razon": "trial_gratuito"}

    db = get_client()
    if not db:
        return {"ok": False, "razon": "db_error"}

    try:
        res = db.rpc("deducir_saldo", {
            "p_tenant_id":     tenant_id,
            "p_monto_usd":     COSTO_LLAMADA_USD,
            "p_descripcion":   descripcion,
            "p_referencia_id": referencia_id or "",
        }).execute()

        result = res.data
        if isinstance(result, list):
            result = result[0]

        if result.get("ok"):
            logger.info(
                f"[billing] cobrado ${COSTO_LLAMADA_USD} | tenant='{tenant_id}' | "
                f"ref='{referencia_id}' | nuevo_saldo=${result.get('balance_nuevo')}"
            )
            # Si el saldo queda en 0, suspender tenant
            if float(result.get("balance_nuevo", 1)) < COSTO_LLAMADA_USD:
                _suspend_tenant_if_empty(tenant_id, result.get("balance_nuevo", 0))
        else:
            logger.warning(
                f"[billing] no se pudo cobrar | tenant='{tenant_id}' | "
                f"error={result.get('error')}"
            )

        return result

    except Exception as e:
        logger.error(f"[billing] error en deduct_credit: {e}")
        return {"ok": False, "razon": str(e)}


def add_credit(
    tenant_id: str,
    monto_usd: float,
    referencia_id: str = "",
    descripcion: str   = "recarga manual",
    tipo: str          = "credito",
) -> dict:
    """
    Agrega crédito a la wallet del tenant.
    Si estaba suspendido por falta de saldo, lo reactiva automáticamente.
    """
    db = get_client()
    if not db:
        return {"ok": False, "razon": "db_error"}

    try:
        res = db.rpc("agregar_saldo", {
            "p_tenant_id":     tenant_id,
            "p_monto_usd":     float(monto_usd),
            "p_tipo":          tipo,
            "p_descripcion":   descripcion,
            "p_referencia_id": referencia_id or "",
        }).execute()

        result = res.data
        if isinstance(result, list):
            result = result[0]

        logger.info(
            f"[billing] recarga +${monto_usd} | tenant='{tenant_id}' | "
            f"nuevo_saldo=${result.get('balance_nuevo')}"
        )
        return result

    except Exception as e:
        logger.error(f"[billing] error en add_credit: {e}")
        return {"ok": False, "razon": str(e)}


def get_wallet_status(tenant_id: str) -> dict:
    """
    Retorna estado completo del wallet + últimas 10 transacciones.
    """
    db = get_client()
    if not db:
        return {"error": "db_no_disponible"}

    tenant = _get_tenant(tenant_id)
    wallet = _get_wallet(tenant_id)

    try:
        txs_res = (
            db.table("wallet_transactions")
            .select("tipo, monto_usd, descripcion, referencia_id, balance_despues, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        transacciones = txs_res.data or []
    except Exception:
        transacciones = []

    return {
        "tenant_id":      tenant_id,
        "estado":         tenant.get("estado", "desconocido") if tenant else "desconocido",
        "trial_activo":   _is_trial_active(tenant) if tenant else False,
        "trial_expira":   tenant.get("trial_expira_at") if tenant else None,
        "balance_usd":    float(wallet.get("balance_usd", 0)) if wallet else 0.0,
        "total_recargado":float(wallet.get("total_recargado", 0)) if wallet else 0.0,
        "total_gastado":  float(wallet.get("total_gastado", 0)) if wallet else 0.0,
        "costo_por_cierre": COSTO_LLAMADA_USD,
        "transacciones":  transacciones,
    }


# ── Helpers privados ──────────────────────────────────────────────────────────

def _suspend_tenant_if_empty(tenant_id: str, balance: float) -> None:
    """Suspende el tenant si su saldo cayó por debajo del costo mínimo."""
    if float(balance) >= COSTO_LLAMADA_USD:
        return
    db = get_client()
    if not db:
        return
    try:
        db.table("tenants").update({
            "estado": "suspendido",
        }).eq("id", tenant_id).eq("estado", "activo").execute()
        logger.warning(f"[billing] tenant '{tenant_id}' suspendido por saldo insuficiente")
    except Exception as e:
        logger.error(f"[billing] error suspendiendo tenant: {e}")
