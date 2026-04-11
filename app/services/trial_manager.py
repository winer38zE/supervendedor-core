"""
app/services/trial_manager.py
────────────────────────────────────────────────────────────────────────────────
Gestión del ciclo de vida del trial de 3 días.

Flujo completo:
  1. start_trial()         → crea tenant + wallet, envía WhatsApp de bienvenida
  2. (automático a 72h)    → envía WhatsApp de vencimiento + link de pago
  3. check_and_expire()    → suspende tenants con trial vencido (llamar desde cron)
  4. Recarga de saldo      → reactiva automáticamente (billing.py / agregar_saldo)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..database import get_client
from .billing import add_credit

logger = logging.getLogger(__name__)

TRIAL_DIAS: int = 3
RECHARGE_LINK: str = "https://pay.ednetpro.co/recargar"   # sobreescribible con env var


# ══════════════════════════════════════════════════════════════════════════════
# Registro y arranque del trial
# ══════════════════════════════════════════════════════════════════════════════

def register_tenant(
    tenant_id: str,
    nombre: str,
    email: str,
    telefono: str = "",
) -> dict:
    """
    Registra un nuevo tenant en la plataforma SaaS:
      1. Inserta en public.tenants (estado='trial', 3 días)
      2. Crea public.wallets con balance $0
      3. Envía WhatsApp de bienvenida
      4. Opcionalmente crea / actualiza public.clients_config

    Returns:
        {ok, tenant_id, trial_expira_at, mensaje}
    """
    db = get_client()
    if not db:
        return {"ok": False, "error": "db_no_disponible"}

    ahora = datetime.now(timezone.utc)
    trial_expira = ahora + timedelta(days=TRIAL_DIAS)

    tenant_row = {
        "id":              tenant_id,
        "nombre":          nombre,
        "email":           email,
        "telefono":        telefono or "",
        "plan":            "trial",
        "estado":          "trial",
        "trial_inicia_at": ahora.isoformat(),
        "trial_expira_at": trial_expira.isoformat(),
    }

    try:
        db.table("tenants").upsert(tenant_row, on_conflict="id").execute()
        logger.info(f"[trial] tenant '{tenant_id}' registrado — trial hasta {trial_expira.date()}")
    except Exception as e:
        logger.error(f"[trial] error creando tenant: {e}")
        return {"ok": False, "error": str(e)}

    # Crear wallet
    try:
        db.table("wallets").upsert(
            {"tenant_id": tenant_id, "balance_usd": 0},
            on_conflict="tenant_id"
        ).execute()
    except Exception as e:
        logger.warning(f"[trial] wallet ya existía o error menor: {e}")

    # WhatsApp de bienvenida (no bloquea si falla)
    try:
        _send_welcome_whatsapp(nombre=nombre, telefono=telefono, tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"[trial] WhatsApp bienvenida falló: {e}")

    return {
        "ok": True,
        "tenant_id":      tenant_id,
        "trial_expira_at": trial_expira.isoformat(),
        "mensaje":        f"Trial de {TRIAL_DIAS} dias iniciado. Bienvenida enviada a {telefono}",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Expiración del trial (llamar desde scheduler o endpoint admin)
# ══════════════════════════════════════════════════════════════════════════════

def check_and_expire_trials() -> list[str]:
    """
    Consulta todos los tenants con trial vencido (estado='trial' y trial_expira < NOW).
    Para cada uno:
      1. Suspende la cuenta (estado → 'suspendido')
      2. Envía WhatsApp de cierre con link de pago

    Returns:
        Lista de tenant_ids procesados
    """
    db = get_client()
    if not db:
        return []

    ahora = datetime.now(timezone.utc).isoformat()

    try:
        res = (
            db.table("tenants")
            .select("id, nombre, telefono")
            .eq("estado", "trial")
            .lt("trial_expira_at", ahora)
            .execute()
        )
        expirados = res.data or []
    except Exception as e:
        logger.error(f"[trial] error consultando trials expirados: {e}")
        return []

    procesados = []
    for tenant in expirados:
        tid = tenant["id"]
        try:
            # Suspender
            db.table("tenants").update({"estado": "suspendido"}).eq("id", tid).execute()
            logger.info(f"[trial] '{tid}' suspendido por vencimiento de trial")

            # WhatsApp de cierre
            _send_expiry_whatsapp(
                nombre=tenant.get("nombre", ""),
                telefono=tenant.get("telefono", ""),
                tenant_id=tid,
            )
            procesados.append(tid)
        except Exception as e:
            logger.error(f"[trial] error procesando expiración de '{tid}': {e}")

    return procesados


# ══════════════════════════════════════════════════════════════════════════════
# Mensajes de WhatsApp
# ══════════════════════════════════════════════════════════════════════════════

def _send_welcome_whatsapp(nombre: str, telefono: str, tenant_id: str) -> bool:
    """Envía mensaje de bienvenida. Usa Evolution API o mock."""
    if not telefono:
        logger.warning(f"[trial] sin teléfono para bienvenida de '{tenant_id}'")
        return False

    nombre_corto = nombre.split()[0] if nombre else "amigo"
    mensaje = (
        f"Hola {nombre_corto}! Bienvenido a ED NET PRO 🚀\n\n"
        f"Tu Súper Vendedor IA ya está listo. Tienes *{TRIAL_DIAS} días gratis* "
        f"para cerrar ventas en piloto automático.\n\n"
        f"*¿Cómo funciona?*\n"
        f"• Tu agente de voz llama a tus prospectos\n"
        f"• Califica, convence y agenda citas por ti\n"
        f"• Solo pagas $0.10 USD por cada cierre exitoso\n\n"
        f"¡El trial empieza ahora! Cualquier duda responde aquí."
    )
    return _dispatch_whatsapp(telefono=telefono, mensaje=mensaje, tenant_id=tenant_id)


def _send_expiry_whatsapp(nombre: str, telefono: str, tenant_id: str) -> bool:
    """Envía mensaje de cierre de trial con link de recarga."""
    if not telefono:
        return False

    import os
    link = os.environ.get("RECHARGE_LINK", RECHARGE_LINK)
    nombre_corto = nombre.split()[0] if nombre else "amigo"

    mensaje = (
        f"Hola {nombre_corto}, tu prueba gratuita de *ED NET PRO* acaba de terminar.\n\n"
        f"¿Cuánto cerraste durante el trial? 💰\n\n"
        f"Para seguir con tu Súper Vendedor IA activo, recarga tu saldo:\n"
        f"👉 *{link}*\n\n"
        f"Solo $0.10 USD por cada venta cerrada. Sin mensualidad fija.\n"
        f"Si tienes preguntas, escríbenos aquí. ¡No dejes que tu competencia te adelante!"
    )
    return _dispatch_whatsapp(telefono=telefono, mensaje=mensaje, tenant_id=tenant_id)


def _dispatch_whatsapp(telefono: str, mensaje: str, tenant_id: str) -> bool:
    """Envía el mensaje por Evolution API o imprime en mock."""
    import os
    import httpx

    evolution_url  = os.environ.get("EVOLUTION_API_URL", "")
    evolution_key  = os.environ.get("EVOLUTION_API_KEY", "")
    evolution_inst = os.environ.get("EVOLUTION_INSTANCE", "super_vendedor")

    # Normalizar teléfono (asegurar prefijo 57)
    tel = telefono.replace("+", "").replace("-", "").replace(" ", "")
    if not tel.startswith("57") and len(tel) == 10:
        tel = "57" + tel

    if evolution_url and evolution_key:
        try:
            resp = httpx.post(
                f"{evolution_url}/message/sendText/{evolution_inst}",
                headers={
                    "apikey": evolution_key,
                    "Content-Type": "application/json",
                },
                json={"number": tel, "text": mensaje},
                timeout=10,
            )
            ok = resp.status_code < 300
            logger.info(f"[trial_wa] tenant='{tenant_id}' status={resp.status_code}")
            return ok
        except Exception as e:
            logger.warning(f"[trial_wa] Evolution falló: {e}")

    # Mock
    logger.info(
        f"[trial_wa MOCK] → {tel}\n"
        f"{mensaje[:120]}..."
    )
    return True
