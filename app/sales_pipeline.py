"""
app/sales_pipeline.py
────────────────────────────────────────────────────────────────────────────────
Helpers compartidos del pipeline de ventas WhatsApp — evita lógica duplicada.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.agents.catalog_bridge_agent import get_catalog_bridge
from app.agents.hermes_negotiator import HermesNegotiator
from app.agents.objection_killer_agent import get_objection_killer


def parse_offer_from_message(message: str) -> Optional[float]:
    """Extrae oferta numérica COP del mensaje del prospecto."""
    msg = message.lower().replace(",", "").replace(".", "")
    patterns = [
        r"(?:ofrezco|pago|tengo|maximo|máximo|solo)\s*\$?\s*(\d{4,7})",
        r"\$\s*(\d{4,7})",
        r"(\d{5,7})\s*(?:cop|pesos)?",
    ]
    for pat in patterns:
        m = re.search(pat, msg)
        if m:
            val = float(m.group(1))
            if val >= 10000:
                return val
    return None


def build_hermes_from_catalog(user_message: str = "") -> tuple[HermesNegotiator, dict[str, Any]]:
    """Consulta catalog bridge antes de instanciar Hermes (elimina hardcoded)."""
    bridge = get_catalog_bridge()
    zopa = bridge.get_zopa_for_message(user_message)
    hermes = HermesNegotiator(
        target_price=zopa["target_price"],
        reserve_price=zopa["reserve_price"],
    )
    return hermes, zopa


def try_handle_objection(message: str, zopa: dict[str, Any]) -> Optional[str]:
    """Retorna respuesta si hay objeción crítica; None si continúa flujo Hermes."""
    killer = get_objection_killer()
    result = killer.handle(message, zopa, product_title=zopa.get("titulo", ""))
    if not result:
        return None
    return result["response"]


def negotiate_response(message: str) -> str:
    """
    Flujo unificado: objeción → Hermes ZOPA → respuesta persuasiva.
    Siempre consulta catalog_bridge primero.
    """
    hermes, zopa = build_hermes_from_catalog(message)

    objection_reply = try_handle_objection(message, zopa)
    if objection_reply:
        return objection_reply

    user_offer = parse_offer_from_message(message)
    if user_offer is not None:
        decision = hermes.calculate_counter_offer(user_offer)
    else:
        decision = {"action": "counter", "price": zopa["target_price"]}

    return hermes.generate_response(decision)
