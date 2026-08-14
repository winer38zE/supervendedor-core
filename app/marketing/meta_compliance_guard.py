"""
app/marketing/meta_compliance_guard.py
────────────────────────────────────────────────────────────────────────────────
Capa 3 — Guardia de cumplimiento de políticas Meta Ads (ED NET PRO).

Revisa copy y segmentación ANTES de crear/publicar campañas.
Registra cada revisión en PocketBase (`compliance_log`) + fallback JSON local.

Colección PocketBase sugerida `compliance_log`:
  - producto_id (Text)
  - producto_nombre (Text)
  - tipo_revision (Text)        → copy | targeting | paquete
  - aprobado (Bool)
  - severidad (Text)            → ok | advertencia | bloqueo
  - motivo (Text)
  - detalles (JSON)
  - copy_snapshot (Text)        → opcional
  - targeting_snapshot (JSON)   → opcional
  - fuente (Text)               → llm | heuristica | mixto
  - created_at (Date)           → auto
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from app.config import settings

logger = logging.getLogger(__name__)

Severidad = Literal["ok", "advertencia", "bloqueo"]
FuenteRevision = Literal["llm", "heuristica", "mixto"]

# Modelo LLM — ajustable en .env (ej. gpt-4.1, gpt-4o)
META_COMPLIANCE_MODEL = os.environ.get("META_COMPLIANCE_MODEL", "gpt-4.1")

_LOCAL_LOG_DIR = Path(
    os.environ.get(
        "COMPLIANCE_LOG_DIR",
        Path(__file__).parent / "logs",
    )
)
_LOCAL_LOG_FILE = _LOCAL_LOG_DIR / "compliance_log.jsonl"

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS EDITABLES — ajustá el tono de marca acá antes de producción
# ══════════════════════════════════════════════════════════════════════════════

COPY_REVIEW_SYSTEM_PROMPT = """\
Sos un revisor senior de políticas publicitarias de Meta (Facebook/Instagram Ads).
Tu trabajo es proteger la cuenta del anunciante de rechazos, bloqueos y baneos.

CONTEXTO DEL NEGOCIO:
- Marca: ED NET PRO / Super Vendedor — ropa deportiva y urbana estilo Shein.
- Mercado: Colombia (Cúcuta y envío nacional).
- Modelo: pago contra entrega, catálogo de reventa, NO somos clínica ni servicio financiero.
- Tono deseado de la marca: directo, colombiano, persuasivo, pero SIEMPRE dentro de políticas Meta.

POLÍTICAS A EVALUAR (prioridad alta = bloqueo):

1) AFIRMACIONES DE SALUD O RESULTADOS GARANTIZADOS
   Bloqueá si promete curar, eliminar, adelgazar X kg, resultados médicos garantizados,
   "100% garantizado" en contexto de salud/cuerpo, o eficacia milagrosa.

2) ATRIBUTOS PERSONALES (Personal Attributes Policy)
   Bloqueá si el texto habla DIRECTAMENTE al usuario sobre:
   - raza, etnia, religión, orientación sexual, identidad de género
   - condición de salud, discapacidad, situación financiera/deudas
   - edad, estado civil, nombre, apellido de forma acusatoria
   Ejemplos PROHIBIDOS: "¿Estás gord@?", "¿Tienes deudas?", "Si sos pobre...", "Para mujeres fea..."
   Permitido: beneficios genéricos del producto sin señalar características del lector.

3) ANTES Y DESPUÉS ENGAÑOSO
   Bloqueá comparaciones visuales/textuales de transformación corporal no realistas
   o implicaciones de pérdida de peso garantizada.

4) PRECIOS ENGAÑOSOS Y ESCASEZ FALSA
   Bloqueá "solo quedan 2", "últimas unidades" u ofertas urgentes si no hay evidencia
   de stock real (riesgo legal Colombia + Meta). "Oferta de hoy" es advertencia, no bloqueo duro,
   salvo que sea claramente falsa.

5) SUPERLATIVOS SIN SUSTENTO
   "El mejor", "único en el mundo", "#1" → ADVERTENCIA (no bloqueo) salvo que implique
   certificación médica o comparación falsa verificable.

6) CONTENIDO PROHIBIDO GENERAL
   Bloqueá: odio, violencia, adulto explícito, armas, drogas, discriminación,
   suplantación de marcas (Shein oficial si no lo somos — usar "estilo Shein" con cuidado).

7) WHATSAPP / DESTINO
   Advertencia si el CTA induce a prácticas de spam o promete respuesta instantánea imposible.

INSTRUCCIONES DE RESPUESTA:
- Respondé ÚNICAMENTE con JSON válido, sin markdown, sin texto extra.
- Schema exacto:
{
  "aprobado": true|false,
  "severidad": "ok"|"advertencia"|"bloqueo",
  "motivo": "resumen en 1-2 frases en español",
  "violaciones": [
    {"codigo": "CODIGO_CORTO", "descripcion": "...", "severidad": "bloqueo"|"advertencia"}
  ],
  "sugerencias": ["cómo reformular sin perder conversión"]
}

REGLAS DE DECISIÓN:
- aprobado=false SI existe al menos una violación con severidad "bloqueo".
- aprobado=true con severidad "advertencia" si solo hay riesgos menores reformulables.
- aprobado=true y severidad "ok" si el copy es seguro para Meta en ropa/catálogo Colombia.
"""

COPY_REVIEW_USER_TEMPLATE = """\
Revisá el siguiente copy publicitario para Meta Ads.

TÍTULO (headline):
{titulo}

TEXTO PRINCIPAL (primary text):
{texto_principal}

DESCRIPCIÓN (description):
{descripcion}

CTA (call to action):
{cta}

NOTAS DE CONTEXTO DEL PRODUCTO:
{contexto_producto}

Devolvé el JSON de evaluación según las instrucciones del system prompt.
"""

TARGETING_REVIEW_SYSTEM_PROMPT = """\
Sos un auditor de segmentación para Meta Ads.

Evaluá si los parámetros de Ad Set violan políticas de categorías especiales o segmentación restringida.

CATEGORÍAS ESPECIALES DE META (requieren declaración y certificación):
- HOUSING (vivienda)
- EMPLOYMENT (empleo)
- CREDIT (crédito/finanzas)
- ISSUES_ELECTIONS_POLITICS (política)

Para campañas de ROPA / ECOMMERCE en Colombia:
- NO deben usar special_ad_categories de vivienda, empleo o crédito.
- Segmentación por edad/género/ubicación está permitida para moda.
- Bloqueá si targeting incluye intereses claramente de salud/clínica, préstamos, deudas,
  o audiencias personalizadas basadas en condiciones de salud/finanzas para vender ropa.

Respondé SOLO JSON:
{
  "aprobado": true|false,
  "severidad": "ok"|"advertencia"|"bloqueo",
  "motivo": "...",
  "violaciones": [{"codigo": "...", "descripcion": "...", "severidad": "..."}],
  "sugerencias": []
}
"""

TARGETING_REVIEW_USER_TEMPLATE = """\
Objetivo de campaña: {objetivo}
Vertical del negocio: ropa deportiva / urbana — reventa catálogo Colombia

Parámetros de Ad Set (JSON):
{adset_json}

Evaluá compliance de segmentación.
"""

# ══════════════════════════════════════════════════════════════════════════════
# Heurísticas locales (fallback si LLM cae o refuerzo rápido)
# ══════════════════════════════════════════════════════════════════════════════

_BLOQUEO_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(cura|curar|elimina|eliminar)\b.{0,30}\b(celulitis|grasa|arrugas|acné|diabetes|cáncer)\b", "SALUD_GARANTIZADA", "Afirmación de salud/resultado médico"),
    (r"\b(100\s*%|cien por ciento)\s*(garantizad[oa]|efectivo|funciona)\b", "GARANTIA_ABSOLUTA", "Garantía absoluta de resultado"),
    (r"\b(adelgaza|baja de peso|pierde \d+\s*kg)\b", "TRANSFORMACION_CORPORAL", "Promesa de transformación corporal"),
    (r"\b(antes y después|antes/después)\b", "ANTES_DESPUES", "Formato antes/después de alto riesgo"),
    (r"¿\s*(estás|eres|tenés|tienes|sos)\s+(gord[oa@]|obes[oa]|fe[oa]|pobre|endeudad[oa]|en deuda)\??", "PERSONAL_ATTRIBUTES", "Atributo personal directo al lector"),
    (r"\b(si estás en deuda|si tienes deudas|personas gordas|gente fea)\b", "PERSONAL_ATTRIBUTES", "Segmentación/discriminación por atributo personal"),
    (r"\b(solo quedan|últim[oa]s?\s+\d+\s+unidades?|quedan \d+)\b", "ESCASEZ_FALSA", "Escasez urgente — verificar stock real"),
    (r"\b(shein oficial|tienda oficial shein)\b", "SUPLANTACION_MARCA", "Posible suplantación de marca"),
]

_ADVERTENCIA_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(el mejor|la mejor|único|unico|#1|numero 1|número 1)\b", "SUPERLATIVO", "Superlativo sin sustento — considerar suavizar"),
    (r"\b(oferta de hoy|solo hoy|última oportunidad)\b", "URGENCIA", "Urgencia comercial — asegurar veracidad"),
    (r"\b(garantía|garantizado)\b", "GARANTIA_COMERCIAL", "Revisar que no implique resultado de salud"),
    (r"\bestilo shein\b", "MARCA_COMPARATIVA", "Comparación con Shein — usar 'inspirado en tendencias' si hay dudas"),
]

_SPECIAL_AD_CATEGORIES = frozenset({
    "HOUSING", "EMPLOYMENT", "CREDIT", "ISSUES_ELECTIONS_POLITICS",
    "FINANCIAL_PRODUCTS_SERVICES",
})

_RESTRICTED_TARGETING_KEYWORDS = (
    "deuda", "crédito", "credito", "préstamo", "prestamo", "hipoteca",
    "empleo", "vacante", "salario", "obesidad", "diabetes", "cáncer", "cancer",
    "depresión", "depresion", "discapacidad",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _heuristic_scan(texto: str) -> dict[str, Any]:
    """Escaneo regex rápido — devuelve violaciones detectadas."""
    t = texto.lower()
    violaciones: list[dict[str, str]] = []

    for pattern, codigo, desc in _BLOQUEO_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            violaciones.append({"codigo": codigo, "descripcion": desc, "severidad": "bloqueo"})

    for pattern, codigo, desc in _ADVERTENCIA_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            violaciones.append({"codigo": codigo, "descripcion": desc, "severidad": "advertencia"})

    tiene_bloqueo = any(v["severidad"] == "bloqueo" for v in violaciones)
    tiene_advertencia = any(v["severidad"] == "advertencia" for v in violaciones)

    if tiene_bloqueo:
        severidad: Severidad = "bloqueo"
        aprobado = False
        motivo = "Copy bloqueado por reglas heurísticas de políticas Meta."
    elif tiene_advertencia:
        severidad = "advertencia"
        aprobado = True
        motivo = "Copy permitido con advertencias — revisar sugerencias antes de publicar."
    else:
        severidad = "ok"
        aprobado = True
        motivo = "Sin señales de riesgo en heurísticas locales."

    return {
        "aprobado": aprobado,
        "motivo": motivo,
        "severidad": severidad,
        "violaciones": violaciones,
        "sugerencias": [],
        "fuente": "heuristica",
    }


def _parse_llm_json(raw: str) -> Optional[dict[str, Any]]:
    text = (raw or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _call_openai_compliance(system_prompt: str, user_prompt: str) -> Optional[dict[str, Any]]:
    api_key = (settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        logger.warning("[Compliance] OPENAI_API_KEY vacía — solo heurísticas")
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=META_COMPLIANCE_MODEL,
            temperature=0.0,
            max_tokens=1200,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_llm_json(raw)
        if not parsed:
            logger.error(f"[Compliance] LLM JSON inválido: {raw[:300]}")
            return None
        return parsed
    except Exception as e:
        logger.error(f"[Compliance] Error LLM ({META_COMPLIANCE_MODEL}): {e}")
        return None


def _merge_results(heuristic: dict[str, Any], llm: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not llm:
        return heuristic

    violaciones = list(heuristic.get("violaciones") or [])
    for v in llm.get("violaciones") or []:
        if isinstance(v, dict) and v not in violaciones:
            violaciones.append(v)

    llm_sev = str(llm.get("severidad", "ok")).lower()
    llm_aprobado = bool(llm.get("aprobado", True))

    if any(v.get("severidad") == "bloqueo" for v in violaciones):
        severidad: Severidad = "bloqueo"
        aprobado = False
    elif llm_sev == "bloqueo" or not llm_aprobado:
        severidad = "bloqueo"
        aprobado = False
    elif llm_sev == "advertencia" or any(v.get("severidad") == "advertencia" for v in violaciones):
        severidad = "advertencia"
        aprobado = True
    else:
        severidad = "ok"
        aprobado = True

    motivo = str(llm.get("motivo") or heuristic.get("motivo") or "Revisión completada")
    sugerencias = list(llm.get("sugerencias") or [])

    return {
        "aprobado": aprobado,
        "motivo": motivo,
        "severidad": severidad,
        "violaciones": violaciones,
        "sugerencias": sugerencias,
        "fuente": "mixto" if violaciones else "llm",
    }


def registrar_compliance_log(
    *,
    producto_id: str = "",
    producto_nombre: str = "",
    tipo_revision: str,
    resultado: dict[str, Any],
    copy_snapshot: str = "",
    targeting_snapshot: Optional[dict[str, Any]] = None,
) -> None:
    """Persiste auditoría en PocketBase + JSONL local."""
    entry = {
        "producto_id": producto_id or "sin_id",
        "producto_nombre": producto_nombre or "",
        "tipo_revision": tipo_revision,
        "aprobado": bool(resultado.get("aprobado")),
        "severidad": resultado.get("severidad", "ok"),
        "motivo": resultado.get("motivo", ""),
        "detalles": {
            "violaciones": resultado.get("violaciones", []),
            "sugerencias": resultado.get("sugerencias", []),
            "fuente": resultado.get("fuente", ""),
        },
        "copy_snapshot": copy_snapshot[:4000] if copy_snapshot else "",
        "targeting_snapshot": targeting_snapshot or {},
        "fuente": resultado.get("fuente", ""),
        "created_at": _now_iso(),
    }

    try:
        from app.database.pocketbase_client import create_record

        create_record("compliance_log", entry)
    except Exception as e:
        logger.debug(f"[Compliance] PocketBase opcional: {e}")

    try:
        _LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCAL_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"[Compliance] No se pudo escribir log local: {e}")


def revisar_copy(
    texto: str,
    *,
    titulo: str = "",
    descripcion: str = "",
    cta: str = "",
    contexto_producto: str = "",
    producto_id: str = "",
    producto_nombre: str = "",
    persistir_log: bool = True,
) -> dict[str, Any]:
    """
    Revisa copy publicitario contra políticas Meta.

    Returns:
        {"aprobado": bool, "motivo": str, "severidad": "ok"|"advertencia"|"bloqueo",
         "violaciones": [...], "sugerencias": [...], "fuente": str}
    """
    texto_principal = _normalize_text(texto)
    if not texto_principal and not titulo.strip():
        resultado = {
            "aprobado": False,
            "motivo": "Copy vacío — no se puede publicar sin texto.",
            "severidad": "bloqueo",
            "violaciones": [{"codigo": "COPY_VACIO", "descripcion": "Sin contenido", "severidad": "bloqueo"}],
            "sugerencias": ["Agregá título y texto principal del anuncio."],
            "fuente": "heuristica",
        }
        if persistir_log:
            registrar_compliance_log(
                producto_id=producto_id,
                producto_nombre=producto_nombre,
                tipo_revision="copy",
                resultado=resultado,
                copy_snapshot="",
            )
        return resultado

    full_text = " ".join(filter(None, [titulo, texto_principal, descripcion, cta]))
    heuristic = _heuristic_scan(full_text)

    user_prompt = COPY_REVIEW_USER_TEMPLATE.format(
        titulo=titulo or "(sin título)",
        texto_principal=texto_principal,
        descripcion=descripcion or "(sin descripción)",
        cta=cta or "(sin CTA)",
        contexto_producto=contexto_producto or "Catálogo ropa deportiva/urbana — Colombia — pago contra entrega",
    )
    llm = _call_openai_compliance(COPY_REVIEW_SYSTEM_PROMPT, user_prompt)
    resultado = _merge_results(heuristic, llm)

    if persistir_log:
        registrar_compliance_log(
            producto_id=producto_id,
            producto_nombre=producto_nombre,
            tipo_revision="copy",
            resultado=resultado,
            copy_snapshot=full_text[:4000],
        )

    logger.info(
        f"[Compliance] copy producto='{producto_nombre or producto_id}' "
        f"aprobado={resultado['aprobado']} severidad={resultado['severidad']}"
    )
    return resultado


def revisar_targeting(
    adset_params: dict[str, Any],
    *,
    objetivo_campana: str = "OUTCOME_SALES",
    producto_id: str = "",
    producto_nombre: str = "",
    persistir_log: bool = True,
) -> dict[str, Any]:
    """
    Valida segmentación de Ad Set — categorías especiales y keywords restringidos.

    Returns mismo schema que revisar_copy.
    """
    violaciones: list[dict[str, str]] = []
    params = adset_params or {}

    special = params.get("special_ad_categories") or params.get("special_ad_category") or []
    if isinstance(special, str):
        special = [special]

    for cat in special:
        cat_up = str(cat).upper()
        if cat_up in _SPECIAL_AD_CATEGORIES:
            violaciones.append({
                "codigo": "SPECIAL_AD_CATEGORY",
                "descripcion": f"Categoría especial '{cat_up}' no corresponde a campaña de ropa.",
                "severidad": "bloqueo",
            })

    blob = json.dumps(params, ensure_ascii=False).lower()
    for kw in _RESTRICTED_TARGETING_KEYWORDS:
        if kw in blob:
            violaciones.append({
                "codigo": "TARGETING_RESTRINGIDO",
                "descripcion": f"Parámetro contiene keyword restringido: '{kw}'",
                "severidad": "bloqueo",
            })

    geo = params.get("geo_locations") or params.get("targeting", {}).get("geo_locations") or {}
    if geo and not (geo.get("countries") or geo.get("cities") or geo.get("regions")):
        violaciones.append({
            "codigo": "GEO_VACIA",
            "descripcion": "Segmentación geográfica vacía o inválida.",
            "severidad": "advertencia",
        })

    heuristic: dict[str, Any]
    if any(v["severidad"] == "bloqueo" for v in violaciones):
        heuristic = {
            "aprobado": False,
            "motivo": "Segmentación bloqueada por categorías especiales o keywords restringidos.",
            "severidad": "bloqueo",
            "violaciones": violaciones,
            "sugerencias": ["Usá segmentación demográfica/geo para moda sin categorías especiales."],
            "fuente": "heuristica",
        }
    elif violaciones:
        heuristic = {
            "aprobado": True,
            "motivo": "Segmentación con advertencias menores.",
            "severidad": "advertencia",
            "violaciones": violaciones,
            "sugerencias": [],
            "fuente": "heuristica",
        }
    else:
        heuristic = {
            "aprobado": True,
            "motivo": "Segmentación compatible con ecommerce de moda.",
            "severidad": "ok",
            "violaciones": [],
            "sugerencias": [],
            "fuente": "heuristica",
        }

    user_prompt = TARGETING_REVIEW_USER_TEMPLATE.format(
        objetivo=objetivo_campana,
        adset_json=json.dumps(params, ensure_ascii=False, indent=2),
    )
    llm = _call_openai_compliance(TARGETING_REVIEW_SYSTEM_PROMPT, user_prompt)
    resultado = _merge_results(heuristic, llm)

    if persistir_log:
        registrar_compliance_log(
            producto_id=producto_id,
            producto_nombre=producto_nombre,
            tipo_revision="targeting",
            resultado=resultado,
            targeting_snapshot=params,
        )

    logger.info(
        f"[Compliance] targeting producto='{producto_nombre or producto_id}' "
        f"aprobado={resultado['aprobado']} severidad={resultado['severidad']}"
    )
    return resultado


def revisar_paquete_anuncio(
    *,
    copy: dict[str, str],
    adset_params: dict[str, Any],
    objetivo_campana: str = "OUTCOME_SALES",
    producto_id: str = "",
    producto_nombre: str = "",
    persistir_log: bool = True,
) -> dict[str, Any]:
    """
    Revisa copy + targeting en un solo paso (usado por campaign_builder Capa 2).

    copy keys: titulo, texto_principal, descripcion, cta, contexto_producto (opcional)
    """
    copy_result = revisar_copy(
        texto=copy.get("texto_principal", copy.get("texto", "")),
        titulo=copy.get("titulo", ""),
        descripcion=copy.get("descripcion", ""),
        cta=copy.get("cta", ""),
        contexto_producto=copy.get("contexto_producto", ""),
        producto_id=producto_id,
        producto_nombre=producto_nombre,
        persistir_log=False,
    )
    targeting_result = revisar_targeting(
        adset_params,
        objetivo_campana=objetivo_campana,
        producto_id=producto_id,
        producto_nombre=producto_nombre,
        persistir_log=False,
    )

    aprobado = copy_result["aprobado"] and targeting_result["aprobado"]
    if not aprobado:
        severidad: Severidad = "bloqueo"
    elif copy_result["severidad"] == "advertencia" or targeting_result["severidad"] == "advertencia":
        severidad = "advertencia"
    else:
        severidad = "ok"

    motivos = []
    if not copy_result["aprobado"]:
        motivos.append(f"Copy: {copy_result['motivo']}")
    if not targeting_result["aprobado"]:
        motivos.append(f"Targeting: {targeting_result['motivo']}")

    resultado = {
        "aprobado": aprobado,
        "motivo": " | ".join(motivos) if motivos else "Paquete aprobado para creación en PAUSED.",
        "severidad": severidad,
        "copy": copy_result,
        "targeting": targeting_result,
        "violaciones": (copy_result.get("violaciones") or []) + (targeting_result.get("violaciones") or []),
        "sugerencias": (copy_result.get("sugerencias") or []) + (targeting_result.get("sugerencias") or []),
        "fuente": "mixto",
    }

    if persistir_log:
        registrar_compliance_log(
            producto_id=producto_id,
            producto_nombre=producto_nombre,
            tipo_revision="paquete",
            resultado=resultado,
            copy_snapshot=json.dumps(copy, ensure_ascii=False),
            targeting_snapshot=adset_params,
        )

    return resultado
