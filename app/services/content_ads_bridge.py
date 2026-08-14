"""
app/services/content_ads_bridge.py
────────────────────────────────────────────────────────────────────────────────
Puente eficiente Content → Meta Ads.

Reutiliza armar_campana() con copy_override — sin segunda llamada LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.content.models import GeneratedScript
from app.content.schemas import ContentAdsProduct

logger = logging.getLogger(__name__)


def script_to_meta_copy(script: GeneratedScript) -> dict[str, str]:
    """Convierte guion outlier a formato copy Meta — determinístico, sin LLM."""
    title = (script.script_title or script.niche or "ED NET PRO")[:40]
    hook = (script.hook or "").strip()
    body = (script.script_body or "").strip()
    cta = (script.cta or "Escríbenos por WhatsApp").strip()

    texto_parts = [p for p in (hook, body, cta) if p]
    texto_principal = "\n\n".join(texto_parts)[:500]

    return {
        "titulo": title,
        "texto_principal": texto_principal,
        "descripcion": cta[:100],
        "cta": "WHATSAPP_MESSAGE",
        "contexto_producto": f"{script.niche} — guion viral remix {int(script.remix_level * 100)}%",
    }


def catalog_dict_to_content_ads(raw: dict[str, Any]) -> ContentAdsProduct:
    """Mapea producto del Nyx Bridge / catálogo Shein → ContentAdsProduct."""
    titulo = str(raw.get("titulo") or "Producto ED NET PRO")
    goods_id = str(raw.get("goods_id") or "")
    precio = float(raw.get("precio_reventa") or raw.get("precio_cop") or 0)

    return ContentAdsProduct(
        titulo=titulo[:120],
        imagen_url=(raw.get("imagen_url") or None),
        producto_url=(raw.get("producto_url") or None),
        precio_cop=precio if precio > 0 else None,
        keyword=titulo[:120],
        producto_id=goods_id or None,
        nombre_campana=f"EDNET Shein — {titulo[:40]}",
        creative_format="image",
    )


def resolve_trend_keyword(
    *,
    catalog_query: str = "",
    niche: str = "",
    product_focus: str = "",
) -> tuple[str, Optional[str]]:
    """
    Devuelve (keyword para catálogo, keyword de tendencia si aplica).
    Usa trend_scout solo si hay señal fuerte — evita llamadas API innecesarias.
    """
    fallback = (catalog_query or product_focus or niche or "").strip()
    if not fallback:
        fallback = "ropa deportiva mujer"

    try:
        from app.marketing.trend_scout import productos_en_tendencia

        seeds = list(dict.fromkeys([catalog_query, product_focus, niche, fallback]))
        seeds = [s.strip() for s in seeds if s and s.strip()][:5]
        report = productos_en_tendencia(keywords=seeds, limite=3, incluir_competencia=False)
        mejor = report.get("mejor_oportunidad")
        if mejor and float(mejor.get("priority_score", 0)) >= 45:
            kw = str(mejor.get("keyword", fallback))
            logger.info("[ContentAdsBridge] Trend keyword: %s (score=%s)", kw, mejor.get("priority_score"))
            return kw, kw
    except Exception as exc:
        logger.warning("[ContentAdsBridge] trend_scout omitido: %s", exc)

    return fallback, None


def resolve_producto_from_catalog(
    *,
    catalog_query: str = "",
    niche: str = "",
    product_focus: str = "",
    use_trends: bool = True,
) -> tuple[ContentAdsProduct, Optional[str], str]:
    """
    Resuelve producto desde catálogo Shein.
    Returns: (producto, trend_keyword, catalog_source)
    """
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    trend_kw: Optional[str] = None
    search = (catalog_query or product_focus or niche or "").strip()
    source = "shein_catalog"

    if use_trends:
        search, trend_kw = resolve_trend_keyword(
            catalog_query=catalog_query,
            niche=niche,
            product_focus=product_focus,
        )
        if trend_kw:
            source = "shein_catalog+trends"

    bridge = get_catalog_bridge()
    raw = bridge.get_top_seller(search)
    logger.info(
        "[ContentAdsBridge] Catálogo query='%s' → %s",
        search or "(auto)",
        raw.get("titulo"),
    )
    return catalog_dict_to_content_ads(raw), trend_kw, source


def producto_from_schema(payload: ContentAdsProduct, script: GeneratedScript) -> dict[str, Any]:
    return {
        "titulo": payload.titulo,
        "imagen_url": payload.imagen_url,
        "producto_url": payload.producto_url,
        "precio_cop": payload.precio_cop,
        "precio_reventa": payload.precio_cop,
        "keyword": payload.keyword or script.niche,
        "producto_id": payload.producto_id or f"outlier-{script.outlier_id[:8]}",
        "nombre_campana": payload.nombre_campana or f"EDNET Outlier — {payload.titulo[:40]}",
        "creative_format": payload.creative_format,
    }


async def launch_ads_from_script(
    script: GeneratedScript,
    producto: ContentAdsProduct,
    *,
    skip_meta_create: bool = False,
    daily_budget_cop: Optional[float] = None,
) -> dict[str, Any]:
    """Lanza campaña Meta PAUSED reutilizando el guion ya generado."""
    from app.marketing.campaign_builder import armar_campana

    copy = script_to_meta_copy(script)
    prod = producto_from_schema(producto, script)

    logger.info(
        "[ContentAdsBridge] Lanzando ads tenant=%s script=%s producto=%s",
        script.tenant_id,
        script.id,
        prod.get("titulo"),
    )

    return await armar_campana(
        prod,
        daily_budget_cop=daily_budget_cop,
        skip_meta_create=skip_meta_create,
        copy_override=copy,
    )


def launch_ads_from_script_sync(
    script: GeneratedScript,
    producto: ContentAdsProduct,
    **kwargs: Any,
) -> dict[str, Any]:
    """Wrapper para BackgroundTasks de FastAPI."""
    return asyncio.run(launch_ads_from_script(script, producto, **kwargs))
