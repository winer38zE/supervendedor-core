"""
app/marketing/campaign_builder.py
────────────────────────────────────────────────────────────────────────────────
Capa 2 — Generador de campaña Meta completa (creative + copy + compliance + PAUSED).

Flujo armar_campana(producto):
  1. Genera creative (imagen Nano Banana o video Veo 3.1, o imagen del catálogo).
  2. Genera copy con OpenAI (GPT-4.1 por defecto).
  3. Pasa copy + targeting por meta_compliance_guard — si falla, WhatsApp + log, STOP.
  4. Si aprueba → MetaAdsManager.crear_campana_completa() en PAUSED.
  5. Devuelve campaign_id y metadatos.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal, Optional

import httpx

from app.config import settings
from app.marketing.meta_api import MetaAdsManager, _default_targeting_colombia
from app.marketing.meta_compliance_guard import revisar_paquete_anuncio
from app.services.whatsapp_sender import send_whatsapp_text

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
META_CAMPAIGN_COPY_MODEL = os.environ.get("META_CAMPAIGN_COPY_MODEL", "gpt-4.1")
META_CREATIVE_FORMAT = os.environ.get("META_CREATIVE_FORMAT", "image").lower()  # image | video
META_USE_CATALOG_IMAGE = os.environ.get("META_USE_CATALOG_IMAGE", "true").lower() == "true"
META_IMAGE_TIER = os.environ.get("META_IMAGE_TIER", "fast")  # fast | pro
META_IMAGE_ASPECT = os.environ.get("META_IMAGE_ASPECT", "1:1")
META_DAILY_BUDGET_COP = float(os.environ.get("META_DEFAULT_DAILY_BUDGET", "30000"))
ADS_NOTIFY_WHATSAPP = os.environ.get("ADS_NOTIFY_WHATSAPP", os.environ.get("OWNER_WHATSAPP", ""))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
IMAGE_MODELS = {
    "fast": "gemini-2.5-flash-image",
    "pro": "gemini-3-pro-image-preview",
}
VEO_MODEL = os.environ.get("META_VEO_MODEL", "veo-3.1-generate-preview")

_CREATIVE_DIR = Path(os.environ.get("META_CREATIVE_DIR", "app/storage_vault/meta_ads/creatives"))
_CREATIVE_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# PROMPT COPY — editable
# ══════════════════════════════════════════════════════════════════════════════

COPY_GENERATION_SYSTEM = """\
Sos copywriter senior de Meta Ads para ED NET PRO (ropa deportiva/urbana, Colombia).

REGLAS DE MARCA:
- Tono: directo, colombiano, cercano, sin vulgaridades.
- Modelo: catálogo estilo tendencias, pago contra entrega en Cúcuta, envío nacional.
- NO uses: "Shein oficial", garantías de salud, antes/después, "¿estás gord@?".
- NO escasez falsa ("solo quedan 2") salvo que el contexto indique stock real.
- Superlativos moderados ("tendencia del momento" OK; "el mejor del mundo" evitar).

Respondé SOLO JSON válido:
{
  "titulo": "headline max 40 chars",
  "texto_principal": "primary text 1-3 frases con emoji moderado",
  "descripcion": "description opcional corta",
  "cta": "WHATSAPP_MESSAGE | SHOP_NOW | LEARN_MORE",
  "contexto_producto": "1 línea para compliance"
}
"""

COPY_GENERATION_USER = """\
Producto:
- Nombre: {titulo}
- Precio: ${precio:,.0f} COP
- URL catálogo: {url}
- Keyword tendencia: {keyword}

Generá copy para anuncio Meta Ads Colombia — mujer 18-45, interés moda deportiva.
Incluí precio solo si suma conversión; mencioná pago contra entrega si aplica.
"""


# ══════════════════════════════════════════════════════════════════════════════
# Creative — Gemini (Nano Banana / Veo)
# ══════════════════════════════════════════════════════════════════════════════

def _gemini_headers() -> dict[str, str]:
    return {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}


async def _generar_imagen_nano_banana(
    prompt: str,
    *,
    tier: str = "fast",
    aspect_ratio: str = "1:1",
    reference_b64: list[str] | None = None,
) -> bytes:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no configurada — no se puede generar imagen")

    model = IMAGE_MODELS.get(tier, IMAGE_MODELS["fast"])
    parts: list[dict] = [{"text": prompt}]
    if reference_b64:
        for b64 in reference_b64:
            parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{GEMINI_BASE}/models/{model}:generateContent",
            headers=_gemini_headers(),
            json=payload,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini image error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    parts_out = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for p in parts_out:
        if "inlineData" in p:
            return base64.b64decode(p["inlineData"]["data"])
    raise RuntimeError("Gemini no devolvió imagen inlineData")


async def _generar_video_veo(prompt: str, *, resolution: str = "720p") -> str:
    """Devuelve URI del video generado (descarga manual pendiente para Meta upload)."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no configurada")

    payload = {"instances": [{"prompt": prompt}], "parameters": {"resolution": resolution}}

    async with httpx.AsyncClient(timeout=120) as client:
        create = await client.post(
            f"{GEMINI_BASE}/models/{VEO_MODEL}:predictLongRunning",
            headers=_gemini_headers(),
            json=payload,
        )
    if create.status_code != 200:
        raise RuntimeError(f"Veo create error: {create.text[:300]}")

    operation_name = create.json().get("name")
    if not operation_name:
        raise RuntimeError("Veo no devolvió operation name")

    waited = 0
    max_wait = int(os.environ.get("META_VEO_MAX_WAIT", "300"))
    interval = 10
    async with httpx.AsyncClient(timeout=60) as client:
        while waited < max_wait:
            poll = await client.get(f"{GEMINI_BASE}/{operation_name}", headers=_gemini_headers())
            if poll.status_code != 200:
                raise RuntimeError(f"Veo poll error: {poll.text[:200]}")
            data = poll.json()
            if data.get("done"):
                samples = data.get("response", {}).get("generateVideoResponse", {}).get("generatedSamples", [])
                if samples:
                    return samples[0]["video"]["uri"]
                raise RuntimeError(f"Veo respuesta inesperada: {data}")
            await asyncio.sleep(interval)
            waited += interval
    raise TimeoutError("Timeout generando video Veo")


async def _descargar_imagen_url(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name.lower())
    return re.sub(r"[\s_]+", "-", s).strip("-")[:60] or "producto"


def _creative_prompt(producto: dict[str, Any]) -> str:
    titulo = producto.get("titulo") or producto.get("keyword") or "Ropa deportiva"
    return (
        f"Foto publicitaria profesional para Meta Ads, producto: {titulo}. "
        "Modelo colombiana usando la prenda, fondo limpio, iluminación de estudio, "
        "estilo ecommerce moda deportiva, sin texto overlay, alta calidad, 1:1."
    )


async def generar_creative(producto: dict[str, Any]) -> dict[str, Any]:
    """
    Genera o reutiliza creative del producto.

    Returns:
        {format, path, video_uri?, source: catalog|generated|existing}
    """
    titulo = producto.get("titulo") or "producto"
    slug = _slug(titulo)
    imagen_url = (producto.get("imagen_url") or producto.get("producto_url") or "").strip()
    existing = producto.get("creative_path")

    if existing and Path(existing).is_file():
        return {"format": "image", "path": str(existing), "source": "existing"}

    fmt = (producto.get("creative_format") or META_CREATIVE_FORMAT).lower()

    if fmt == "video":
        video_uri = await _generar_video_veo(_creative_prompt(producto))
        # Meta requiere video_id subido — por ahora guardamos URI; campaign usa imagen fallback si no hay upload
        logger.warning("[CampaignBuilder] Video generado pero Meta video upload no automatizado — usar imagen")
        # Fallback a imagen para no bloquear pipeline
        fmt = "image"

    if META_USE_CATALOG_IMAGE and imagen_url and imagen_url.startswith("http"):
        try:
            raw = await _descargar_imagen_url(imagen_url)
            path = _CREATIVE_DIR / f"{slug}-catalog-{int(time.time())}.jpg"
            path.write_bytes(raw)
            return {"format": "image", "path": str(path.resolve()), "source": "catalog"}
        except Exception as e:
            logger.warning("[CampaignBuilder] No se pudo usar imagen catálogo: %s", e)

    reference_b64: list[str] | None = None
    if imagen_url.startswith("http"):
        try:
            raw = await _descargar_imagen_url(imagen_url)
            reference_b64 = [base64.b64encode(raw).decode()]
        except Exception:
            pass

    png_bytes = await _generar_imagen_nano_banana(
        _creative_prompt(producto),
        tier=META_IMAGE_TIER,
        aspect_ratio=META_IMAGE_ASPECT,
        reference_b64=reference_b64,
    )
    path = _CREATIVE_DIR / f"{slug}-gen-{int(time.time())}.png"
    path.write_bytes(png_bytes)
    return {"format": "image", "path": str(path.resolve()), "source": "generated"}


# ══════════════════════════════════════════════════════════════════════════════
# Copy — OpenAI
# ══════════════════════════════════════════════════════════════════════════════

def generar_copy_producto(producto: dict[str, Any]) -> dict[str, str]:
    """Genera titulo, texto_principal, descripcion, cta con OpenAI."""
    titulo = producto.get("titulo") or producto.get("keyword") or "Producto destacado"
    precio = float(producto.get("precio_reventa") or producto.get("precio_cop") or 0)
    url = producto.get("producto_url") or producto.get("url") or ""
    keyword = producto.get("keyword") or titulo

    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        logger.warning("[CampaignBuilder] Sin OPENAI — copy plantilla")
        return _copy_plantilla(titulo, precio)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        user_msg = COPY_GENERATION_USER.format(
            titulo=titulo, precio=precio, url=url or "N/A", keyword=keyword,
        )
        resp = client.chat.completions.create(
            model=META_CAMPAIGN_COPY_MODEL,
            temperature=0.7,
            max_tokens=600,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": COPY_GENERATION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return {
            "titulo": str(data.get("titulo", titulo))[:40],
            "texto_principal": str(data.get("texto_principal", "")),
            "descripcion": str(data.get("descripcion", "")),
            "cta": str(data.get("cta", "WHATSAPP_MESSAGE")),
            "contexto_producto": str(data.get("contexto_producto", titulo)),
        }
    except Exception as e:
        logger.error("[CampaignBuilder] OpenAI copy error: %s", e)
        return _copy_plantilla(titulo, precio)


def _copy_plantilla(titulo: str, precio: float) -> dict[str, str]:
    precio_txt = f"${precio:,.0f} COP — " if precio > 0 else ""
    return {
        "titulo": titulo[:40],
        "texto_principal": (
            f"🔥 {titulo}\n{precio_txt}Pago contra entrega en Cúcuta. "
            "Escríbenos por WhatsApp y te apartamos tu talla."
        ),
        "descripcion": "Envío nacional | Catálogo directo",
        "cta": "WHATSAPP_MESSAGE",
        "contexto_producto": f"Ropa deportiva — {titulo}",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Notificaciones
# ══════════════════════════════════════════════════════════════════════════════

def _notificar_whatsapp(mensaje: str) -> bool:
    phone = (ADS_NOTIFY_WHATSAPP or "").strip()
    if not phone:
        logger.warning("[CampaignBuilder] ADS_NOTIFY_WHATSAPP vacío — notificación solo en log")
        logger.info("[CampaignBuilder] %s", mensaje)
        return False
    return send_whatsapp_text(phone, mensaje)


def _notificar_bloqueo_compliance(producto: dict[str, Any], compliance: dict[str, Any]) -> None:
    nombre = producto.get("titulo") or producto.get("keyword") or "Producto"
    msg = (
        f"⚠️ *Ads bloqueado — Compliance Meta*\n\n"
        f"Producto: {nombre}\n"
        f"Motivo: {compliance.get('motivo', 'Revisión manual')}\n"
        f"Severidad: {compliance.get('severidad', 'bloqueo')}\n\n"
        f"Revisá en compliance_log y ajustá el copy antes de relanzar."
    )
    sugerencias = compliance.get("sugerencias") or []
    if sugerencias:
        msg += "\n\nSugerencias:\n" + "\n".join(f"• {s}" for s in sugerencias[:3])
    _notificar_whatsapp(msg)


def _notificar_campana_lista(nombre: str, campaign_id: str, copy: dict[str, str]) -> None:
    msg = (
        f"🆕 *Nueva campaña lista (PAUSED)*\n\n"
        f"Nombre: {nombre}\n"
        f"ID: {campaign_id}\n"
        f"Título: {copy.get('titulo', '')}\n\n"
        f"Activala en Meta Ads Manager cuando apruebes el creative."
    )
    _notificar_whatsapp(msg)


# ══════════════════════════════════════════════════════════════════════════════
# Orquestación principal
# ══════════════════════════════════════════════════════════════════════════════

async def armar_campana(
    producto: dict[str, Any],
    *,
    daily_budget_cop: float | None = None,
    targeting: dict[str, Any] | None = None,
    skip_meta_create: bool = False,
    copy_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pipeline completo Capa 2.

    producto keys útiles:
      titulo, precio_cop, precio_reventa, imagen_url, producto_url, keyword,
      producto_id, creative_format (image|video), creative_path

    Returns:
        {
          ok: bool,
          campaign_id: str | None,
          blocked_by_compliance: bool,
          compliance: dict,
          copy: dict,
          creative: dict,
          meta: dict | None,
          error: str | None,
        }
    """
    titulo = producto.get("titulo") or producto.get("keyword") or "Campaña ED NET PRO"
    producto_id = str(producto.get("producto_id") or producto.get("id") or _slug(titulo))
    nombre_campana = producto.get("nombre_campana") or f"EDNET — {titulo[:50]}"

    resultado: dict[str, Any] = {
        "ok": False,
        "campaign_id": None,
        "blocked_by_compliance": False,
        "compliance": {},
        "copy": {},
        "creative": {},
        "meta": None,
        "error": None,
    }

    try:
        # 1) Creative
        logger.info("[CampaignBuilder] Generando creative para '%s'", titulo)
        creative = await generar_creative(producto)
        resultado["creative"] = creative

        # 2) Copy — reutilizar guion outlier si viene pre-generado (evita 2.ª llamada LLM)
        if copy_override:
            logger.info("[CampaignBuilder] Usando copy pre-generado (content outlier)")
            copy = {
                "titulo": str(copy_override.get("titulo", titulo))[:40],
                "texto_principal": str(copy_override.get("texto_principal", "")),
                "descripcion": str(copy_override.get("descripcion", "")),
                "cta": str(copy_override.get("cta", "WHATSAPP_MESSAGE")),
                "contexto_producto": str(copy_override.get("contexto_producto", titulo)),
            }
        else:
            logger.info("[CampaignBuilder] Generando copy")
            copy = generar_copy_producto(producto)
        resultado["copy"] = copy

        # 3) Compliance — STOP si no aprueba
        tgt = targeting or _default_targeting_colombia()
        compliance = revisar_paquete_anuncio(
            copy={
                "titulo": copy["titulo"],
                "texto_principal": copy["texto_principal"],
                "descripcion": copy.get("descripcion", ""),
                "cta": copy.get("cta", ""),
                "contexto_producto": copy.get("contexto_producto", titulo),
            },
            adset_params={"targeting": tgt, "special_ad_categories": []},
            producto_id=producto_id,
            producto_nombre=titulo,
        )
        resultado["compliance"] = compliance

        if not compliance.get("aprobado"):
            resultado["blocked_by_compliance"] = True
            resultado["error"] = compliance.get("motivo", "Bloqueado por compliance")
            logger.error("[CampaignBuilder] Compliance RECHAZADO: %s", resultado["error"])
            _notificar_bloqueo_compliance(producto, compliance)
            return resultado

        if compliance.get("severidad") == "advertencia":
            logger.warning("[CampaignBuilder] Compliance con advertencias — continúa en PAUSED")

        if skip_meta_create:
            resultado["ok"] = True
            resultado["error"] = "skip_meta_create=true — no se creó en Meta"
            return resultado

        # 4) Crear en Meta — PAUSED
        logger.info("[CampaignBuilder] Creando campaña PAUSED en Meta")
        meta = MetaAdsManager()
        meta_result = meta.crear_campana_completa(
            nombre=nombre_campana,
            copy=copy,
            creative_path=creative.get("path"),
            daily_budget_cop=daily_budget_cop or META_DAILY_BUDGET_COP,
            targeting=tgt,
            status="PAUSED",
        )
        resultado["meta"] = meta_result
        resultado["campaign_id"] = meta_result.get("campaign_id")
        resultado["ok"] = bool(resultado["campaign_id"])

        if resultado["ok"]:
            _notificar_campana_lista(nombre_campana, resultado["campaign_id"], copy)
        else:
            resultado["error"] = "Meta no devolvió campaign_id"

    except Exception as e:
        logger.exception("[CampaignBuilder] Error armar_campana")
        resultado["error"] = str(e)
        _notificar_whatsapp(f"❌ *Error creando campaña*\n{titulo}\n{e}")

    return resultado


def armar_campana_sync(producto: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Wrapper síncrono para scripts / n8n vía subprocess."""
    return asyncio.run(armar_campana(producto, **kwargs))
