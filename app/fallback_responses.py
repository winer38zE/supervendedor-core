"""
Plantillas de respuesta cuando falla el LLM (Hermes / Objection Killer).
"""

from __future__ import annotations

HERMES_TEMPLATES = {
    "accept": (
        "¡Perfecto! Cerramos el pedido ahora mismo. "
        "Confírmame talla y dirección en Cúcuta para el envío contra entrega."
    ),
    "counter": (
        "Mira, te hago un esfuerzo y lo dejamos en *${price:,.0f} COP* con pago al recibir. "
        "¿Te lo aparto hoy?"
    ),
    "reject_counter": (
        "Entiendo tu presupuesto. Lo mínimo que puedo ofrecerte es *${price:,.0f} COP* "
        "con entrega en Cúcuta — es precio especial de catálogo."
    ),
}

OBJECTION_TEMPLATES = {
    "precio_alto": (
        "Te entiendo — por ser cliente directo te dejo *{titulo}* en "
        "*${authorized:,.0f} COP* (precio especial de hoy).\n"
        "Pago *solo cuando recibes* en Cúcuta. ¿Te lo aparto?"
    ),
    "desconfianza_envio": (
        "Totalmente válido desconfiar. Por eso trabajamos *pago contra entrega*: "
        "recibes *{titulo}*, lo revisas y *ahí pagas*.\n"
        "Entregas en Cúcuta y envío nacional con seguimiento por WhatsApp."
    ),
    "consultar": (
        "Claro, tómate tu tiempo. Te *aparto {titulo}* por 24 horas "
        "al precio de *${target:,.0f} COP* para que no suba.\n"
        "Escríbeme cuando decidas — sin compromiso."
    ),
    "competencia": (
        "En Shein esperas semanas; con nosotros *{titulo}* llega rápido "
        "a Cúcuta con *pago al recibir* por *${target:,.0f} COP*.\n"
        "Soporte directo por WhatsApp — ¿te envío la ficha con foto?"
    ),
}


def hermes_fallback(decision: dict) -> str:
    action = decision.get("action", "counter")
    price = float(decision.get("price", 0))
    tpl = HERMES_TEMPLATES.get(action, HERMES_TEMPLATES["counter"])
    return tpl.replace("${price:,.0f}", f"{price:,.0f}")


def objection_fallback(objection_type: str, ctx: dict) -> str:
    tpl = OBJECTION_TEMPLATES.get(objection_type, OBJECTION_TEMPLATES["precio_alto"])
    titulo = ctx.get("titulo", "este producto")
    authorized = float(ctx.get("authorized", ctx.get("target_price", 0)))
    target = float(ctx.get("target_price", authorized))
    out = tpl.replace("{titulo}", titulo)
    out = out.replace("${authorized:,.0f}", f"{authorized:,.0f}")
    out = out.replace("${target:,.0f}", f"{target:,.0f}")
    return out
