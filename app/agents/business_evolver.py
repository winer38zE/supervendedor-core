"""
app/agents/business_evolver.py
────────────────────────────────────────────────────────────────────────────────
Motor de Evolución Continua del Asistente de Ventas.

La función `evolve_business_logic` analiza las últimas N llamadas de un cliente
y usa Claude Sonnet para extraer tres inteligencias clave:

  1. PREGUNTAS SIN RESPUESTA  — lo que el bot no supo responder y costó ventas.
  2. PERFIL DEL COMPRADOR EXITOSO — patrones de lenguaje de quienes SÍ cerraron.
  3. MOTIVOS DE PÉRDIDA — por qué algunas llamadas fueron una pérdida de tiempo.

El resultado se guarda como JSON en clients_config.dynamic_knowledge y se inyecta
automáticamente en el system prompt de Vapi en cada nueva llamada.

Fuentes de datos (en orden de prioridad):
  A. Tabla leads_crm en Supabase (estado, lead_score, notas)
  B. Archivos feedback.txt generados por extract_missed_info (análisis por llamada)
  C. Ambas fuentes combinadas para máxima riqueza

Trigger: llamado en background desde vapi_handler.py tras cada end-of-call-report.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
MIN_LLAMADAS_PARA_EVOLUCIONAR: int = 3   # mínimo de llamadas para hacer el análisis
MAX_LLAMADAS_A_ANALIZAR:       int = 10  # ventana de análisis

_MOCK_S3_DIR = Path(__file__).parent / "mock_s3"

# ── Prompt maestro para Claude Sonnet ────────────────────────────────────────
_EVOLUTION_PROMPT = """\
Eres un analista senior de ventas y experto en optimización de bots de voz.
Tu trabajo es analizar llamadas de ventas reales y extraer inteligencia accionable.

NEGOCIO ANALIZADO: {negocio}
MODO DE VENTAS: {modo}
DATOS: {n_llamadas} llamadas | {n_cerradas} ventas cerradas | {n_perdidas} perdidas | Tasa: {tasa}%

══════════════════════════════════════════════════════
REGISTRO DE LLAMADAS:
══════════════════════════════════════════════════════
{registro_llamadas}

══════════════════════════════════════════════════════
INSTRUCCIÓN:
══════════════════════════════════════════════════════
Analiza todas las llamadas anteriores con ojos de coach experto en ventas.
Responde ÚNICAMENTE con un objeto JSON válido, sin markdown, sin texto extra.
Usa exactamente esta estructura:

{{
  "version": {version_nueva},
  "updated_at": "{timestamp}",
  "total_analizadas": {n_llamadas},
  "cerradas": {n_cerradas},
  "perdidas": {n_perdidas},
  "tasa_conversion": "{tasa}%",

  "preguntas_sin_respuesta": [
    "Pregunta 1 que el bot no respondió bien y causó fricción o pérdida",
    "Pregunta 2...",
    "Pregunta 3..."
  ],

  "perfil_comprador_exitoso": {{
    "frases_trigger": [
      "frase que dijo un comprador exitoso y que indica intención de compra",
      "otra frase típica del que sí cerró"
    ],
    "caracteristicas": [
      "rasgo del comprador que sí cerró (ej: pregunta precio directo, menciona urgencia)",
      "otro rasgo..."
    ],
    "momento_de_cierre": "Descripción del momento exacto en que se dio el cierre exitoso"
  }},

  "motivos_perdida_tiempo": [
    "Motivo 1 por el que una llamada fue pérdida de tiempo (sin intención real, sin presupuesto, etc.)",
    "Motivo 2...",
    "Motivo 3..."
  ],

  "tecnicas_ganadoras": [
    "Técnica concreta que funcionó para cerrar ventas en estas llamadas",
    "Otra técnica..."
  ],

  "instrucciones_para_bot": "Párrafo de instrucciones DIRECTAS y ESPECÍFICAS para mejorar el bot, en español colombiano, listo para inyectar en el system prompt. Debe ser concreto, accionable y basado en los datos reales de estas llamadas. Máximo 250 palabras. Empieza con: APRENDIZAJE ACTIVO (v{version_nueva}):"
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# Función principal pública
# ══════════════════════════════════════════════════════════════════════════════

def evolve_business_logic(
    client_id: str,
    tenant_id:  Optional[str] = None,
    n_llamadas: int = MAX_LLAMADAS_A_ANALIZAR,
) -> dict:
    """
    Analiza las últimas `n_llamadas` del cliente, extrae inteligencia de ventas
    con Claude Sonnet y actualiza clients_config.dynamic_knowledge en Supabase.

    Args:
        client_id:  ID del cliente en clients_config.
        tenant_id:  ID del tenant en leads_crm (por defecto = client_id).
        n_llamadas: Cuántas llamadas recientes analizar (máx 10).

    Returns:
        {
          "evolucionado": bool,
          "motivo":       str,          # si no evolucionó
          "version":      int,          # nueva versión del knowledge
          "resumen":      str,          # resumen legible
          "knowledge":    dict,         # el JSON completo generado
        }
    """
    tenant_id = tenant_id or client_id

    # ── 1. Recolectar datos de llamadas ───────────────────────────────────────
    llamadas = _recolectar_llamadas(client_id, tenant_id, n_llamadas)

    if len(llamadas) < MIN_LLAMADAS_PARA_EVOLUCIONAR:
        logger.info(
            f"[Evolver] client='{client_id}' | solo {len(llamadas)} llamadas "
            f"(mínimo {MIN_LLAMADAS_PARA_EVOLUCIONAR}). Sin evolución."
        )
        return {
            "evolucionado": False,
            "motivo": f"Solo {len(llamadas)} llamadas disponibles (mínimo {MIN_LLAMADAS_PARA_EVOLUCIONAR})",
            "version": 0,
            "resumen": "",
            "knowledge": {},
        }

    # ── 2. Obtener config actual (para versión y contexto) ────────────────────
    config_actual = _get_client_config(client_id) or {}
    dk_actual     = config_actual.get("dynamic_knowledge") or {}
    version_nueva = (dk_actual.get("version") or 0) + 1

    # ── 3. Construir registro de llamadas para el prompt ──────────────────────
    registro, stats = _formatear_llamadas_para_prompt(llamadas)

    # ── 4. Llamar a Claude Sonnet ─────────────────────────────────────────────
    knowledge = _llamar_claude_para_analisis(
        negocio      = config_actual.get("negocio_nombre") or client_id,
        modo         = config_actual.get("modo_operacion") or "venta",
        registro     = registro,
        stats        = stats,
        version_nueva = version_nueva,
    )

    if not knowledge:
        return {
            "evolucionado": False,
            "motivo": "Claude no devolvió respuesta válida",
            "version": 0,
            "resumen": "",
            "knowledge": {},
        }

    # ── 5. Guardar en Supabase ────────────────────────────────────────────────
    guardado = _guardar_dynamic_knowledge(client_id, knowledge)

    resumen = (
        f"v{version_nueva} | {stats['n_llamadas']} llamadas | "
        f"{stats['n_cerradas']} ventas | {stats['tasa']}% conversión | "
        f"{len(knowledge.get('preguntas_sin_respuesta', []))} preguntas sin responder"
    )

    logger.info(f"[Evolver] client='{client_id}' → {resumen} | guardado={guardado}")

    return {
        "evolucionado": True,
        "motivo":       "Análisis completado con éxito",
        "version":      version_nueva,
        "resumen":      resumen,
        "knowledge":    knowledge,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Recolección de datos de llamadas
# ══════════════════════════════════════════════════════════════════════════════

def _recolectar_llamadas(client_id: str, tenant_id: str, n: int) -> list[dict]:
    """
    Combina datos de Supabase (leads_crm) y feedback.txt locales.
    Retorna lista de dicts con: resultado, score, notas, analisis_ia.
    """
    llamadas_db  = _leer_leads_supabase(tenant_id, n)
    llamadas_txt = _leer_feedback_txt(client_id, n)

    # Merge: usar Supabase como base, enriquecer con feedback.txt si hay menos
    if llamadas_db:
        # Enriquecer con análisis del feedback.txt si está disponible
        for i, l in enumerate(llamadas_db):
            if i < len(llamadas_txt):
                l["analisis_ia"] = llamadas_txt[i].get("analisis_ia", "")
        return llamadas_db[:n]

    return llamadas_txt[:n]


def _leer_leads_supabase(tenant_id: str, n: int) -> list[dict]:
    """Lee los últimos N leads de leads_crm con fuente vapi o whatsapp."""
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        return []
    try:
        from supabase import create_client
        db  = create_client(sb_url, sb_key)
        res = (
            db.table("leads_crm")
            .select("nombre, estado, lead_score, notas, metadata, created_at")
            .eq("tenant_id", tenant_id)
            .in_("fuente", ["vapi", "whatsapp", "llamada"])
            .order("created_at", desc=True)
            .limit(n)
            .execute()
        )
        return [
            {
                "resultado":   _normalizar_estado(r.get("estado", "")),
                "score":       r.get("lead_score", 0),
                "nombre":      r.get("nombre", "Desconocido"),
                "notas":       r.get("notas", ""),
                "analisis_ia": "",
                "fecha":       (r.get("created_at") or "")[:10],
            }
            for r in (res.data or [])
        ]
    except Exception as e:
        logger.warning(f"[Evolver] Supabase no disponible: {e}")
        return []


def _leer_feedback_txt(client_id: str, n: int) -> list[dict]:
    """
    Lee el feedback.txt local y parsea las entradas más recientes.
    Formato esperado: bloques separados por la línea de guiones + fecha.
    """
    path = _MOCK_S3_DIR / client_id / "feedback.txt"
    if not path.exists():
        return []

    try:
        texto = path.read_text(encoding="utf-8")
    except Exception:
        return []

    # Dividir en bloques por el separador de llamada
    bloques = re.split(r"─{40,}", texto)
    bloques = [b.strip() for b in bloques if b.strip()]

    llamadas = []
    i = 0
    while i < len(bloques) and len(llamadas) < n:
        bloque = bloques[i]
        # Buscar el header "LLAMADA: ... | RESULTADO: ..."
        header_match = re.search(
            r"LLAMADA:\s*(\S+\s+\S+)\s*\|.*?RESULTADO:\s*(\w+)",
            bloque,
            re.IGNORECASE,
        )
        if header_match:
            fecha     = header_match.group(1)
            resultado = header_match.group(2)
            # El análisis completo está en el bloque siguiente (si existe)
            analisis = bloques[i + 1] if i + 1 < len(bloques) else bloque
            llamadas.append({
                "resultado":   _normalizar_estado(resultado),
                "score":       _extraer_puntuacion(analisis),
                "nombre":      "Llamada",
                "notas":       "",
                "analisis_ia": analisis.strip()[:1500],   # máx 1500 chars por llamada
                "fecha":       fecha,
            })
            i += 2
        else:
            i += 1

    # Las más recientes primero (el txt escribe al final)
    return list(reversed(llamadas))


def _normalizar_estado(estado: str) -> str:
    estado = (estado or "").lower()
    if any(x in estado for x in ["cerr", "venta", "exito", "ok", "compro"]):
        return "CERRADA"
    if any(x in estado for x in ["perdi", "fallid", "rechaz", "no"]):
        return "PERDIDA"
    return "DESCONOCIDA"


def _extraer_puntuacion(texto: str) -> int:
    """Extrae el score numérico del análisis (busca 'N/10')."""
    m = re.search(r"(\d+)\s*/\s*10", texto)
    return int(m.group(1)) if m else 5


# ══════════════════════════════════════════════════════════════════════════════
# Formateo del registro para el prompt
# ══════════════════════════════════════════════════════════════════════════════

def _formatear_llamadas_para_prompt(llamadas: list[dict]) -> tuple[str, dict]:
    """
    Convierte la lista de llamadas en texto legible para el prompt de Claude.
    Retorna (texto_registro, dict_stats).
    """
    cerradas = sum(1 for l in llamadas if l["resultado"] == "CERRADA")
    perdidas  = sum(1 for l in llamadas if l["resultado"] == "PERDIDA")
    n_total   = len(llamadas)
    tasa      = round(cerradas / n_total * 100) if n_total else 0

    bloques = []
    for i, l in enumerate(llamadas, 1):
        partes = [
            f"── LLAMADA {i} ──────────────────────────────────",
            f"Resultado : {l['resultado']} | Score: {l['score']}/10 | Fecha: {l['fecha']}",
        ]
        if l.get("nombre") and l["nombre"] != "Llamada":
            partes.append(f"Lead      : {l['nombre']}")
        if l.get("notas"):
            partes.append(f"Notas CRM : {l['notas'][:300]}")
        if l.get("analisis_ia"):
            partes.append(f"Análisis IA:\n{l['analisis_ia']}")
        bloques.append("\n".join(partes))

    registro = "\n\n".join(bloques)
    stats = {
        "n_llamadas": n_total,
        "n_cerradas": cerradas,
        "n_perdidas": perdidas,
        "tasa":       tasa,
    }
    return registro, stats


# ══════════════════════════════════════════════════════════════════════════════
# Llamada a Claude Sonnet para síntesis
# ══════════════════════════════════════════════════════════════════════════════

def _llamar_claude_para_analisis(
    negocio: str,
    modo: str,
    registro: str,
    stats: dict,
    version_nueva: int,
) -> Optional[dict]:
    """
    Envía el registro de llamadas a Claude Sonnet y parsea el JSON devuelto.
    Fallback a Groq/Llama3 si no hay Anthropic key.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    prompt = _EVOLUTION_PROMPT.format(
        negocio        = negocio,
        modo           = modo,
        n_llamadas     = stats["n_llamadas"],
        n_cerradas     = stats["n_cerradas"],
        n_perdidas     = stats["n_perdidas"],
        tasa           = stats["tasa"],
        registro_llamadas = registro,
        version_nueva  = version_nueva,
        timestamp      = timestamp,
    )

    # ── Intento 1: Claude Sonnet ──────────────────────────────────────────────
    if api_key:
        try:
            import anthropic
            client  = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model      = "claude-sonnet-4-6",   # Sonnet para análisis de calidad
                max_tokens = 2000,
                messages   = [{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            logger.info(f"[Evolver] Claude Sonnet respondió ({len(raw)} chars)")
            return _parsear_json_seguro(raw)
        except Exception as e:
            logger.error(f"[Evolver] Claude Sonnet falló: {e}")

    # ── Intento 2: Groq / Llama3 ──────────────────────────────────────────────
    if groq_key:
        try:
            from groq import Groq
            groq_client = Groq(api_key=groq_key)
            completion  = groq_client.chat.completions.create(
                model       = "llama3-70b-8192",
                messages    = [{"role": "user", "content": prompt}],
                temperature = 0.2,
                max_tokens  = 2000,
            )
            raw = completion.choices[0].message.content.strip()
            logger.info(f"[Evolver] Groq/Llama3 respondió ({len(raw)} chars)")
            return _parsear_json_seguro(raw)
        except Exception as e:
            logger.error(f"[Evolver] Groq falló: {e}")

    # ── Fallback: conocimiento básico sin IA ──────────────────────────────────
    logger.warning("[Evolver] Sin IA disponible — generando knowledge básico")
    return _knowledge_fallback(stats, version_nueva, timestamp)


def _parsear_json_seguro(texto: str) -> Optional[dict]:
    """
    Extrae y parsea el JSON de la respuesta de Claude, aunque venga con
    markdown (```json ... ```) u otro texto alrededor.
    """
    # Intentar primero el texto completo
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    # Buscar bloque JSON entre ```json ... ``` o ``` ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Buscar el primer { ... } más largo (puede haber texto antes/después)
    m = re.search(r"(\{.*\})", texto, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    logger.error(f"[Evolver] No se pudo parsear JSON. Respuesta: {texto[:300]}")
    return None


def _knowledge_fallback(stats: dict, version: int, timestamp: str) -> dict:
    """
    Genera un knowledge básico cuando no hay IA disponible.
    Permite que el sistema funcione en modo degradado.
    """
    return {
        "version":           version,
        "updated_at":        timestamp,
        "total_analizadas":  stats["n_llamadas"],
        "cerradas":          stats["n_cerradas"],
        "perdidas":          stats["n_perdidas"],
        "tasa_conversion":   f"{stats['tasa']}%",
        "preguntas_sin_respuesta": [
            "Configura ANTHROPIC_API_KEY para análisis automático de preguntas sin respuesta"
        ],
        "perfil_comprador_exitoso": {
            "frases_trigger": ["me interesa", "¿cuándo tienen disponibilidad?"],
            "caracteristicas": ["pregunta por precio directamente", "menciona urgencia"],
            "momento_de_cierre": "Cuando el agente propone fecha y hora específica",
        },
        "motivos_perdida_tiempo": [
            "Sin intención real de compra",
            "Sin presupuesto disponible",
        ],
        "tecnicas_ganadoras": [
            "Proponer fecha específica en lugar de preguntar '¿cuándo quieres?'",
        ],
        "instrucciones_para_bot": (
            f"APRENDIZAJE ACTIVO (v{version}): "
            f"Tasa de conversión actual: {stats['tasa']}%. "
            "Configura ANTHROPIC_API_KEY para recibir instrucciones específicas "
            "basadas en el análisis real de tus llamadas."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Guardado en Supabase
# ══════════════════════════════════════════════════════════════════════════════

def _get_client_config(client_id: str) -> Optional[dict]:
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        return None
    try:
        from supabase import create_client
        db  = create_client(sb_url, sb_key)
        res = (
            db.table("clients_config")
            .select("dynamic_knowledge, modo_operacion, negocio_nombre")
            .eq("client_id", client_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"[Evolver] No se pudo leer clients_config: {e}")
        return None


def _guardar_dynamic_knowledge(client_id: str, knowledge: dict) -> bool:
    """
    Actualiza el campo dynamic_knowledge en clients_config.
    Si el registro no existe, lo crea con valores mínimos.
    """
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not sb_url or not sb_key:
        logger.warning("[Evolver] Sin Supabase — dynamic_knowledge no guardado.")
        _guardar_knowledge_local(client_id, knowledge)
        return False
    try:
        from supabase import create_client
        db = create_client(sb_url, sb_key)
        db.table("clients_config").upsert(
            {
                "client_id":         client_id,
                "dynamic_knowledge": knowledge,
                "updated_at":        datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="client_id",
        ).execute()
        logger.info(f"[Evolver] dynamic_knowledge v{knowledge.get('version')} guardado en Supabase")
        return True
    except Exception as e:
        logger.error(f"[Evolver] Error guardando en Supabase: {e}")
        _guardar_knowledge_local(client_id, knowledge)
        return False


def _guardar_knowledge_local(client_id: str, knowledge: dict) -> None:
    """Fallback: guarda el knowledge en un archivo JSON local."""
    path = _MOCK_S3_DIR / client_id / "dynamic_knowledge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[Evolver] dynamic_knowledge guardado localmente en {path}")
    except Exception as e:
        logger.error(f"[Evolver] No se pudo guardar localmente: {e}")


def cargar_knowledge_local(client_id: str) -> Optional[dict]:
    """
    Carga el dynamic_knowledge desde el archivo JSON local.
    Útil cuando Supabase no está disponible (desarrollo).
    """
    path = _MOCK_S3_DIR / client_id / "dynamic_knowledge.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
