#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atacar_cartera.py
══════════════════════════════════════════════════════════════════════════════
CENTINELA — Motor de Ataque de Cartera  |  ED NET PRO
Técnica de cobro: Empatía Táctica (Chris Voss · Never Split the Difference)
══════════════════════════════════════════════════════════════════════════════

Flujo de ejecución:
  1. Conecta a Supabase y extrae el deudor objetivo ('Juan Perez').
  2. Si no está en BD, usa un registro demo con datos realistas.
  3. Calcula intereses, quita aplicable y monto final.
  4. Genera mensaje WhatsApp con Empatía Táctica (Voss).
  5. Envía por Evolution API → Meta → Mock (según disponibilidad).
  6. Registra la acción en bitacora_centinela.
  7. Imprime el resumen ejecutivo con comisión del 20% en terminal.

Uso:
  python atacar_cartera.py
  python atacar_cartera.py --nombre "Pedro Gomez" --dry-run
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import textwrap
from datetime import datetime, timezone

# Forzar UTF-8 en la terminal de Windows (CP1252 no soporta caracteres de caja)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv

# ── Cargar variables de entorno ───────────────────────────────────────────────
load_dotenv()

# ── Logging en color para la terminal ─────────────────────────────────────────
class _ColorFormatter(logging.Formatter):
    """Formatter con colores ANSI para una terminal profesional."""

    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    CYAN   = "\033[96m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    MAGENTA= "\033[95m"
    WHITE  = "\033[97m"
    DIM    = "\033[2m"

    LEVEL_COLORS = {
        "DEBUG":    DIM,
        "INFO":     CYAN,
        "WARNING":  YELLOW,
        "ERROR":    RED,
        "CRITICAL": RED + BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        color   = self.LEVEL_COLORS.get(record.levelname, self.RESET)
        ts      = datetime.now().strftime("%H:%M:%S")
        level   = f"{color}[{record.levelname:<8}]{self.RESET}"
        name    = f"{self.DIM}{record.name}{self.RESET}"
        message = record.getMessage()
        return f"{self.DIM}{ts}{self.RESET} {level} {name} — {message}"


def _setup_logging(verbose: bool = False) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_ColorFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    return logging.getLogger("centinela")


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES DE NEGOCIO
# ══════════════════════════════════════════════════════════════════════════════

COMISION_PCT          = 20          # % de comisión sobre el monto recuperado
TASA_INTERES_DIARIA   = 0.001       # 0.10% diario por defecto
AGENTE_NOMBRE         = "Valentina" # Nombre del agente en el mensaje
EMPRESA_NOMBRE        = "ED NET PRO Cobranzas"

# Tabla de quitas (días_mora → % máximo de descuento)
TRAMOS_QUITA = [
    (0,    30,   0),
    (31,   60,   5),
    (61,   90,  10),
    (91,  180,  20),
    (181, 365,  30),
    (366, 730,  40),
    (731, 9999, 50),
]

# Registro demo cuando el deudor no está en BD
DEMO_JUAN_PEREZ = {
    "id":                  "demo-uuid-juan-perez-001",
    "tenant_id":           "ednetpro_demo",
    "nombre":              "Juan Perez",
    "telefono":            "3175824601",
    "cedula":              "1020304050",
    "deuda_original":      2_500_000.0,
    "deuda_actual":        2_500_000.0,
    "dias_mora":           127,
    "tasa_interes_diaria": TASA_INTERES_DIARIA,
    "intereses_acumulados": 0.0,        # se recalcula en tiempo real
    "estado":              "activo",
    "canal_contacto":      "whatsapp",
    "notas":               "Deudor demo — primer contacto",
    "_es_demo":            True,
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONEXIÓN A SUPABASE
# ══════════════════════════════════════════════════════════════════════════════

def conectar_supabase(log: logging.Logger):
    """Retorna el cliente Supabase o None si faltan credenciales."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")

    if not url or not key or "tu-url" in url:
        log.warning("Supabase no configurado — modo demo activado.")
        return None

    try:
        from supabase import create_client
        client = create_client(url, key)
        log.info(f"Conectado a Supabase: {url.split('//')[1].split('.')[0]}.supabase.co")
        return client
    except Exception as e:
        log.error(f"Error al conectar con Supabase: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 2. EXTRACCIÓN DEL DEUDOR
# ══════════════════════════════════════════════════════════════════════════════

def extraer_deudor(db, nombre_busqueda: str, log: logging.Logger) -> dict:
    """
    Busca el deudor en clientes_recuperacion.
    Coincidencia flexible: nombre contiene el valor buscado (case-insensitive).
    Retorna el primer resultado o el registro demo si no se encuentra.
    """
    if db is None:
        log.warning(f"Sin conexion DB — usando registro demo para '{nombre_busqueda}'.")
        return DEMO_JUAN_PEREZ.copy()

    try:
        # ilike = case-insensitive LIKE en Supabase/PostgREST
        res = (
            db.table("clientes_recuperacion")
            .select("*")
            .ilike("nombre", f"%{nombre_busqueda}%")
            .eq("estado", "activo")
            .order("dias_mora", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            deudor = res.data[0]
            log.info(
                f"Deudor encontrado en BD: {deudor['nombre']} | "
                f"deuda=${deudor['deuda_actual']:,.0f} | mora={deudor['dias_mora']}d"
            )
            return deudor
        else:
            log.warning(
                f"'{nombre_busqueda}' no encontrado en clientes_recuperacion. "
                "Usando registro demo para simulacion."
            )
            demo = DEMO_JUAN_PEREZ.copy()
            demo["_es_demo"] = True
            return demo

    except Exception as e:
        log.error(f"Error consultando BD: {e} — usando demo.")
        return DEMO_JUAN_PEREZ.copy()


# ══════════════════════════════════════════════════════════════════════════════
# 3. CALCULADORA FINANCIERA
# ══════════════════════════════════════════════════════════════════════════════

def calcular_quita_maxima(dias_mora: int) -> int:
    """Retorna el % máximo de quita según los días de mora."""
    for min_d, max_d, pct in TRAMOS_QUITA:
        if min_d <= dias_mora <= max_d:
            return pct
    return 50


def analisis_financiero(deudor: dict) -> dict:
    """
    Calcula todos los valores financieros del caso:
    intereses, quita, monto final y comisión del agente.
    """
    deuda        = float(deudor.get("deuda_actual", 0))
    dias_mora    = int(deudor.get("dias_mora", 0))
    tasa         = float(deudor.get("tasa_interes_diaria", TASA_INTERES_DIARIA))

    # Intereses por mora (interés simple)
    intereses    = round(deuda * tasa * dias_mora, 2)
    total_bruto  = round(deuda + intereses, 2)

    # Quita
    quita_pct    = calcular_quita_maxima(dias_mora)
    quita_monto  = round(total_bruto * quita_pct / 100, 2)
    monto_final  = round(total_bruto - quita_monto, 2)

    # Comisión 20% sobre lo que se recupera efectivamente
    comision_pct    = COMISION_PCT
    comision_monto  = round(monto_final * comision_pct / 100, 2)
    neto_empresa    = round(monto_final - comision_monto, 2)

    return {
        "deuda_original":    deuda,
        "dias_mora":         dias_mora,
        "tasa_diaria_pct":   tasa * 100,
        "intereses":         intereses,
        "total_bruto":       total_bruto,
        "quita_pct":         quita_pct,
        "quita_monto":       quita_monto,
        "monto_final":       monto_final,
        "ahorro_deudor":     quita_monto,
        "comision_pct":      comision_pct,
        "comision_monto":    comision_monto,
        "neto_empresa":      neto_empresa,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. GENERADOR DE MENSAJE — EMPATÍA TÁCTICA (Chris Voss)
# ══════════════════════════════════════════════════════════════════════════════
#
# Las 5 técnicas de Voss aplicadas a cobranza:
#   A. Accusation Audit   — nombrar las objeciones ANTES de que las digan.
#   B. Labeling           — "Parece que..." / "Da la impresión de que..."
#   C. Calibrated Question— pregunta abierta que invita a hablar, no a decir "sí/no".
#   D. Late Night FM DJ   — tono calmado, pausado, empático. Sin presión.
#   E. Minimal Encouragers + Mirroring — escucha activa implícita en el texto.
# ══════════════════════════════════════════════════════════════════════════════

def generar_mensaje_voss(deudor: dict, financiero: dict) -> str:
    """
    Genera un mensaje de cobranza WhatsApp usando Empatía Táctica de Chris Voss.
    El tono es de aliado, no de cobrador agresivo.
    """
    nombre_corto  = deudor["nombre"].split()[0].title()
    dias          = financiero["dias_mora"]
    deuda_fmt     = f"${financiero['deuda_original']:,.0f}"
    total_fmt     = f"${financiero['total_bruto']:,.0f}"
    monto_fmt     = f"${financiero['monto_final']:,.0f}"
    ahorro_fmt    = f"${financiero['ahorro_deudor']:,.0f}"
    quita_pct     = int(financiero["quita_pct"])

    # ── Selección dinámica del párrafo de empatía según antigüedad ────────────
    if dias <= 60:
        apertura_empatia = (
            f"Sé que a veces los tiempos se complican y una cuenta "
            f"pendiente puede generar estrés. Lo entiendo perfectamente."
        )
        label_emocional = (
            "Parece que simplemente no hemos encontrado el momento "
            "adecuado para hablar de esto."
        )
    elif dias <= 180:
        apertura_empatia = (
            f"Llevas un tiempo cargando con esto y es probable que no haya "
            f"sido fácil. Eso tiene sentido."
        )
        label_emocional = (
            "Da la impresión de que la situación no ha sido la mejor "
            "y quizás sentiste que no había salida."
        )
    else:
        apertura_empatia = (
            f"Han pasado {dias} días y sé que cuando algo se arrastra tanto "
            f"es porque las circunstancias no han ayudado. Lo valoro y no vengo a juzgar."
        )
        label_emocional = (
            "Parece que lo que más necesitas en este momento "
            "es una salida real, sin presiones."
        )

    # ── Accusation Audit: nombrar las objeciones antes de que las digan ───────
    accusation_audit = (
        "Quizás piensas que esto es otra llamada de cobro más, "
        "o que lo que te voy a pedir está fuera de tu alcance. "
        "Es completamente válido pensarlo."
    )

    # ── Oferta de quita (solo si aplica) ──────────────────────────────────────
    if quita_pct == 0:
        bloque_oferta = (
            f"Tu saldo actual es de *{total_fmt}*. "
            f"Podemos diseñar juntos un plan de pagos que se ajuste a tu realidad — "
            f"sin intereses adicionales si llegamos a un acuerdo esta semana."
        )
    else:
        bloque_oferta = (
            f"Revisamos tu caso y tenemos *una propuesta especial* para ti:\n\n"
            f"   Deuda + intereses:  {total_fmt}\n"
            f"   Descuento especial: -{quita_pct}% ({ahorro_fmt} que no pagas)\n"
            f"   *Solo pagas:        {monto_fmt}*\n\n"
            f"Esto es un acuerdo directo, sin más trámites ni intermediarios."
        )

    # ── Calibrated Question (abre el diálogo sin presionar) ───────────────────
    calibrated_q = (
        "¿Qué necesitarías para que esto fuera posible para ti?"
    )

    # ── Ensamblado final ───────────────────────────────────────────────────────
    parrafos = [
        f"Hola {nombre_corto}, soy *{AGENTE_NOMBRE}* de *{EMPRESA_NOMBRE}* \U0001f91d",
        apertura_empatia.strip(),
        label_emocional.strip(),
        accusation_audit.strip(),
        "Lo que s\u00ed puedo decirte es esto:",
        bloque_oferta.strip(),
        calibrated_q.strip(),
        "Estoy aqu\u00ed para escucharte, no para presionarte. "
        "Resp\u00f3ndeme cuando puedas y encontramos la forma juntos.",
    ]
    mensaje = "\n\n".join(parrafos)
    return mensaje


# ══════════════════════════════════════════════════════════════════════════════
# 5. ENVÍO POR WHATSAPP
# ══════════════════════════════════════════════════════════════════════════════

def _normalizar_telefono(telefono: str) -> str:
    """Normaliza a formato internacional colombiano sin '+'."""
    digitos = "".join(c for c in telefono if c.isdigit())
    if digitos.startswith("57") and len(digitos) == 12:
        return digitos
    if len(digitos) == 10 and digitos.startswith("3"):
        return "57" + digitos
    if len(digitos) == 11 and digitos.startswith("0"):
        return "57" + digitos[1:]
    return digitos


def enviar_whatsapp(telefono: str, mensaje: str, log: logging.Logger, dry_run: bool = False) -> dict:
    """
    Intenta enviar el mensaje por:
      1. Evolution API  (si EVOLUTION_API_URL está configurado)
      2. Meta Cloud API (si WHATSAPP_TOKEN está configurado)
      3. Mock           (muestra en terminal — siempre disponible)
    """
    telefono_norm = _normalizar_telefono(telefono)

    if dry_run:
        log.info(f"[DRY-RUN] Mensaje NO enviado (simulacion). Destino: {telefono_norm}")
        return {"enviado": False, "proveedor": "dry-run", "telefono": telefono_norm}

    # ── A. Evolution API ──────────────────────────────────────────────────────
    ev_url  = os.environ.get("EVOLUTION_API_URL", "").rstrip("/")
    ev_key  = os.environ.get("EVOLUTION_API_KEY", "")
    ev_inst = os.environ.get("EVOLUTION_INSTANCE", "super_vendedor")

    if ev_url and ev_key:
        endpoint = f"{ev_url}/message/sendText/{ev_inst}"
        headers  = {"apikey": ev_key, "Content-Type": "application/json"}
        payload  = {"number": telefono_norm, "text": mensaje, "delay": 1500}
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                log.info(f"Enviado via Evolution API a {telefono_norm}")
                return {
                    "enviado":      True,
                    "proveedor":    "evolution",
                    "telefono":     telefono_norm,
                    "respuesta_api": resp.json(),
                }
        except httpx.HTTPStatusError as e:
            log.warning(f"Evolution API error {e.response.status_code} — intentando siguiente proveedor.")
        except Exception as e:
            log.warning(f"Evolution API no disponible: {e} — intentando siguiente proveedor.")

    # ── B. Meta WhatsApp Cloud API ────────────────────────────────────────────
    meta_token    = os.environ.get("WHATSAPP_TOKEN", "")
    meta_phone_id = os.environ.get("WHATSAPP_PHONE_ID", "")

    if meta_token and meta_phone_id:
        endpoint = f"https://graph.facebook.com/v19.0/{meta_phone_id}/messages"
        headers  = {
            "Authorization": f"Bearer {meta_token}",
            "Content-Type":  "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to":   telefono_norm,
            "type": "text",
            "text": {"body": mensaje},
        }
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                log.info(f"Enviado via Meta Cloud API a {telefono_norm}")
                return {
                    "enviado":      True,
                    "proveedor":    "meta",
                    "telefono":     telefono_norm,
                    "respuesta_api": resp.json(),
                }
        except Exception as e:
            log.warning(f"Meta API no disponible: {e} — usando Mock.")

    # ── C. Mock (siempre funciona) ────────────────────────────────────────────
    log.info("Sin proveedores configurados — activando MOCK (no se envía mensaje real).")
    return {
        "enviado":   True,
        "proveedor": "mock",
        "telefono":  telefono_norm,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. REGISTRO EN BITÁCORA
# ══════════════════════════════════════════════════════════════════════════════

def registrar_en_bitacora(
    db,
    deudor: dict,
    financiero: dict,
    mensaje: str,
    resultado_envio: dict,
    log: logging.Logger,
) -> str | None:
    """Inserta la acción en bitacora_centinela."""
    if db is None or deudor.get("_es_demo"):
        log.info("Bitacora: registro omitido (sin DB o modo demo).")
        return None

    fila = {
        "tenant_id":       deudor.get("tenant_id", "ednetpro_demo"),
        "cliente_id":      deudor.get("id"),
        "telefono":        deudor.get("telefono", ""),
        "accion":          "whatsapp_enviado",
        "agente_ia":       "centinela_atacar_cartera",
        "descripcion":     f"Empatia Tactica Voss | quita={financiero['quita_pct']}%",
        "monto_propuesto": financiero["monto_final"],
        "quita_ofrecida":  financiero["quita_pct"],
        "resultado":       "exitoso" if resultado_envio.get("enviado") else "fallido",
        "resumen_ia":      f"Mensaje generado con tecnica Voss. Proveedor: {resultado_envio.get('proveedor')}",
        "transcripcion":   mensaje,
        "metadata": {
            "proveedor":         resultado_envio.get("proveedor"),
            "telefono_destino":  resultado_envio.get("telefono"),
            "financiero":        financiero,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        res = db.table("bitacora_centinela").insert(fila).execute()
        bit_id = res.data[0]["id"] if res.data else None
        log.info(f"Bitacora registrada. ID: {bit_id}")
        return bit_id
    except Exception as e:
        log.error(f"Error guardando en bitacora: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 7. PANEL DE RESULTADO EN TERMINAL
# ══════════════════════════════════════════════════════════════════════════════

VERDE    = "\033[92m"
AMARILLO = "\033[93m"
ROJO     = "\033[91m"
CYAN     = "\033[96m"
MAGENTA  = "\033[95m"
BOLD     = "\033[1m"
DIM      = "\033[2m"
RESET    = "\033[0m"
LINEA    = f"{DIM}{'═' * 64}{RESET}"
LINEA_S  = f"{DIM}{'─' * 64}{RESET}"


def imprimir_panel_resultado(
    deudor:          dict,
    financiero:      dict,
    mensaje:         str,
    resultado_envio: dict,
    bitacora_id:     str | None,
) -> None:
    """
    Imprime el resumen ejecutivo completo en la terminal:
    datos del deudor, análisis financiero, comisión y estado del envío.
    """
    es_demo  = deudor.get("_es_demo", False)
    enviado  = resultado_envio.get("enviado", False)
    proveedor = resultado_envio.get("proveedor", "?")

    print(f"\n{LINEA}")
    print(f"{BOLD}{CYAN}   CENTINELA — ATAQUE DE CARTERA COMPLETADO{RESET}")
    if es_demo:
        print(f"   {AMARILLO}[MODO DEMO — Juan Perez no encontrado en BD]{RESET}")
    print(f"{LINEA}")

    # ── Ficha del deudor ──────────────────────────────────────────────────────
    print(f"\n{BOLD}  DEUDOR{RESET}")
    print(f"{LINEA_S}")
    print(f"  Nombre      : {BOLD}{deudor['nombre']}{RESET}")
    print(f"  Telefono    : {deudor.get('telefono', 'N/A')}")
    print(f"  Cedula      : {deudor.get('cedula', 'N/A')}")
    print(f"  Canal       : {deudor.get('canal_contacto', 'whatsapp').upper()}")
    print(f"  Estado BD   : {deudor.get('estado', 'activo').upper()}")

    # ── Análisis financiero ───────────────────────────────────────────────────
    print(f"\n{BOLD}  ANALISIS FINANCIERO{RESET}")
    print(f"{LINEA_S}")
    print(f"  Deuda original    : {BOLD}${financiero['deuda_original']:>14,.0f}{RESET}")
    print(f"  Dias de mora      : {BOLD}{financiero['dias_mora']:>14} dias{RESET}")
    print(
        f"  Tasa interes      : "
        f"{AMARILLO}{financiero['tasa_diaria_pct']:.2f}% diario "
        f"({financiero['tasa_diaria_pct']*365:.1f}% anual){RESET}"
    )
    print(f"  Intereses mora    : {ROJO}+${financiero['intereses']:>13,.0f}{RESET}")
    print(f"  Total bruto       :  ${financiero['total_bruto']:>13,.0f}")
    print(f"{LINEA_S}")

    if financiero["quita_pct"] > 0:
        print(
            f"  Quita aplicada    : {VERDE}-{financiero['quita_pct']}% "
            f"(-${financiero['quita_monto']:,.0f}){RESET}"
        )
    else:
        print(f"  Quita aplicada    : {DIM}0% (deuda reciente){RESET}")

    print(f"  {BOLD}MONTO A COBRAR    : {VERDE}${financiero['monto_final']:>13,.0f}{RESET}")
    print(f"  Ahorro al deudor  : {CYAN}${financiero['ahorro_deudor']:>13,.0f}{RESET}")

    # ── Comisión del agente ───────────────────────────────────────────────────
    print(f"\n{BOLD}  COMISION DEL AGENTE ({COMISION_PCT}%){RESET}")
    print(f"{LINEA_S}")
    print(f"  Monto recuperado  :  ${financiero['monto_final']:>13,.0f}")
    print(
        f"  Comision {COMISION_PCT}%       : "
        f"{MAGENTA}{BOLD}+${financiero['comision_monto']:>13,.0f}{RESET}"
    )
    print(
        f"  Neto empresa      :  "
        f"{VERDE}${financiero['neto_empresa']:>13,.0f}{RESET}"
    )

    # ── Estado del envío ──────────────────────────────────────────────────────
    print(f"\n{BOLD}  WHATSAPP{RESET}")
    print(f"{LINEA_S}")
    estado_envio = f"{VERDE}ENVIADO{RESET}" if enviado else f"{ROJO}NO ENVIADO{RESET}"
    print(f"  Estado     : {estado_envio}")
    print(f"  Proveedor  : {proveedor.upper()}")
    print(f"  Destino    : {resultado_envio.get('telefono', 'N/A')}")
    if bitacora_id:
        print(f"  Bitacora   : {DIM}{bitacora_id}{RESET}")
    else:
        print(f"  Bitacora   : {DIM}(modo demo — no registrado){RESET}")

    # ── Técnica utilizada ─────────────────────────────────────────────────────
    print(f"\n{BOLD}  TECNICA VOSS APLICADA{RESET}")
    print(f"{LINEA_S}")
    tecnicas = [
        ("Accusation Audit",    "Objeciones nombradas antes que el deudor las diga"),
        ("Labeling",            "Estado emocional del deudor etiquetado con empatia"),
        ("Calibrated Question", "Pregunta abierta que abre el dialogo sin presion"),
        ("Late Night FM DJ",    "Tono calmado, nunca agresivo ni urgente"),
        ("Sin BATNA agresivo",  "No se amenaza — se ofrece colaboracion"),
    ]
    for tecnica, descripcion in tecnicas:
        print(f"  {CYAN}{tecnica:<22}{RESET} {DIM}{descripcion}{RESET}")

    # ── Mensaje generado ──────────────────────────────────────────────────────
    print(f"\n{BOLD}  MENSAJE WHATSAPP GENERADO{RESET}")
    print(f"{LINEA_S}")
    for linea in mensaje.splitlines():
        print(f"  {linea}")

    print(f"\n{LINEA}")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"  {DIM}Ejecutado: {ts} | Script: atacar_cartera.py | v1.0{RESET}")
    print(f"{LINEA}\n")


# ══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Centinela — Ataque de cartera con Empatia Tactica (Voss)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--nombre",
        default="Juan Perez",
        help="Nombre del deudor a buscar en BD (default: 'Juan Perez')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera y muestra el mensaje pero NO lo envía por WhatsApp",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Activa logs DEBUG detallados",
    )
    args = parser.parse_args()

    log = _setup_logging(verbose=args.verbose)

    print(f"\n{LINEA}")
    print(f"{BOLD}{MAGENTA}   CENTINELA  |  ED NET PRO  |  ATAQUE DE CARTERA{RESET}")
    print(f"   {DIM}Tecnica: Empatia Tactica — Chris Voss{RESET}")
    print(f"{LINEA}\n")

    log.info(f"Iniciando ataque de cartera para: '{args.nombre}'")
    if args.dry_run:
        log.info("Modo DRY-RUN activo — el mensaje no sera enviado.")

    # ── 1. Conexion ────────────────────────────────────────────────────────────
    db = conectar_supabase(log)

    # ── 2. Extraccion del deudor ───────────────────────────────────────────────
    log.info(f"Buscando deudor en clientes_recuperacion: '{args.nombre}'...")
    deudor = extraer_deudor(db, args.nombre, log)

    # ── 3. Análisis financiero ─────────────────────────────────────────────────
    financiero = analisis_financiero(deudor)
    log.info(
        f"Financiero calculado: deuda=${financiero['deuda_original']:,.0f} | "
        f"mora={financiero['dias_mora']}d | "
        f"quita={financiero['quita_pct']}% | "
        f"cobrar=${financiero['monto_final']:,.0f} | "
        f"comision={COMISION_PCT}%=${financiero['comision_monto']:,.0f}"
    )

    # ── 4. Generación del mensaje Voss ─────────────────────────────────────────
    log.info("Generando mensaje con tecnica Empatia Tactica (Voss)...")
    mensaje = generar_mensaje_voss(deudor, financiero)

    # ── 5. Envío ───────────────────────────────────────────────────────────────
    telefono = deudor.get("telefono", "")
    log.info(f"Enviando WhatsApp a {telefono}...")
    resultado_envio = enviar_whatsapp(telefono, mensaje, log, dry_run=args.dry_run)

    # ── 6. Bitácora ────────────────────────────────────────────────────────────
    bitacora_id = registrar_en_bitacora(db, deudor, financiero, mensaje, resultado_envio, log)

    # ── 7. Panel de resultado ──────────────────────────────────────────────────
    imprimir_panel_resultado(deudor, financiero, mensaje, resultado_envio, bitacora_id)

    # Código de salida
    sys.exit(0 if resultado_envio.get("enviado") else 1)


if __name__ == "__main__":
    main()
