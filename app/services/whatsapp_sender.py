"""
app/services/whatsapp_sender.py
────────────────────────────────────────────────────────────────────────────────
Servicio de WhatsApp para leads calientes (score >= 9).

Flujo:
  1. Gate de score: solo actúa cuando lead_score >= SCORE_MINIMO (9)
  2. Selecciona plantilla de mensaje según modo_operacion del cliente
  3. Envía por el proveedor configurado (Evolution API → Meta Cloud API → Mock)
  4. Registra resultado en la tabla 'seguimiento_leads' de Supabase

Proveedores soportados (en orden de prioridad):
  A. Evolution API  — EVOLUTION_API_URL + EVOLUTION_API_KEY + EVOLUTION_INSTANCE
  B. Meta WhatsApp Cloud API — WHATSAPP_TOKEN + WHATSAPP_PHONE_ID
  C. Mock (desarrollo) — imprime el mensaje, retorna éxito simulado

Variables de entorno requeridas (al menos un proveedor):
  EVOLUTION_API_URL      → URL base de tu instancia Evolution (ej: http://localhost:8080)
  EVOLUTION_API_KEY      → API key de Evolution
  EVOLUTION_INSTANCE     → Nombre de la instancia (ej: super_vendedor)
  WHATSAPP_TOKEN         → Bearer token de Meta (alternativa a Evolution)
  WHATSAPP_PHONE_ID      → ID del número de Meta (alternativa a Evolution)
"""

import os
import random
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Constante de gate ─────────────────────────────────────────────────────────
SCORE_MINIMO: int = 9  # Solo leads con score >= 9 reciben WhatsApp automático


# ══════════════════════════════════════════════════════════════════════════════
# BANCO DE MENSAJES — Múltiples variantes por modo para sonar humano
# Cada plantilla usa llaves {clave} que se rellenan con los datos del lead.
# ══════════════════════════════════════════════════════════════════════════════

_MENSAJES: dict[str, list[str]] = {

    # ── Modo 'venta' — agenda de cita B2C ─────────────────────────────────────
    "venta": [
        (
            "Hola {nombre}! 👋 Te escribe {agente} de {negocio}.\n\n"
            "Quedé con ganas de ayudarte a agendar tu {accion}. "
            "Esta semana tenemos espacio y no quería que te quedara por fuera.\n\n"
            "Reserva directo aquí 👉 {link}\n\n"
            "¿Te queda bien mañana o pasado?"
        ),
        (
            "Ey {nombre}! Soy {agente} de {negocio} 😊\n\n"
            "Vi que estás buscando {servicio} y quería contarte que esta semana "
            "tenemos disponibilidad limitada.\n\n"
            "Para no perder tu espacio, agéndalo aquí en 30 segundos:\n"
            "👉 {link}\n\n"
            "¿Alguna pregunta antes de agendar?"
        ),
        (
            "{nombre}, buenas! 🙌\n\n"
            "Soy {agente}, del equipo de {negocio}. "
            "Tenemos disponibilidad para tu {accion} esta semana y quería avisarte "
            "antes de que se ocupen los turnos.\n\n"
            "Aquí el link para reservar: {link} 📅\n\n"
            "¿Alguna duda? Aquí estoy."
        ),
    ],

    # ── Modo 'venta_directa' — cierre con link de pago, máxima urgencia ───────
    "venta_directa": [
        (
            "Hola {nombre} 🔥\n\n"
            "Soy {agente} de {negocio}. Te escribo porque el *{descuento}* en "
            "{servicio} vence *{oferta_expira}* y no quería que se te fuera.\n\n"
            "Ya hay varias personas que lo tomaron hoy. "
            "Aquí el link para cerrar ahora:\n"
            "💳 {link_pago}\n\n"
            "¿Lo vemos juntos o te surge alguna duda rápida?"
        ),
        (
            "{nombre}, oye! 👊\n\n"
            "Mira, el {descuento} que tenemos en {negocio} cierra *{oferta_expira}*. "
            "Si lo dejas para después ya no va a estar disponible a este precio.\n\n"
            "Para que quede asegurado, aquí el link directo:\n"
            "🔗 {link_pago}\n\n"
            "¿Lo hacemos ahora o necesitas que te aclare algo primero?"
        ),
        (
            "¡{nombre}! Buenas 😎\n\n"
            "Soy {agente} de {negocio} y te cuento: el precio especial de "
            "*{servicio}* ({descuento}) está activo solo hasta *{oferta_expira}*.\n\n"
            "Para no complicarte, aquí el link de pago:\n"
            "👉 {link_pago}\n\n"
            "Literalmente 2 minutos y queda listo. ¿Vamos?"
        ),
    ],

    # ── Modo 'b2b' — calificación BANT+, cierre de demo con AE ───────────────
    "b2b": [
        (
            "Hola {nombre}, ¿cómo estás? 👋\n\n"
            "Soy {agente} de {negocio}. Quedé pensando en lo que conversamos "
            "sobre {servicio} y creo que hay una oportunidad real para "
            "*{empresa}*.\n\n"
            "¿Tendrías 30 minuticos esta semana para que nuestro equipo te "
            "muestre cómo funciona en un caso similar al tuyo?\n\n"
            "Aquí puedes ver la disponibilidad: {link} 📅"
        ),
        (
            "{nombre}, buenas!\n\n"
            "{agente} por aquí, de {negocio}. Me quedó dando vueltas "
            "la situación que me comentaste con {empresa}.\n\n"
            "Creo que podemos ayudarlos a resolver eso más rápido de lo que "
            "esperan. ¿Agendamos una demo corta (30 min) con el equipo técnico?\n\n"
            "👉 {link}\n\n"
            "Sin presión, solo para que vean si tiene sentido."
        ),
        (
            "Hola {nombre}! Soy {agente} de {negocio} 🤝\n\n"
            "Después de nuestra conversación, quise buscarte porque "
            "empresas similares a {empresa} han logrado resultados concretos "
            "con {servicio} en menos de 60 días.\n\n"
            "¿Te parece si agendamos 30 minutos para mostrarte cómo?\n"
            "Aquí el link: {link}"
        ),
    ],

    # ── Modo 'prospeccion_b2b' — SDR, descubrimiento de dolor ────────────────
    "prospeccion_b2b": [
        (
            "Hola {nombre}! 👋 Soy {agente}, SDR de {negocio}.\n\n"
            "Quedé con la duda de cómo están resolviendo hoy el tema de "
            "{servicio} en {empresa}.\n\n"
            "¿Tendría sentido agendar un call rápido de 20 min? "
            "No para venderte nada, sino para entender tu situación y ver "
            "si realmente podemos ayudar.\n\n"
            "Aquí el link de mi agenda: {link} 📞"
        ),
        (
            "{nombre}, ¿cómo va todo?\n\n"
            "Soy {agente} de {negocio}. Estuve investigando un poco sobre "
            "{empresa} y me surgió una pregunta: ¿cómo están manejando hoy "
            "{servicio}?\n\n"
            "Si me das 20 minutos, puedo contarte cómo lo están resolviendo "
            "empresas parecidas. Sin pitch, prometo 😄\n\n"
            "👉 {link}"
        ),
        (
            "Ey {nombre}! Soy {agente} de {negocio} 👋\n\n"
            "Me contacto porque trabajamos con negocios como {empresa} y "
            "normalmente descubrimos 2-3 cosas que se pueden mejorar en "
            "{servicio} sin grandes inversiones.\n\n"
            "¿Agendamos 20 min para explorar si aplica para ustedes?\n"
            "Aquí mi calendario: {link}"
        ),
    ],
}

# Fallback cuando el modo no está en el dict
_MENSAJES["default"] = _MENSAJES["venta"]


# ══════════════════════════════════════════════════════════════════════════════
# Clase principal
# ══════════════════════════════════════════════════════════════════════════════

class WhatsAppSender:
    """
    Envía mensajes de WhatsApp a leads calientes (score >= SCORE_MINIMO).

    Uso:
        sender = WhatsAppSender(tenant_id="ednetpro_demo")
        result = sender.enviar_lead_caliente(lead_dict, client_config_dict)
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

        # ── Credenciales Evolution API ───────────────────────────────────────
        self.evolution_url      = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
        self.evolution_key      = os.environ.get("EVOLUTION_API_KEY", "")
        self.evolution_instance = os.environ.get("EVOLUTION_INSTANCE", "super_vendedor")

        # ── Credenciales Meta WhatsApp Cloud API ────────────────────────────
        self.meta_token    = os.environ.get("WHATSAPP_TOKEN", "")
        self.meta_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")

        # ── Supabase ─────────────────────────────────────────────────────────
        self._db = None
        sb_url = os.environ.get("SUPABASE_URL", "")
        sb_key = os.environ.get("SUPABASE_KEY", "")
        if sb_url and sb_key:
            try:
                from supabase import create_client
                self._db = create_client(sb_url, sb_key)
            except Exception as e:
                logger.warning(f"[WhatsApp] Supabase no disponible: {e}")

    # ── API pública ───────────────────────────────────────────────────────────

    def enviar_lead_caliente(
        self,
        lead: dict,
        client_config: Optional[dict] = None,
    ) -> dict:
        """
        Punto de entrada principal.

        Args:
            lead:          Fila de leads_crm (debe tener nombre, telefono, lead_score).
            client_config: Fila de clients_config (modo_operacion, nombre_agente, etc.).
                           Si es None, usa valores por defecto.

        Returns:
            {
                "enviado":   bool,
                "proveedor": "evolution" | "meta" | "mock" | "bloqueado",
                "motivo":    str,        # si no se envió
                "mensaje":   str,        # texto enviado
                "seguimiento_id": str,   # UUID del registro en Supabase
            }
        """
        score = lead.get("lead_score", 0)

        # ── Gate de score ────────────────────────────────────────────────────
        if score < SCORE_MINIMO:
            logger.info(
                f"[WhatsApp] Lead '{lead.get('nombre')}' score={score} "
                f"< {SCORE_MINIMO}. No se envía."
            )
            return {
                "enviado":   False,
                "proveedor": "bloqueado",
                "motivo":    f"score {score} < {SCORE_MINIMO}",
                "mensaje":   "",
                "seguimiento_id": None,
            }

        config  = client_config or {}
        telefono = self._normalizar_telefono(lead.get("telefono", ""))

        if not telefono:
            return {
                "enviado":   False,
                "proveedor": "bloqueado",
                "motivo":    "teléfono vacío o inválido",
                "mensaje":   "",
                "seguimiento_id": None,
            }

        # ── Construir mensaje personalizado ──────────────────────────────────
        mensaje = self._construir_mensaje(lead, config)

        # ── Enviar por el proveedor disponible ───────────────────────────────
        resultado_envio = self._enviar_mensaje(telefono, mensaje)

        # ── Registrar en Supabase ────────────────────────────────────────────
        seguimiento_id = self._registrar_seguimiento(
            lead       = lead,
            mensaje    = mensaje,
            telefono   = telefono,
            resultado  = resultado_envio,
            config     = config,
        )

        logger.info(
            f"[WhatsApp] Lead '{lead.get('nombre')}' | score={score} | "
            f"tel={telefono} | proveedor={resultado_envio['proveedor']} | "
            f"enviado={resultado_envio['enviado']}"
        )

        return {
            **resultado_envio,
            "mensaje":        mensaje,
            "seguimiento_id": seguimiento_id,
        }

    # ── Construcción del mensaje ──────────────────────────────────────────────

    def _construir_mensaje(self, lead: dict, config: dict) -> str:
        """
        Elige aleatoriamente una plantilla del banco de mensajes
        y la rellena con los datos reales del lead y el cliente.
        """
        modo      = (config.get("modo_operacion") or "venta").lower()
        plantillas = _MENSAJES.get(modo, _MENSAJES["default"])
        plantilla  = random.choice(plantillas)

        # Valores de relleno — prioridad: lead > config > defaults
        nombre  = (lead.get("nombre") or "").split()[0] or "amigo"  # solo el primer nombre
        empresa = lead.get("empresa") or lead.get("nombre") or "tu empresa"

        variables = {
            "nombre":        nombre,
            "agente":        config.get("nombre_agente")       or "el equipo",
            "negocio":       config.get("negocio_nombre")      or "nosotros",
            "servicio":      config.get("productos_servicios") or "nuestros servicios",
            "accion":        config.get("accion")              or "cita",
            "empresa":       empresa,
            # venta_directa
            "link_pago":     config.get("link_de_pago")        or config.get("link") or "https://wa.me/",
            "descuento":     config.get("descuento_activo")    or "descuento especial",
            "oferta_expira": config.get("oferta_expira")       or "pronto",
            # link genérico (cita / demo / agenda)
            "link":          config.get("link_reserva") or config.get("link_de_pago") or "https://wa.me/",
        }

        try:
            return plantilla.format(**variables)
        except KeyError as e:
            logger.error(f"[WhatsApp] Variable faltante en plantilla: {e}")
            # Fallback ultra-simple
            return (
                f"Hola {nombre}! 👋 Te escribe {variables['agente']} de "
                f"{variables['negocio']}. Quedamos pendientes — ¿cuándo "
                f"podemos hablar? Aquí el link: {variables['link']}"
            )

    # ── Envío HTTP ────────────────────────────────────────────────────────────

    def _enviar_mensaje(self, telefono: str, mensaje: str) -> dict:
        """
        Intenta enviar por Evolution API, luego Meta, luego Mock.
        Siempre retorna un dict con 'enviado', 'proveedor' y 'respuesta_api'.
        """
        # ── Proveedor A: Evolution API ───────────────────────────────────────
        if self.evolution_url and self.evolution_key:
            return self._enviar_evolution(telefono, mensaje)

        # ── Proveedor B: Meta WhatsApp Cloud API ─────────────────────────────
        if self.meta_token and self.meta_phone_id:
            return self._enviar_meta(telefono, mensaje)

        # ── Proveedor C: Mock (desarrollo / sin credenciales) ────────────────
        return self._enviar_mock(telefono, mensaje)

    def _enviar_evolution(self, telefono: str, mensaje: str) -> dict:
        url     = f"{self.evolution_url}/message/sendText/{self.evolution_instance}"
        headers = {"apikey": self.evolution_key, "Content-Type": "application/json"}
        payload = {
            "number":  telefono,
            "text":    mensaje,
            "delay":   1200,   # delay natural de 1.2 s para simular escritura humana
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return {
                    "enviado":      True,
                    "proveedor":    "evolution",
                    "respuesta_api": resp.json(),
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"[Evolution] HTTP {e.response.status_code}: {e.response.text}")
            return {
                "enviado":      False,
                "proveedor":    "evolution",
                "respuesta_api": {"error": str(e), "status": e.response.status_code},
            }
        except Exception as e:
            logger.error(f"[Evolution] Error de conexión: {e}")
            return {
                "enviado":      False,
                "proveedor":    "evolution",
                "respuesta_api": {"error": str(e)},
            }

    def _enviar_meta(self, telefono: str, mensaje: str) -> dict:
        url     = f"https://graph.facebook.com/v19.0/{self.meta_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_token}",
            "Content-Type":  "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to":   telefono,
            "type": "text",
            "text": {"body": mensaje},
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return {
                    "enviado":       True,
                    "proveedor":     "meta",
                    "respuesta_api": resp.json(),
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"[Meta WA] HTTP {e.response.status_code}: {e.response.text}")
            return {
                "enviado":       False,
                "proveedor":     "meta",
                "respuesta_api": {"error": str(e), "status": e.response.status_code},
            }
        except Exception as e:
            logger.error(f"[Meta WA] Error de conexión: {e}")
            return {
                "enviado":       False,
                "proveedor":     "meta",
                "respuesta_api": {"error": str(e)},
            }

    def _enviar_mock(self, telefono: str, mensaje: str) -> dict:
        """Modo desarrollo: imprime el mensaje pero no hace llamada HTTP."""
        borde = "─" * 60
        print(f"\n{borde}")
        print(f"[WhatsApp MOCK] Para: {telefono}")
        print(f"{borde}")
        print(mensaje)
        print(f"{borde}\n")
        return {
            "enviado":       True,
            "proveedor":     "mock",
            "respuesta_api": {"mock": True, "telefono": telefono},
        }

    # ── Normalización de teléfono ─────────────────────────────────────────────

    @staticmethod
    def _normalizar_telefono(telefono: str) -> str:
        """
        Limpia y normaliza el número a formato internacional sin '+'.
        Ejemplos:
          '+573175824601'  → '573175824601'
          '3175824601'     → '573175824601'  (asume Colombia)
          '(317) 582-4601' → '573175824601'
        """
        if not telefono:
            return ""

        # Quitar todo lo que no sea dígito
        digitos = "".join(c for c in telefono if c.isdigit())

        if not digitos:
            return ""

        # Si empieza con 57 y tiene 12 dígitos → ya está correcto
        if digitos.startswith("57") and len(digitos) == 12:
            return digitos

        # Si tiene 10 dígitos y empieza por 3 → número colombiano sin código de país
        if len(digitos) == 10 and digitos.startswith("3"):
            return "57" + digitos

        # Si tiene 11 dígitos y empieza con 0 → quitar el 0 y añadir 57
        if len(digitos) == 11 and digitos.startswith("0"):
            return "57" + digitos[1:]

        # En cualquier otro caso, devolver como está
        return digitos

    # ── Persistencia en Supabase ──────────────────────────────────────────────

    def _registrar_seguimiento(
        self,
        lead: dict,
        mensaje: str,
        telefono: str,
        resultado: dict,
        config: dict,
    ) -> Optional[str]:
        """
        Inserta un registro en 'seguimiento_leads' y retorna su UUID.
        Si Supabase no está disponible, solo loggea.
        """
        if not self._db:
            logger.warning("[WhatsApp] Supabase no disponible — seguimiento no guardado.")
            return None

        modo = (config.get("modo_operacion") or "venta").lower()
        tipo = (
            "link_pago"  if modo == "venta_directa"   else
            "demo"       if modo in ("b2b", "prospeccion_b2b") else
            "reserva"
        )

        fila = {
            "tenant_id":      self.tenant_id,
            "lead_id":        lead.get("id"),
            "nombre_lead":    lead.get("nombre", ""),
            "telefono":       telefono,
            "canal":          "whatsapp",
            "tipo_mensaje":   tipo,
            "mensaje_enviado": mensaje,
            "estado_envio":   "enviado" if resultado["enviado"] else "fallido",
            "lead_score":     lead.get("lead_score"),
            "proveedor":      resultado.get("proveedor", "desconocido"),
            "respuesta_api":  resultado.get("respuesta_api", {}),
            "created_at":     datetime.now(timezone.utc).isoformat(),
        }

        try:
            res = self._db.table("seguimiento_leads").insert(fila).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as e:
            logger.error(f"[WhatsApp] Error guardando seguimiento: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# Función de conveniencia para uso directo desde vapi_handler
# ══════════════════════════════════════════════════════════════════════════════

def trigger_whatsapp_si_hot_lead(
    tenant_id: str,
    telefono_lead: str,
    client_id: str,
) -> dict:
    """
    Función de alto nivel para llamar desde background_tasks en Vapi.

    1. Busca el lead en leads_crm por teléfono + tenant_id.
    2. Si score >= SCORE_MINIMO, busca la config del cliente.
    3. Llama a WhatsAppSender.enviar_lead_caliente().
    4. Retorna el resultado del envío.
    """
    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")

    lead   = _fetch_lead(sb_url, sb_key, tenant_id, telefono_lead)
    config = _fetch_client_config(sb_url, sb_key, client_id)

    if not lead:
        logger.info(f"[WhatsApp Trigger] Lead no encontrado: tel={telefono_lead}")
        return {"enviado": False, "motivo": "lead no encontrado en DB"}

    sender = WhatsAppSender(tenant_id=tenant_id)
    return sender.enviar_lead_caliente(lead, config)


def _fetch_lead(
    sb_url: str, sb_key: str,
    tenant_id: str, telefono: str,
) -> Optional[dict]:
    if not sb_url or not sb_key or not telefono:
        return None
    try:
        from supabase import create_client
        db  = create_client(sb_url, sb_key)
        # Normalizar teléfono para la búsqueda
        tel_norm = WhatsAppSender._normalizar_telefono(telefono)
        tel_variants = list({telefono, tel_norm, "+" + tel_norm})

        for tel in tel_variants:
            res = (
                db.table("leads_crm")
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("telefono", tel)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
    except Exception as e:
        logger.warning(f"[WhatsApp] No se pudo leer lead de Supabase: {e}")
    return None


def _fetch_client_config(sb_url: str, sb_key: str, client_id: str) -> dict:
    if not sb_url or not sb_key or not client_id:
        return {}
    try:
        from supabase import create_client
        db  = create_client(sb_url, sb_key)
        res = (
            db.table("clients_config")
            .select("*")
            .eq("client_id", client_id)
            .eq("activo", True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.warning(f"[WhatsApp] No se pudo leer client_config: {e}")
        return {}
