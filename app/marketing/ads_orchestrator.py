"""
app/marketing/ads_orchestrator.py
────────────────────────────────────────────────────────────────────────────────
Capa 5 — Orquestación del ciclo autónomo Meta Ads.

Secuencia run_ads_cycle():
  1. productos_en_tendencia() — inteligencia de producto.
  2. Si hay oportunidad prioritaria → mapear catálogo → armar_campana() (PAUSED).
  3. evaluar_campanas() — pausa / escala campañas ACTIVE.
  4. Resumen consolidado (JSON + WhatsApp opcional).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.whatsapp_sender import send_whatsapp_text

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
ADS_AUTO_LAUNCH_ENABLED = os.environ.get("ADS_AUTO_LAUNCH_ENABLED", "true").lower() == "true"
ADS_MIN_PRIORITY_SCORE = float(os.environ.get("ADS_MIN_PRIORITY_SCORE", "70"))
ADS_MIN_PRIORIDAD = os.environ.get("ADS_MIN_PRIORIDAD", "alta").lower()  # alta | media
ADS_HORAS_COOLDOWN_LANZAMIENTO = int(os.environ.get("ADS_HORAS_COOLDOWN_LANZAMIENTO", "72"))
ADS_CYCLE_NOTIFY = os.environ.get("ADS_CYCLE_NOTIFY", "true").lower() == "true"
ADS_TRENDS_LIMITE = int(os.environ.get("ADS_TRENDS_LIMITE", "10"))
ADS_NOTIFY_WHATSAPP = os.environ.get("ADS_NOTIFY_WHATSAPP", os.environ.get("OWNER_WHATSAPP", ""))

_LOG_DIR = Path(os.environ.get("ADS_ACTIONS_LOG_DIR", "app/marketing/logs"))
_LAUNCHED_FILE = _LOG_DIR / "ads_launched_keywords.json"

_PRIORIDAD_RANK = {"baja": 0, "media": 1, "alta": 2}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_launched() -> dict[str, str]:
    if not _LAUNCHED_FILE.is_file():
        return {}
    try:
        return json.loads(_LAUNCHED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_launched(data: dict[str, str]) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _LAUNCHED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _keyword_en_cooldown(keyword: str) -> tuple[bool, str]:
    launched = _load_launched()
    last = launched.get(keyword.lower().strip())
    if not last:
        return False, ""
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return False, ""
    delta = datetime.now(timezone.utc) - last_dt
    horas = delta.total_seconds() / 3600
    if horas < ADS_HORAS_COOLDOWN_LANZAMIENTO:
        restante = ADS_HORAS_COOLDOWN_LANZAMIENTO - horas
        return True, f"Keyword lanzada hace {horas:.0f}h — cooldown {restante:.0f}h restantes"
    return False, ""


def _marcar_keyword_lanzada(keyword: str) -> None:
    launched = _load_launched()
    launched[keyword.lower().strip()] = _now_iso()
    _save_launched(launched)


def _cumple_umbral_lanzamiento(oportunidad: dict[str, Any], min_score: float) -> tuple[bool, str]:
    score = float(oportunidad.get("priority_score") or 0)
    prioridad = (oportunidad.get("prioridad") or "baja").lower()
    min_rank = _PRIORIDAD_RANK.get(ADS_MIN_PRIORIDAD, 2)
    rank = _PRIORIDAD_RANK.get(prioridad, 0)

    if score < min_score:
        return False, f"Score {score:.0f} < mínimo {min_score:.0f}"
    if rank < min_rank:
        return False, f"Prioridad '{prioridad}' < mínima '{ADS_MIN_PRIORIDAD}'"
    return True, "Cumple umbral de lanzamiento"


def mapear_oportunidad_a_producto(oportunidad: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    """
    Cruza keyword de trend_scout con catalog_bridge.find_product().
    Returns (producto_dict | None, motivo_si_none).
    """
    keyword = (oportunidad.get("keyword") or "").strip()
    if not keyword:
        return None, "Oportunidad sin keyword"

    try:
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        catalog = bridge.find_product(keyword)
    except Exception as e:
        logger.warning("[AdsOrchestrator] Catalog bridge error: %s", e)
        catalog = None

    if not catalog:
        return None, f"Sin match en catálogo para '{keyword}'"

    producto = {
        **catalog,
        "keyword": keyword,
        "nombre_campana": f"EDNET — Trend {keyword[:45]}",
        "contexto_trend": {
            "priority_score": oportunidad.get("priority_score"),
            "prioridad": oportunidad.get("prioridad"),
            "trend_interest": oportunidad.get("trend_interest"),
            "competition_score": oportunidad.get("competition_score"),
            "recomendacion": oportunidad.get("recomendacion"),
        },
    }
    return producto, ""


def formatear_resumen_ciclo_whatsapp(ciclo: dict[str, Any]) -> str:
    """Resumen unificado Capa 5 para WhatsApp / n8n."""
    from app.marketing.ads_rules_engine import formatear_resumen_whatsapp

    ts = (ciclo.get("ejecutado_at") or "")[:19].replace("T", " ")
    lines = [f"🤖 *Ciclo Meta Ads — {ts}*", ""]

    trends = ciclo.get("trends") or {}
    mejor = trends.get("mejor_oportunidad")
    if mejor:
        lines.append(
            f"📈 *Tendencia top:* {mejor.get('keyword')} "
            f"(score {mejor.get('priority_score', 0):.0f}, {mejor.get('prioridad')})"
        )
        lines.append("")

    nueva = ciclo.get("nueva_campana")
    if nueva:
        if nueva.get("ok"):
            lines.append(
                f"🆕 *Nueva campaña PAUSED:* {nueva.get('nombre_campana') or nueva.get('titulo')}\n"
                f"ID: `{nueva.get('campaign_id')}`"
            )
        elif nueva.get("blocked_by_compliance"):
            lines.append(
                f"🚫 *Bloqueada por compliance:* {nueva.get('titulo') or nueva.get('keyword')}\n"
                f"{nueva.get('error', '')}"
            )
        elif nueva.get("skipped"):
            lines.append(f"⏭️ *Lanzamiento omitido:* {nueva.get('motivo')}")
        else:
            lines.append(f"❌ *Error campaña:* {nueva.get('error', 'desconocido')}")
        lines.append("")

    reglas = ciclo.get("reglas") or {}
    if reglas:
        sub = formatear_resumen_whatsapp(reglas)
        # Quitar encabezado duplicado del sub-resumen
        sub_lines = sub.split("\n")
        if sub_lines and sub_lines[0].startswith("📊"):
            sub = "\n".join(sub_lines[2:] if len(sub_lines) > 2 else sub_lines[1:])
        if sub.strip():
            lines.append(sub)

    if len(lines) <= 2:
        lines.append("✅ Ciclo completado sin novedades.")

    return "\n".join(lines).strip()


async def run_ads_cycle(
    *,
    launch_new_campaign: Optional[bool] = None,
    min_priority_score: Optional[float] = None,
    incluir_trends: bool = True,
    evaluar_reglas: bool = True,
    notificar_whatsapp: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Ejecuta el ciclo completo Capa 1 → 2 → 4.

    Returns JSON con trends, nueva_campana, reglas, errores y resumen_whatsapp.
    """
    from app.marketing.trend_scout import productos_en_tendencia

    launch = ADS_AUTO_LAUNCH_ENABLED if launch_new_campaign is None else launch_new_campaign
    min_score = min_priority_score if min_priority_score is not None else ADS_MIN_PRIORITY_SCORE
    notify = ADS_CYCLE_NOTIFY if notificar_whatsapp is None else notificar_whatsapp

    ciclo: dict[str, Any] = {
        "ejecutado_at": _now_iso(),
        "ok": True,
        "trends": None,
        "nueva_campana": None,
        "reglas": None,
        "errores": [],
        "config": {
            "launch_new_campaign": launch,
            "min_priority_score": min_score,
            "incluir_trends": incluir_trends,
            "evaluar_reglas": evaluar_reglas,
        },
    }

    # ── 1) Trend Scout ────────────────────────────────────────────────────────
    if incluir_trends:
        try:
            ciclo["trends"] = productos_en_tendencia(limite=ADS_TRENDS_LIMITE)
        except Exception as e:
            logger.exception("[AdsOrchestrator] productos_en_tendencia falló")
            ciclo["errores"].append({"fase": "trends", "error": str(e)})

    # ── 2) Lanzar campaña si oportunidad ──────────────────────────────────────
    if launch and ciclo.get("trends"):
        mejor = ciclo["trends"].get("mejor_oportunidad")
        if not mejor:
            ciclo["nueva_campana"] = {
                "skipped": True,
                "motivo": "Sin oportunidad con score/prioridad suficiente",
            }
        else:
            keyword = mejor.get("keyword", "")
            en_cooldown, motivo_cd = _keyword_en_cooldown(keyword)
            if en_cooldown:
                ciclo["nueva_campana"] = {"skipped": True, "motivo": motivo_cd, "keyword": keyword}
            else:
                ok_umbral, motivo_umbral = _cumple_umbral_lanzamiento(mejor, min_score)
                if not ok_umbral:
                    ciclo["nueva_campana"] = {
                        "skipped": True,
                        "motivo": motivo_umbral,
                        "keyword": keyword,
                        "oportunidad": mejor,
                    }
                else:
                    producto, motivo_map = mapear_oportunidad_a_producto(mejor)
                    if not producto:
                        ciclo["nueva_campana"] = {
                            "skipped": True,
                            "motivo": motivo_map,
                            "keyword": keyword,
                            "oportunidad": mejor,
                        }
                    else:
                        try:
                            from app.marketing.campaign_builder import armar_campana

                            resultado = await armar_campana(producto)
                            ciclo["nueva_campana"] = {
                                **resultado,
                                "keyword": keyword,
                                "titulo": producto.get("titulo"),
                                "nombre_campana": producto.get("nombre_campana"),
                            }
                            if resultado.get("ok"):
                                _marcar_keyword_lanzada(keyword)
                            elif resultado.get("blocked_by_compliance"):
                                pass  # campaign_builder ya notificó bloqueo
                        except Exception as e:
                            logger.exception("[AdsOrchestrator] armar_campana falló")
                            ciclo["nueva_campana"] = {
                                "ok": False,
                                "error": str(e),
                                "keyword": keyword,
                                "titulo": producto.get("titulo"),
                            }
                            ciclo["errores"].append({"fase": "armar_campana", "error": str(e)})

    elif not launch:
        ciclo["nueva_campana"] = {
            "skipped": True,
            "motivo": "ADS_AUTO_LAUNCH_ENABLED=false o launch_new_campaign=false",
        }

    # ── 3) Rules Engine ───────────────────────────────────────────────────────
    if evaluar_reglas:
        try:
            from app.marketing.ads_rules_engine import evaluar_campanas

            ciclo["reglas"] = evaluar_campanas(notificar=False)
        except Exception as e:
            logger.exception("[AdsOrchestrator] evaluar_campanas falló")
            ciclo["errores"].append({"fase": "reglas", "error": str(e)})
            ciclo["ok"] = False

    if ciclo["errores"]:
        ciclo["ok"] = ciclo["ok"] and len(ciclo["errores"]) == 0

    ciclo["resumen_whatsapp"] = formatear_resumen_ciclo_whatsapp(ciclo)

    if notify and ADS_NOTIFY_WHATSAPP:
        try:
            send_whatsapp_text(ADS_NOTIFY_WHATSAPP, ciclo["resumen_whatsapp"])
            ciclo["whatsapp_enviado"] = True
        except Exception as e:
            logger.warning("[AdsOrchestrator] WhatsApp resumen falló: %s", e)
            ciclo["whatsapp_enviado"] = False
            ciclo["errores"].append({"fase": "whatsapp", "error": str(e)})
    else:
        ciclo["whatsapp_enviado"] = False

    logger.info(
        "[AdsOrchestrator] Ciclo OK=%s trends=%s nueva=%s pausadas=%s escaladas=%s",
        ciclo["ok"],
        bool(ciclo.get("trends")),
        (ciclo.get("nueva_campana") or {}).get("ok"),
        len((ciclo.get("reglas") or {}).get("pausadas") or []),
        len((ciclo.get("reglas") or {}).get("escaladas") or []),
    )
    return ciclo
