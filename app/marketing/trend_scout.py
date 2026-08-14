"""
app/marketing/trend_scout.py
────────────────────────────────────────────────────────────────────────────────
Capa 1 — Inteligencia de producto (Google Trends + Meta Ad Library).

Señales:
  1. Interés de búsqueda en Colombia (últimos 7 días) vía pytrends.
  2. Anuncios activos de competencia en Ad Library — los que llevan más días
     corriendo suelen ser los que más convierten (nadie sostiene un loser).

Score de prioridad:
  Alta tendencia + pocos anuncios sostenidos de competencia → lanzar campaña.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
TRENDS_GEO = os.environ.get("META_TRENDS_GEO", "CO")
TRENDS_TIMEFRAME = os.environ.get("META_TRENDS_TIMEFRAME", "now 7-d")
TRENDS_HL = os.environ.get("META_TRENDS_HL", "es-CO")

# Días mínimos corriendo para considerar un anuncio de competencia "sostenido"
MIN_DIAS_ANUNCIO_SOSTENIDO = int(os.environ.get("META_MIN_DIAS_ANUNCIO_SOSTENIDO", "7"))

# Peso del score combinado (tendencia vs competencia)
PESO_TENDENCIA = float(os.environ.get("META_PESO_TENDENCIA", "0.6"))
PESO_BAJA_COMPETENCIA = float(os.environ.get("META_PESO_BAJA_COMPETENCIA", "0.4"))

META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v21.0")
META_AD_LIBRARY_TOKEN = os.environ.get(
    "META_AD_LIBRARY_TOKEN",
    os.environ.get("META_ACCESS_TOKEN", ""),
).strip()

# Keywords base del catálogo ED NET PRO (fallback si no hay Excel cargado)
DEFAULT_CATALOG_KEYWORDS: list[str] = [
    "enterizo deportivo",
    "conjunto deportivo mujer",
    "leggings deportivos",
    "ropa deportiva mujer",
    "biker short",
    "top deportivo",
    "ropa urbana mujer",
    "moda deportiva",
    "enterizo gym",
    "set deportivo",
]

# Máximo keywords por batch en pytrends (límite de la librería ≈ 5)
_PYTRENDS_BATCH = 5


def _catalog_keywords(limit: int = 15) -> list[str]:
    """Extrae keywords del catalog bridge + defaults."""
    keywords: list[str] = []
    try:
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        for p in bridge.get_products(limit=limit):
            titulo = (p.get("titulo") or "").strip()
            if titulo and len(titulo) > 4:
                keywords.append(titulo[:80])
    except Exception as e:
        logger.debug(f"[TrendScout] Catálogo no disponible: {e}")

    env_kw = os.environ.get("META_TREND_KEYWORDS", "")
    if env_kw:
        keywords.extend(k.strip() for k in env_kw.split(",") if k.strip())

    for kw in DEFAULT_CATALOG_KEYWORDS:
        if kw not in keywords:
            keywords.append(kw)

    # Deduplicar preservando orden
    seen: set[str] = set()
    unique: list[str] = []
    for k in keywords:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            unique.append(k)
    return unique[:limit]


def _fetch_google_trends(keywords: list[str]) -> dict[str, float]:
    """
    Devuelve interés medio 0–100 por keyword (últimos 7 días, Colombia).
    Si pytrends falla, devuelve dict vacío.
    """
    if not keywords:
        return {}

    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.error("[TrendScout] Instalá pytrends: pip install pytrends")
        return {}

    scores: dict[str, float] = {}

    try:
        pytrends = TrendReq(hl=TRENDS_HL, tz=300)
    except Exception as e:
        logger.error(f"[TrendScout] TrendReq init error: {e}")
        return {}

    for i in range(0, len(keywords), _PYTRENDS_BATCH):
        batch = keywords[i : i + _PYTRENDS_BATCH]
        try:
            pytrends.build_payload(batch, timeframe=TRENDS_TIMEFRAME, geo=TRENDS_GEO)
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                continue
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"], errors="ignore")
            for kw in batch:
                if kw in df.columns:
                    scores[kw] = round(float(df[kw].mean()), 2)
                else:
                    scores[kw] = 0.0
        except Exception as e:
            logger.warning(f"[TrendScout] pytrends batch {batch}: {e}")
            for kw in batch:
                scores.setdefault(kw, 0.0)

    return scores


def espiar_anuncios_competencia(
    keyword: str,
    *,
    pais: str = "CO",
    limite: int = 50,
) -> dict[str, Any]:
    """
    Consulta Meta Ad Library (Graph API ads_archive) para anuncios ACTIVOS
    que coincidan con la keyword en el país indicado.

    Returns:
        {
          "keyword": str,
          "total_encontrados": int,
          "anuncios_sostenidos": int,   # corriendo >= MIN_DIAS_ANUNCIO_SOSTENIDO
          "competition_score": float,     # 0–100 (más alto = más competencia)
          "anuncios": [                  # ordenados por días corriendo desc
            {
              "id", "page_name", "dias_corriendo", "inicio_entrega",
              "ad_snapshot_url", "sostenido"
            }, ...
          ],
          "error": str | None,
        }
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return _empty_competition_result(keyword, "Keyword vacía")

    if not META_AD_LIBRARY_TOKEN:
        logger.warning("[TrendScout] META_AD_LIBRARY_TOKEN / META_ACCESS_TOKEN vacío")
        return _empty_competition_result(
            keyword,
            "Sin token — configurá META_ACCESS_TOKEN para Ad Library",
        )

    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/ads_archive"
    params: dict[str, Any] = {
        "access_token": META_AD_LIBRARY_TOKEN,
        "search_terms": keyword,
        "ad_reached_countries": f'["{pais}"]',
        "ad_active_status": "ACTIVE",
        "limit": min(limite, 100),
        "fields": ",".join([
            "id",
            "ad_creation_time",
            "ad_delivery_start_time",
            "ad_delivery_stop_time",
            "page_name",
            "ad_snapshot_url",
            "publisher_platforms",
        ]),
    }

    anuncios: list[dict[str, Any]] = []
    try:
        r = httpx.get(url, params=params, timeout=30)
        data = r.json()
        if r.status_code != 200:
            err = data.get("error", {}).get("message", r.text[:200])
            logger.error(f"[TrendScout] Ad Library error: {err}")
            return _empty_competition_result(keyword, str(err))

        for item in data.get("data") or []:
            dias = _dias_corriendo(item.get("ad_delivery_start_time"))
            anuncios.append({
                "id": item.get("id"),
                "page_name": item.get("page_name", ""),
                "dias_corriendo": dias,
                "inicio_entrega": item.get("ad_delivery_start_time"),
                "ad_snapshot_url": item.get("ad_snapshot_url", ""),
                "publisher_platforms": item.get("publisher_platforms") or [],
                "sostenido": dias >= MIN_DIAS_ANUNCIO_SOSTENIDO,
            })
    except Exception as e:
        logger.error(f"[TrendScout] Ad Library request failed: {e}")
        return _empty_competition_result(keyword, str(e))

    anuncios.sort(key=lambda x: x["dias_corriendo"], reverse=True)
    sostenidos = sum(1 for a in anuncios if a["sostenido"])
    total = len(anuncios)

    # 0 anuncios → competencia baja (100 = oportunidad)
    # muchos sostenidos → competencia alta (0 = saturado)
    if total == 0:
        competition_score = 0.0
    else:
        ratio_sostenidos = sostenidos / total
        competition_score = round(min(100.0, ratio_sostenidos * 60 + total * 2), 2)

    return {
        "keyword": keyword,
        "total_encontrados": total,
        "anuncios_sostenidos": sostenidos,
        "competition_score": competition_score,
        "anuncios": anuncios[:20],
        "error": None,
    }


def _empty_competition_result(keyword: str, error: str) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "total_encontrados": 0,
        "anuncios_sostenidos": 0,
        "competition_score": 0.0,
        "anuncios": [],
        "error": error,
    }


def _dias_corriendo(ad_delivery_start: Optional[str]) -> int:
    if not ad_delivery_start:
        return 0
    try:
        # Meta devuelve ISO 8601, ej. 2026-01-15T08:00:00+0000
        start = ad_delivery_start.replace("+0000", "+00:00")
        if start.endswith("Z"):
            start = start[:-1] + "+00:00"
        dt = datetime.fromisoformat(start)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return max(0, delta.days)
    except Exception:
        return 0


def _calcular_priority_score(trend_interest: float, competition_score: float) -> float:
    """
    trend_interest: 0–100 (Google Trends)
    competition_score: 0–100 (más = más competencia sostenida)

    priority = tendencia alta + competencia baja
    """
    trend_norm = max(0.0, min(100.0, trend_interest)) / 100.0
    oportunidad = 1.0 - (max(0.0, min(100.0, competition_score)) / 100.0)
    score = (PESO_TENDENCIA * trend_norm + PESO_BAJA_COMPETENCIA * oportunidad) * 100
    return round(score, 2)


def _clasificar_prioridad(score: float) -> str:
    if score >= 70:
        return "alta"
    if score >= 45:
        return "media"
    return "baja"


def productos_en_tendencia(
    *,
    keywords: Optional[list[str]] = None,
    limite: int = 10,
    incluir_competencia: bool = True,
) -> dict[str, Any]:
    """
    Combina Google Trends + Ad Library en un ranking de oportunidades.

    Returns:
        {
          "generado_at": ISO8601,
          "geo": "CO",
          "timeframe": "now 7-d",
          "productos": [
            {
              "keyword": str,
              "trend_interest": float,       # 0–100
              "competition_score": float,    # 0–100
              "anuncios_sostenidos": int,
              "priority_score": float,       # 0–100
              "prioridad": "alta"|"media"|"baja",
              "competencia_top": [...],      # top 3 anuncios más longevos
              "recomendacion": str,
            }, ...
          ],
          "mejor_oportunidad": dict | None,
        }
    """
    kw_list = keywords or _catalog_keywords(limit=20)
    trend_scores = _fetch_google_trends(kw_list)

    productos: list[dict[str, Any]] = []

    for kw in kw_list:
        interest = trend_scores.get(kw, 0.0)

        if incluir_competencia:
            comp = espiar_anuncios_competencia(kw)
            competition = comp["competition_score"]
            sostenidos = comp["anuncios_sostenidos"]
            top_ads = comp["anuncios"][:3]
            comp_error = comp.get("error")
        else:
            competition = 0.0
            sostenidos = 0
            top_ads = []
            comp_error = None

        priority = _calcular_priority_score(interest, competition)
        prioridad = _clasificar_prioridad(priority)
        recomendacion = _generar_recomendacion(interest, competition, sostenidos, prioridad)

        productos.append({
            "keyword": kw,
            "trend_interest": interest,
            "competition_score": competition,
            "anuncios_sostenidos": sostenidos,
            "priority_score": priority,
            "prioridad": prioridad,
            "competencia_top": top_ads,
            "competencia_error": comp_error,
            "recomendacion": recomendacion,
        })

    productos.sort(key=lambda x: x["priority_score"], reverse=True)
    productos = productos[:limite]

    mejor = productos[0] if productos and productos[0]["priority_score"] >= 45 else None

    return {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "geo": TRENDS_GEO,
        "timeframe": TRENDS_TIMEFRAME,
        "total_analizados": len(kw_list),
        "productos": productos,
        "mejor_oportunidad": mejor,
    }


def _generar_recomendacion(
    interest: float,
    competition: float,
    sostenidos: int,
    prioridad: str,
) -> str:
    if prioridad == "alta":
        return (
            f"Tendencia fuerte ({interest}/100) con competencia moderada "
            f"({sostenidos} anuncios sostenidos). Candidato prioritario para campaña PAUSED."
        )
    if prioridad == "media":
        return (
            f"Señal mixta — tendencia {interest}/100, competencia {competition}/100. "
            "Probar con presupuesto bajo tras revisión de compliance."
        )
    if interest < 20:
        return "Baja demanda de búsqueda en Google — posponer o cambiar keyword."
    if competition > 70:
        return f"Mercado saturado ({sostenidos} anuncios longevos). Diferenciar creative/copy."
    return "Prioridad baja — monitorear una semana más antes de invertir."


def mejor_producto_para_campana() -> Optional[dict[str, Any]]:
    """Atajo: devuelve el producto con mayor priority_score (si >= 45)."""
    result = productos_en_tendencia(limite=1)
    return result.get("mejor_oportunidad")
