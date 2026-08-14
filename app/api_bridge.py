"""
app/api_bridge.py
────────────────────────────────────────────────────────────────────────────────
Puente HTTP para Hermes Agent (VPS Coolify :8085) → agentes Python (:8000).

Endpoint: POST /api/v1/agents/{agent_name}
Agentes: negotiator | objection_killer | closing | catalog_bridge | prospecto
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agents",
    tags=["Hermes Bridge"],
    dependencies=[Depends(verify_api_key)],
)

AgentName = Literal[
    "negotiator",
    "objection_killer",
    "closing",
    "catalog_bridge",
    "prospecto",
]

AGENT_ALIASES: dict[str, str] = {
    "hermes": "negotiator",
    "hermes_negotiator": "negotiator",
    "objection": "objection_killer",
    "objection_killer_agent": "objection_killer",
    "closing_followup": "closing",
    "closing_followup_agent": "closing",
    "catalog": "catalog_bridge",
    "catalog_bridge_agent": "catalog_bridge",
    "shaka": "prospecto",
    "shaka_quantum_prospector": "prospecto",
}


# ── Esquemas Hermes ───────────────────────────────────────────────────────────


class AgentContext(BaseModel):
    """Contexto opcional enviado por Hermes / Evolution API / n8n."""

    user_offer: Optional[float] = Field(None, description="Oferta numérica del cliente (COP)")
    product_query: Optional[str] = Field(None, description="Nombre o referencia de producto")
    nombre: Optional[str] = Field(None, description="Nombre del lead")
    estado: Optional[str] = Field(None, description="Estado CRM: negociando, contactado, etc.")
    lead_score: Optional[int] = Field(None, ge=1, le=10)
    prospecto: Optional[dict[str, Any]] = Field(None, description="Payload Hunter/Shaka")
    extra: dict[str, Any] = Field(default_factory=dict)


class HermesAgentRequest(BaseModel):
    user_id: str = Field(default="", description="ID interno Hermes / Evolution")
    phone: str = Field(..., description="Teléfono WhatsApp normalizado")
    message: str = Field(..., description="Texto del usuario")
    context: AgentContext = Field(default_factory=AgentContext)


class HermesAgentResponse(BaseModel):
    """Formato estándar consumido por Hermes Agent dashboard."""

    status: Literal["success", "no_action", "error"] = "success"
    agent: str
    message: str = Field(description="Texto listo para enviar por WhatsApp")
    intent_detected: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    persistence: dict[str, Any] = Field(default_factory=dict)


# ── Endpoint principal ────────────────────────────────────────────────────────


@router.get("", summary="Listar agentes disponibles para Hermes")
def list_agents() -> dict[str, Any]:
    return {
        "bridge": "supervendedor-core-ednetpro",
        "base_url": settings.PUBLIC_URL or "http://178.105.48.103:8000",
        "agents": [
            {"name": "negotiator", "class": "HermesNegotiator", "use": "Negociación ZOPA / contraoferta"},
            {"name": "objection_killer", "class": "ObjectionKillerAgent", "use": "Objeciones de precio, envío, competencia"},
            {"name": "closing", "class": "ClosingFollowupAgent", "use": "Cierre y reactivación de venta"},
            {"name": "catalog_bridge", "class": "CatalogBridgeAgent", "use": "Stock, ZOPA y productos Shein"},
            {"name": "prospecto", "class": "ShakaQuantumProspector", "use": "Scoring Hunter / apertura B2B"},
        ],
    }


@router.post("/{agent_name}", response_model=HermesAgentResponse, summary="Invocar agente por nombre")
async def invoke_agent(agent_name: str, body: HermesAgentRequest) -> HermesAgentResponse:
    normalized = AGENT_ALIASES.get(agent_name.strip().lower(), agent_name.strip().lower())
    if normalized not in (
        "negotiator",
        "objection_killer",
        "closing",
        "catalog_bridge",
        "prospecto",
    ):
        raise HTTPException(
            status_code=404,
            detail=f"Agente '{agent_name}' no registrado. Use: negotiator, objection_killer, closing, catalog_bridge, prospecto",
        )

    phone = _normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Teléfono inválido")

    # Persistencia PocketBase (leads + conversaciones)
    persistence = _ensure_persistence(phone, body)

    try:
        if normalized == "negotiator":
            result = _run_negotiator(body)
        elif normalized == "objection_killer":
            result = _run_objection_killer(body)
        elif normalized == "closing":
            result = _run_closing(body)
        elif normalized == "catalog_bridge":
            result = _run_catalog_bridge(body)
        else:
            result = _run_prospecto(body)

        _persist_agent_turn(
            persistence.get("conversation_id", ""),
            persistence.get("lead_id", ""),
            phone,
            body.message,
            result.message,
            agent=normalized,
        )

        result.persistence = persistence
        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[HermesBridge] Error agent=%s phone=%s", normalized, phone)
        raise HTTPException(status_code=500, detail=f"Error en agente {normalized}: {exc}") from exc


# ── Dispatchers por agente ───────────────────────────────────────────────────


def _run_negotiator(body: HermesAgentRequest) -> HermesAgentResponse:
    from app.agents.catalog_bridge_agent import get_catalog_bridge
    from app.agents.hermes_negotiator import HermesNegotiator

    bridge = get_catalog_bridge()
    query = body.context.product_query or body.message
    zopa = bridge.get_zopa_for_message(query)

    user_offer = body.context.user_offer or _parse_cop_amount(body.message)
    if user_offer is None:
        user_offer = zopa.get("target_price", 0) * 0.85

    negotiator = HermesNegotiator(
        target_price=float(zopa.get("target_price", 0)),
        reserve_price=float(zopa.get("reserve_price", 0)),
    )
    decision = negotiator.calculate_counter_offer(float(user_offer))
    reply = negotiator.generate_response(decision)

    return HermesAgentResponse(
        status="success",
        agent="negotiator",
        message=reply,
        intent_detected="negociacion_precio",
        data={
            "decision": decision,
            "zopa": zopa,
            "user_offer": user_offer,
        },
    )


def _run_objection_killer(body: HermesAgentRequest) -> HermesAgentResponse:
    from app.agents.catalog_bridge_agent import get_catalog_bridge
    from app.agents.objection_killer_agent import get_objection_killer

    bridge = get_catalog_bridge()
    query = body.context.product_query or body.message
    zopa = bridge.get_zopa_for_message(query)
    product = bridge.find_product(query)
    titulo = (product or {}).get("titulo") or zopa.get("titulo", "")

    killer = get_objection_killer()
    handled = killer.handle(body.message, zopa, product_title=titulo)

    if not handled:
        return HermesAgentResponse(
            status="no_action",
            agent="objection_killer",
            message="",
            intent_detected=None,
            data={"objection_detected": False, "zopa": zopa},
        )

    return HermesAgentResponse(
        status="success",
        agent="objection_killer",
        message=handled["response"],
        intent_detected=handled["objection_type"],
        data=handled,
    )


def _run_closing(body: HermesAgentRequest) -> HermesAgentResponse:
    from app.agents.closing_followup_agent import get_followup_agent

    agent = get_followup_agent()
    lead = {
        "nombre": body.context.nombre or "amigo/a",
        "estado": body.context.estado or "negociando",
        "notas": body.message,
    }
    reply = agent._build_reactivation_message(lead)

    return HermesAgentResponse(
        status="success",
        agent="closing",
        message=reply,
        intent_detected="cierre_reactivacion",
        data={"lead_snapshot": lead},
    )


def _run_catalog_bridge(body: HermesAgentRequest) -> HermesAgentResponse:
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    query = body.context.product_query or body.message
    product = bridge.find_product(query)
    zopa = bridge.get_zopa_for_message(query)
    summary = bridge.get_catalog_summary()

    if product:
        msg = (
            f"📦 *{product['titulo']}*\n"
            f"💰 Precio: *${product.get('precio_reventa', product.get('target_price', 0)):,.0f} COP*\n"
            f"✅ Pago contra entrega — Cúcuta\n"
            f"¿Te aparto una talla?"
        )
    else:
        top = summary.get("top_titles") or []
        msg = (
            f"Tenemos *{summary.get('total_products', 0)}* productos en catálogo.\n"
            f"Destacados: {', '.join(top[:3]) or 'enterizos deportivos'}.\n"
            f"¿Qué estilo buscas?"
        )

    return HermesAgentResponse(
        status="success",
        agent="catalog_bridge",
        message=msg,
        intent_detected="consulta_catalogo",
        data={"product": product, "zopa": zopa, "summary": summary},
    )


def _run_prospecto(body: HermesAgentRequest) -> HermesAgentResponse:
    from app.agents.shaka_quantum_prospector import ShakaQuantumProspector

    shaka = ShakaQuantumProspector()
    prospecto = body.context.prospecto or {
        "nombre_negocio": body.context.nombre or body.message[:80],
        "telefono": body.phone,
        "categoria": body.context.extra.get("categoria", ""),
        "ciudad": body.context.extra.get("ciudad", "Cúcuta"),
        "rating": body.context.extra.get("rating"),
        "total_reviews": body.context.extra.get("total_reviews", 0),
        "sitio_web": body.context.extra.get("sitio_web", ""),
    }
    score = body.context.lead_score or 5
    collapse = shaka.score_hunter_lead(prospecto, score)

    return HermesAgentResponse(
        status="success",
        agent="prospecto",
        message=collapse.get("opening_line", ""),
        intent_detected="prospeccion_b2b",
        data=collapse,
    )


# ── PocketBase ────────────────────────────────────────────────────────────────


def _ensure_persistence(phone: str, body: HermesAgentRequest) -> dict[str, str]:
    """Reutiliza helpers de chat.py para leads/conversaciones en PocketBase."""
    try:
        from app.routers.chat import (
            _get_or_create_conversation,
            _get_or_create_lead,
        )

        lead_id = _get_or_create_lead(phone)
        conv_id, _ = _get_or_create_conversation(phone, lead_id)
        return {
            "lead_id": lead_id,
            "conversation_id": conv_id,
            "user_id": body.user_id or "",
            "phone": phone,
        }
    except Exception as exc:
        logger.debug("[HermesBridge] Persistencia omitida: %s", exc)
        return {"lead_id": f"local-{phone}", "conversation_id": f"conv-{phone}", "phone": phone}


def _persist_agent_turn(
    conversation_id: str,
    lead_id: str,
    phone: str,
    user_msg: str,
    bot_msg: str,
    *,
    agent: str,
) -> None:
    if not bot_msg:
        return
    try:
        from app.routers.chat import _persist_message

        _persist_message(conversation_id, lead_id, phone, "user", user_msg, message_type="text")
        enriched = f"[agent:{agent}] {bot_msg}"
        _persist_message(
            conversation_id,
            lead_id,
            phone,
            "assistant",
            enriched,
            message_type="text",
        )
    except Exception as exc:
        logger.debug("[HermesBridge] Mensajes no persistidos: %s", exc)


# ── Utilidades ────────────────────────────────────────────────────────────────


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def _parse_cop_amount(text: str) -> Optional[float]:
    """Extrae monto COP desde texto ('85000', '85.000', '85 mil')."""
    raw = (text or "").lower().replace(",", "").replace(".", "")
    if "mil" in raw:
        m = re.search(r"(\d+)\s*mil", raw)
        if m:
            return float(m.group(1)) * 1000
    m = re.search(r"(\d{4,7})", raw.replace(" ", ""))
    if m:
        return float(m.group(1))
    return None
