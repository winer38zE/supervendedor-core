"""
app/marketing/ads_rules_engine.py
────────────────────────────────────────────────────────────────────────────────
Capa 4 — Motor de decisión / reglas de rentabilidad Meta Ads.

evaluar_campanas() corre sobre campañas ACTIVE:
  - Pausa si gasto >= umbral y CPA > máximo (campaa con >= 48h).
  - Escala presupuesto si ROAS 24h >= objetivo (cooldown entre escalados).
  - Frena escalados si gasto diario de cuenta >= límite global.

Registra cada acción en ads_actions_log (PocketBase + JSONL local).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from app.marketing.meta_api import MetaAdsManager
from app.services.whatsapp_sender import send_whatsapp_text

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Constantes configurables — ajustar en .env sin tocar lógica
# ══════════════════════════════════════════════════════════════════════════════

UMBRAL_MINIMO_DATOS = float(os.environ.get("ADS_UMBRAL_MINIMO_DATOS", "15000"))
CPA_MAXIMO_ACEPTABLE = float(os.environ.get("ADS_CPA_MAXIMO_ACEPTABLE", "25000"))
ROAS_OBJETIVO = float(os.environ.get("ADS_ROAS_OBJETIVO", "2.5"))
PORCENTAJE_ESCALADO = float(os.environ.get("ADS_PORCENTAJE_ESCALADO", "20"))
HORAS_MIN_ENTRE_ESCALADOS = int(os.environ.get("ADS_HORAS_MIN_ENTRE_ESCALADOS", "24"))
HORAS_MIN_CAMPANA_NUEVA = int(os.environ.get("ADS_HORAS_MIN_CAMPANA_NUEVA", "48"))
LIMITE_DIARIO_CUENTA = float(os.environ.get("ADS_LIMITE_DIARIO_CUENTA", "200000"))

# Proxies cuando no hay conversiones (campaña nueva o pixel sin datos)
CPC_MAXIMO_ACEPTABLE = float(os.environ.get("ADS_CPC_MAXIMO_ACEPTABLE", "3000"))
CTR_MINIMO_ACEPTABLE = float(os.environ.get("ADS_CTR_MINIMO_ACEPTABLE", "0.8"))

ADS_NOTIFY_WHATSAPP = os.environ.get("ADS_NOTIFY_WHATSAPP", os.environ.get("OWNER_WHATSAPP", ""))

_LOG_DIR = Path(os.environ.get("ADS_ACTIONS_LOG_DIR", "app/marketing/logs"))
_ACTIONS_FILE = _LOG_DIR / "ads_actions_log.jsonl"
_SCALE_STATE_FILE = _LOG_DIR / "ads_scale_cooldown.json"

_lock = threading.Lock()
_scale_cooldown: dict[str, str] = {}  # campaign_id -> last_scale ISO


AccionTipo = Literal["pausar", "escalar", "sin_accion", "skip", "error"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_scale_cooldown() -> None:
    global _scale_cooldown
    if _SCALE_STATE_FILE.is_file():
        try:
            _scale_cooldown = json.loads(_SCALE_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _scale_cooldown = {}


def _save_scale_cooldown() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _SCALE_STATE_FILE.write_text(json.dumps(_scale_cooldown, ensure_ascii=False, indent=2), encoding="utf-8")


def _puede_escalar(campaign_id: str) -> tuple[bool, str]:
    with _lock:
        _load_scale_cooldown()
        last = _scale_cooldown.get(campaign_id)
        if not last:
            return True, ""
        try:
            dt = datetime.fromisoformat(last)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            horas = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if horas < HORAS_MIN_ENTRE_ESCALADOS:
                return False, f"cooldown escalado ({horas:.1f}h < {HORAS_MIN_ENTRE_ESCALADOS}h)"
        except Exception:
            pass
        return True, ""


def _marcar_escalado(campaign_id: str) -> None:
    with _lock:
        _load_scale_cooldown()
        _scale_cooldown[campaign_id] = _now_iso()
        _save_scale_cooldown()


def registrar_accion(
    *,
    campaign_id: str,
    campaign_name: str,
    accion: AccionTipo,
    motivo: str,
    metricas: dict[str, Any],
    presupuesto_anterior: float | None = None,
    presupuesto_nuevo: float | None = None,
) -> None:
    """Auditoría PocketBase + JSONL local."""
    entry = {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "accion": accion,
        "motivo": motivo,
        "metricas": metricas,
        "presupuesto_anterior_cop": presupuesto_anterior,
        "presupuesto_nuevo_cop": presupuesto_nuevo,
        "created_at": _now_iso(),
    }

    try:
        from app.database.pocketbase_client import create_record
        create_record("ads_actions_log", entry)
    except Exception as e:
        logger.debug("[AdsRules] PocketBase opcional: %s", e)

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _ACTIONS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("[AdsRules] No se pudo escribir log: %s", e)


def _notificar_whatsapp(texto: str) -> None:
    phone = (ADS_NOTIFY_WHATSAPP or "").strip()
    if phone:
        send_whatsapp_text(phone, texto)
    else:
        logger.info("[AdsRules] WhatsApp: %s", texto[:200])


def _campana_es_muy_nueva(hours_since_created: float | None) -> bool:
    if hours_since_created is None:
        return True
    return hours_since_created < HORAS_MIN_CAMPANA_NUEVA


def _evaluar_pausa(summary: dict[str, Any], hours: float | None) -> tuple[bool, str, dict]:
    """Decide si pausar por CPA/CPC malo."""
    spend = float(summary.get("spend") or 0)
    cpa = summary.get("cpa")
    cpc = float(summary.get("cpc") or 0)
    ctr = float(summary.get("ctr") or 0)

    metricas = {
        "spend": spend,
        "cpa": cpa,
        "cpc": cpc,
        "ctr": ctr,
        "hours_since_created": hours,
    }

    if _campana_es_muy_nueva(hours):
        return False, f"campaña < {HORAS_MIN_CAMPANA_NUEVA}h — sin pausa automática", metricas

    if spend < UMBRAL_MINIMO_DATOS:
        return False, f"spend {spend:.0f} < umbral {UMBRAL_MINIMO_DATOS:.0f}", metricas

    if cpa is not None and float(cpa) > CPA_MAXIMO_ACEPTABLE:
        return True, f"CPA {cpa:.0f} > máximo {CPA_MAXIMO_ACEPTABLE:.0f} (spend {spend:.0f})", metricas

    if cpa is None and cpc > CPC_MAXIMO_ACEPTABLE:
        return True, f"CPC proxy {cpc:.0f} > máximo {CPC_MAXIMO_ACEPTABLE:.0f} (sin conversiones)", metricas

    if cpa is None and ctr < CTR_MINIMO_ACEPTABLE and spend >= UMBRAL_MINIMO_DATOS:
        return True, f"CTR proxy {ctr:.2f}% < mínimo {CTR_MINIMO_ACEPTABLE}%", metricas

    return False, "dentro de parámetros", metricas


def _evaluar_escalado(summary_24h: dict[str, Any], hours: float | None) -> tuple[bool, str, dict]:
    """Decide si escalar por ROAS 24h."""
    spend = float(summary_24h.get("spend") or 0)
    roas = summary_24h.get("roas")
    cpa = summary_24h.get("cpa")

    metricas = {
        "spend_24h": spend,
        "roas_24h": roas,
        "cpa_24h": cpa,
        "hours_since_created": hours,
    }

    if _campana_es_muy_nueva(hours):
        return False, f"campaña < {HORAS_MIN_CAMPANA_NUEVA}h — sin escalar", metricas

    if roas is None:
        return False, "sin ROAS en 24h (pixel/conversiones)", metricas

    if float(roas) < ROAS_OBJETIVO:
        return False, f"ROAS 24h {roas} < objetivo {ROAS_OBJETIVO}", metricas

    if spend < UMBRAL_MINIMO_DATOS * 0.25:
        return False, f"spend 24h {spend:.0f} insuficiente para escalar con confianza", metricas

    return True, f"ROAS 24h {roas} >= {ROAS_OBJETIVO}", metricas


def _primer_adset_con_presupuesto(meta: MetaAdsManager, campaign_id: str) -> dict | None:
    adsets = meta.obtener_adsets_de_campana(campaign_id)
    for a in adsets:
        if a.get("daily_budget"):
            return a
    return adsets[0] if adsets else None


def evaluar_campanas(
    *,
    meta: MetaAdsManager | None = None,
    notificar: bool = True,
) -> dict[str, Any]:
    """
    Evalúa TODAS las campañas ACTIVE y aplica reglas de pausa/escalado.

    Returns:
        {
          evaluado_at, gasto_cuenta_hoy, limite_diario_alcanzado,
          campanas_evaluadas, pausadas, escaladas, sin_accion, errores
        }
    """
    manager = meta or MetaAdsManager()
    gasto_hoy = manager.get_account_spend_today()
    limite_alcanzado = gasto_hoy >= LIMITE_DIARIO_CUENTA

    resultado: dict[str, Any] = {
        "evaluado_at": _now_iso(),
        "gasto_cuenta_hoy": round(gasto_hoy, 2),
        "limite_diario_cuenta": LIMITE_DIARIO_CUENTA,
        "limite_diario_alcanzado": limite_alcanzado,
        "campanas_evaluadas": 0,
        "pausadas": [],
        "escaladas": [],
        "sin_accion": [],
        "errores": [],
    }

    try:
        activas = manager.listar_campanas_activas()
    except Exception as e:
        logger.exception("[AdsRules] No se pudieron listar campañas")
        resultado["errores"].append({"error": str(e)})
        return resultado

    for camp in activas:
        cid = camp.get("id", "")
        nombre = camp.get("name", cid)
        resultado["campanas_evaluadas"] += 1

        try:
            ins = manager.get_campaign_insights(cid, date_preset="last_7d")
            summary = ins.get("summary") or {}
            hours = summary.get("hours_since_created")

            # ── Regla PAUSA ───────────────────────────────────────────────────
            debe_pausar, motivo_pausa, metricas_pausa = _evaluar_pausa(summary, hours)
            if debe_pausar:
                manager.pausar_campana(cid)
                item = {
                    "campaign_id": cid,
                    "nombre": nombre,
                    "motivo": motivo_pausa,
                    "metricas": metricas_pausa,
                }
                resultado["pausadas"].append(item)
                registrar_accion(
                    campaign_id=cid,
                    campaign_name=nombre,
                    accion="pausar",
                    motivo=motivo_pausa,
                    metricas=metricas_pausa,
                )
                if notificar:
                    _notificar_whatsapp(
                        f"🔴 *Campaña pausada*\n{nombre}\nID: {cid}\n{motivo_pausa}"
                    )
                continue

            # ── Regla ESCALADO ────────────────────────────────────────────────
            if limite_alcanzado:
                msg = f"techo diario cuenta ({gasto_hoy:.0f}/{LIMITE_DIARIO_CUENTA:.0f} COP)"
                resultado["sin_accion"].append({
                    "campaign_id": cid, "nombre": nombre, "motivo": msg,
                })
                registrar_accion(
                    campaign_id=cid, campaign_name=nombre, accion="skip",
                    motivo=msg, metricas=metricas_pausa,
                )
                continue

            puede, motivo_cd = _puede_escalar(cid)
            if not puede:
                resultado["sin_accion"].append({
                    "campaign_id": cid, "nombre": nombre, "motivo": motivo_cd,
                })
                continue

            ins_24 = manager.get_campaign_insights_24h(cid)
            summary_24 = ins_24.get("summary") or {}
            debe_escalar, motivo_escala, metricas_escala = _evaluar_escalado(summary_24, hours)

            if not debe_escalar:
                resultado["sin_accion"].append({
                    "campaign_id": cid, "nombre": nombre, "motivo": motivo_escala,
                })
                registrar_accion(
                    campaign_id=cid, campaign_name=nombre, accion="sin_accion",
                    motivo=motivo_escala, metricas={**metricas_pausa, **metricas_escala},
                )
                continue

            adset = _primer_adset_con_presupuesto(manager, cid)
            if not adset:
                resultado["errores"].append({
                    "campaign_id": cid, "error": "Sin Ad Set con daily_budget",
                })
                continue

            adset_id = adset["id"]
            scale = manager.subir_presupuesto(
                adset_id, PORCENTAJE_ESCALADO, campaign_id=cid,
            )
            _marcar_escalado(cid)

            item = {
                "campaign_id": cid,
                "nombre": nombre,
                "motivo": motivo_escala,
                "adset_id": adset_id,
                "presupuesto_anterior_cop": scale["presupuesto_anterior_cop"],
                "presupuesto_nuevo_cop": scale["presupuesto_nuevo_cop"],
                "porcentaje": PORCENTAJE_ESCALADO,
                "metricas": metricas_escala,
            }
            resultado["escaladas"].append(item)
            registrar_accion(
                campaign_id=cid,
                campaign_name=nombre,
                accion="escalar",
                motivo=motivo_escala,
                metricas=metricas_escala,
                presupuesto_anterior=scale["presupuesto_anterior_cop"],
                presupuesto_nuevo=scale["presupuesto_nuevo_cop"],
            )
            if notificar:
                _notificar_whatsapp(
                    f"🟢 *Campaña escalada +{PORCENTAJE_ESCALADO:.0f}%*\n{nombre}\n"
                    f"Presupuesto: ${scale['presupuesto_anterior_cop']:,.0f} → "
                    f"${scale['presupuesto_nuevo_cop']:,.0f} COP\n{motivo_escala}"
                )

        except Exception as e:
            logger.exception("[AdsRules] Error campaña %s", cid)
            resultado["errores"].append({"campaign_id": cid, "nombre": nombre, "error": str(e)})
            registrar_accion(
                campaign_id=cid, campaign_name=nombre, accion="error",
                motivo=str(e), metricas={},
            )

    logger.info(
        "[AdsRules] Evaluadas=%s pausadas=%s escaladas=%s",
        resultado["campanas_evaluadas"],
        len(resultado["pausadas"]),
        len(resultado["escaladas"]),
    )
    return resultado


def formatear_resumen_whatsapp(resultado: dict[str, Any]) -> str:
    """Formato para n8n / Capa 5."""
    ts = resultado.get("evaluado_at", "")[:19].replace("T", " ")
    lines = [f"📊 *Ciclo de Ads — {ts}*", ""]

    if resultado.get("limite_diario_alcanzado"):
        lines.append(
            f"⛔ Techo diario: ${resultado.get('gasto_cuenta_hoy', 0):,.0f} / "
            f"${resultado.get('limite_diario_cuenta', 0):,.0f} COP"
        )
        lines.append("")

    escaladas = resultado.get("escaladas") or []
    if escaladas:
        lines.append("🟢 *Escaladas:*")
        for e in escaladas:
            lines.append(
                f"• {e.get('nombre')} (+{e.get('porcentaje', PORCENTAJE_ESCALADO):.0f}%) — "
                f"${e.get('presupuesto_nuevo_cop', 0):,.0f} COP"
            )
        lines.append("")

    pausadas = resultado.get("pausadas") or []
    if pausadas:
        lines.append("🔴 *Pausadas:*")
        for p in pausadas:
            lines.append(f"• {p.get('nombre')} — {p.get('motivo')}")
        lines.append("")

    if not escaladas and not pausadas:
        lines.append("✅ Sin cambios en campañas activas.")

    errores = resultado.get("errores") or []
    if errores:
        lines.append(f"⚠️ Errores: {len(errores)}")

    return "\n".join(lines)
