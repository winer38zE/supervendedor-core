"""
app/services/centinela.py
────────────────────────────────────────────────────────────────────────────────
Módulo Centinela — Motor de Recuperación de Cartera

Responsabilidades:
  - CalculadoraQuitas: determina el % de descuento según antigüedad de deuda.
  - CentinelaService: CRUD sobre clientes_recuperacion + bitacora_centinela.
  - calcular_intereses(): proyecta intereses según días de mora y tasa diaria.

Tablas que maneja:
  - public.clientes_recuperacion
  - public.bitacora_centinela

Variables de entorno requeridas:
  SUPABASE_URL  → URL del proyecto
  SUPABASE_KEY  → service_role key (para bypass de RLS)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.database.supabase_client import get_client

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CALCULADORA DE QUITAS
# Regla de negocio: a mayor antigüedad de la deuda, mayor descuento posible.
# El agente IA usa estos valores como techo — puede negociar por debajo.
# ══════════════════════════════════════════════════════════════════════════════

# Tabla de tramos: (dias_mora_min, dias_mora_max_inclusive, quita_max_%)
_TRAMOS_QUITA = [
    (0,    30,   0),   # Deuda nueva: sin descuento
    (31,   60,   5),   # 1-2 meses: 5%
    (61,   90,  10),   # 2-3 meses: 10%
    (91,  180,  20),   # 3-6 meses: 20%
    (181, 365,  30),   # 6-12 meses: 30%
    (366, 730,  40),   # 1-2 años: 40%
    (731, 9999, 50),   # Más de 2 años: 50% (máximo permitido)
]


class CalculadoraQuitas:
    """
    Calcula el descuento máximo aplicable y el monto final a cobrar,
    en función de los días de mora de la deuda.

    Uso:
        resultado = CalculadoraQuitas.calcular(deuda=500_000, dias_mora=120)
        # → {'quita_pct': 20, 'quita_monto': 100000, 'monto_final': 400000, ...}
    """

    @staticmethod
    def quita_maxima(dias_mora: int) -> int:
        """Retorna el porcentaje máximo de quita permitido para esos días de mora."""
        for min_d, max_d, pct in _TRAMOS_QUITA:
            if min_d <= dias_mora <= max_d:
                return pct
        return 50  # fallback: máximo absoluto

    @staticmethod
    def calcular(
        deuda: float,
        dias_mora: int,
        intereses: float = 0.0,
        quita_pct: Optional[float] = None,
    ) -> dict:
        """
        Calcula la propuesta de quita para un deudor.

        Args:
            deuda:      Monto de la deuda actual (sin intereses).
            dias_mora:  Días de mora a la fecha.
            intereses:  Intereses acumulados (opcional, default 0).
            quita_pct:  Porcentaje de quita a aplicar. Si es None, usa el máximo
                        permitido según los días de mora.

        Returns:
            {
                "dias_mora":          int,
                "deuda_original":     float,
                "intereses":          float,
                "total_sin_quita":    float,
                "quita_pct_max":      int,    ← techo según tabla de tramos
                "quita_pct_aplicado": float,  ← el que se usó (≤ quita_pct_max)
                "quita_monto":        float,
                "monto_final":        float,
                "ahorro_deudor":      float,
                "mensaje_agente":     str,    ← texto listo para decirle al deudor
            }
        """
        dias_mora   = max(0, int(dias_mora))
        deuda       = max(0.0, float(deuda))
        intereses   = max(0.0, float(intereses))
        total       = deuda + intereses
        quita_max   = CalculadoraQuitas.quita_maxima(dias_mora)

        # Aplicar la quita solicitada, pero nunca superar el techo
        if quita_pct is None:
            quita_pct = quita_max
        else:
            quita_pct = min(float(quita_pct), float(quita_max))

        quita_monto  = round(total * quita_pct / 100, 2)
        monto_final  = round(total - quita_monto, 2)
        ahorro       = quita_monto

        # Mensaje listo para el agente IA
        if quita_pct == 0:
            mensaje = (
                f"Su deuda es de ${total:,.0f}. "
                "Por ser reciente no aplica descuento, pero podemos acordar un plan de pagos."
            )
        else:
            mensaje = (
                f"Tenemos buenas noticias: por la antigüedad de su deuda podemos ofrecerle "
                f"un descuento del {quita_pct:.0f}%. "
                f"Su deuda total es ${total:,.0f} pero si la cancela hoy, "
                f"solo paga ${monto_final:,.0f}. "
                f"Usted se ahorra ${ahorro:,.0f}. ¿Le interesa?"
            )

        return {
            "dias_mora":           dias_mora,
            "deuda_original":      deuda,
            "intereses":           intereses,
            "total_sin_quita":     round(total, 2),
            "quita_pct_max":       quita_max,
            "quita_pct_aplicado":  quita_pct,
            "quita_monto":         quita_monto,
            "monto_final":         monto_final,
            "ahorro_deudor":       ahorro,
            "mensaje_agente":      mensaje,
        }

    @staticmethod
    def tabla_referencia() -> list[dict]:
        """Retorna la tabla completa de tramos para referencia del agente."""
        return [
            {"dias_min": mn, "dias_max": mx, "quita_max_pct": pct}
            for mn, mx, pct in _TRAMOS_QUITA
        ]


# ══════════════════════════════════════════════════════════════════════════════
# 2. CÁLCULO DE INTERESES
# ══════════════════════════════════════════════════════════════════════════════

def calcular_intereses(
    deuda_original: float,
    dias_mora: int,
    tasa_diaria: float = 0.001,
) -> float:
    """
    Calcula intereses por mora usando interés simple.

    Fórmula: intereses = deuda_original × tasa_diaria × días_mora

    Args:
        deuda_original: Deuda base sin intereses.
        dias_mora:      Días transcurridos desde el vencimiento.
        tasa_diaria:    Tasa de interés diaria (default: 0.1% = 0.001).

    Returns:
        Monto de intereses acumulados (float, redondeado a 2 decimales).
    """
    return round(float(deuda_original) * float(tasa_diaria) * max(0, int(dias_mora)), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 3. CRUD — clientes_recuperacion
# ══════════════════════════════════════════════════════════════════════════════

class CentinelaService:
    """Operaciones sobre las tablas de recuperación de cartera."""

    # ── Clientes ─────────────────────────────────────────────────────────────

    @staticmethod
    def registrar_cliente(
        tenant_id:          str,
        nombre:             str,
        telefono:           str,
        deuda_original:     float,
        dias_mora:          int,
        tasa_interes_diaria: float = 0.001,
        cedula:             str   = "",
        canal_contacto:     str   = "whatsapp",
        fecha_vencimiento:  str   = None,
        notas:              str   = "",
        metadata:           dict  = None,
    ) -> Optional[dict]:
        """
        Inserta o actualiza un deudor en clientes_recuperacion.
        Si el par (tenant_id, telefono) ya existe, actualiza la deuda y mora.
        """
        db = get_client()
        if not db:
            logger.error("[Centinela] Sin cliente DB")
            return None

        intereses = calcular_intereses(deuda_original, dias_mora, tasa_interes_diaria)
        calculo   = CalculadoraQuitas.calcular(deuda_original, dias_mora, intereses)

        fila = {
            "tenant_id":            tenant_id,
            "nombre":               nombre or "",
            "telefono":             telefono or "",
            "cedula":               cedula or "",
            "deuda_original":       round(float(deuda_original), 2),
            "deuda_actual":         round(float(deuda_original), 2),
            "dias_mora":            max(0, int(dias_mora)),
            "tasa_interes_diaria":  float(tasa_interes_diaria),
            "intereses_acumulados": intereses,
            "quita_porcentaje":     calculo["quita_pct_max"],
            "quita_monto":          calculo["quita_monto"],
            "canal_contacto":       canal_contacto,
            "notas":                notas or "",
            "metadata":             metadata or {},
            "updated_at":           datetime.now(timezone.utc).isoformat(),
        }
        if fecha_vencimiento:
            fila["fecha_vencimiento"] = fecha_vencimiento

        try:
            res = (
                db.table("clientes_recuperacion")
                .upsert(fila, on_conflict="tenant_id,telefono")
                .execute()
            )
            data = res.data[0] if res.data else None
            logger.info(
                f"[Centinela] Cliente registrado: {nombre} | deuda={deuda_original} | "
                f"mora={dias_mora}d | quita={calculo['quita_pct_max']}%"
            )
            return data
        except Exception as e:
            logger.error(f"[Centinela] Error registrando cliente: {e}")
            return None

    @staticmethod
    def cargar_lista_deudores(tenant_id: str, deudores: list[dict]) -> dict:
        """
        Carga masiva de deudores. Cada elemento del listado debe tener:
          nombre, telefono, deuda_original, dias_mora
          (campos opcionales: cedula, tasa_interes_diaria, notas, metadata)

        Returns:
            {"exitosos": int, "fallidos": int, "errores": list}
        """
        exitosos, fallidos, errores = 0, 0, []

        for d in deudores:
            try:
                resultado = CentinelaService.registrar_cliente(
                    tenant_id           = tenant_id,
                    nombre              = d.get("nombre", ""),
                    telefono            = d.get("telefono", ""),
                    deuda_original      = float(d.get("deuda_original", 0)),
                    dias_mora           = int(d.get("dias_mora", 0)),
                    tasa_interes_diaria = float(d.get("tasa_interes_diaria", 0.001)),
                    cedula              = d.get("cedula", ""),
                    canal_contacto      = d.get("canal_contacto", "whatsapp"),
                    notas               = d.get("notas", ""),
                    metadata            = d.get("metadata", {}),
                )
                if resultado:
                    exitosos += 1
                else:
                    fallidos += 1
                    errores.append({"telefono": d.get("telefono"), "error": "DB no retornó datos"})
            except Exception as e:
                fallidos += 1
                errores.append({"telefono": d.get("telefono"), "error": str(e)})

        logger.info(f"[Centinela] Carga masiva tenant={tenant_id}: {exitosos} ok, {fallidos} falló")
        return {"exitosos": exitosos, "fallidos": fallidos, "errores": errores}

    @staticmethod
    def obtener_clientes(
        tenant_id: str,
        estado: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Lista deudores de un tenant, opcionalmente filtrados por estado."""
        db = get_client()
        if not db:
            return []
        try:
            q = db.table("clientes_recuperacion").select("*").eq("tenant_id", tenant_id)
            if estado:
                q = q.eq("estado", estado)
            res = q.order("dias_mora", desc=True).range(offset, offset + limit - 1).execute()
            return res.data or []
        except Exception as e:
            logger.error(f"[Centinela] Error listando clientes: {e}")
            return []

    @staticmethod
    def actualizar_estado(
        cliente_id: str,
        nuevo_estado: str,
        quita_pct: float = None,
        quita_monto: float = None,
    ) -> bool:
        """Actualiza el estado de un deudor (y opcionalmente la quita acordada)."""
        db = get_client()
        if not db:
            return False
        estados_validos = {"activo", "negociando", "acuerdo", "pagado", "incobrable"}
        if nuevo_estado not in estados_validos:
            logger.warning(f"[Centinela] Estado inválido: {nuevo_estado}")
            return False
        fila = {
            "estado":     nuevo_estado,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if quita_pct is not None:
            fila["quita_porcentaje"] = float(quita_pct)
        if quita_monto is not None:
            fila["quita_monto"] = float(quita_monto)
        try:
            db.table("clientes_recuperacion").update(fila).eq("id", cliente_id).execute()
            return True
        except Exception as e:
            logger.error(f"[Centinela] Error actualizando estado: {e}")
            return False

    # ── Bitácora ──────────────────────────────────────────────────────────────

    @staticmethod
    def registrar_accion(
        tenant_id:       str,
        accion:          str,
        telefono:        str        = "",
        cliente_id:      str        = None,
        descripcion:     str        = "",
        monto_propuesto: float      = 0,
        monto_acordado:  float      = 0,
        quita_ofrecida:  float      = 0,
        resultado:       str        = "pendiente",
        transcripcion:   str        = "",
        resumen_ia:      str        = "",
        duracion_seg:    int        = 0,
        agente_ia:       str        = "centinela",
        metadata:        dict       = None,
    ) -> Optional[str]:
        """
        Inserta un evento en bitacora_centinela.
        Cada llamada, mensaje o acuerdo genera una fila inmutable.

        Returns:
            UUID del registro o None si falló.
        """
        db = get_client()
        if not db:
            logger.warning(f"[Bitácora] Sin DB — acción '{accion}' no guardada.")
            return None

        acciones_validas = {
            "llamada_iniciada", "llamada_completada", "whatsapp_enviado",
            "propuesta_quita", "acuerdo_pago", "pago_parcial",
            "pago_total", "no_contesto", "promesa_pago", "incobrable_marcado",
        }
        if accion not in acciones_validas:
            logger.warning(f"[Bitácora] Acción desconocida: {accion}")
            accion = "llamada_completada"

        resultados_validos = {"exitoso", "fallido", "pendiente", "sin_respuesta"}
        if resultado not in resultados_validos:
            resultado = "pendiente"

        fila = {
            "tenant_id":       tenant_id,
            "cliente_id":      cliente_id,
            "telefono":        telefono or "",
            "accion":          accion,
            "agente_ia":       agente_ia or "centinela",
            "descripcion":     descripcion or "",
            "monto_propuesto": round(float(monto_propuesto or 0), 2),
            "monto_acordado":  round(float(monto_acordado or 0), 2),
            "quita_ofrecida":  round(float(quita_ofrecida or 0), 2),
            "resultado":       resultado,
            "transcripcion":   transcripcion or "",
            "resumen_ia":      resumen_ia or "",
            "duracion_seg":    max(0, int(duracion_seg or 0)),
            "metadata":        metadata or {},
            "created_at":      datetime.now(timezone.utc).isoformat(),
        }

        try:
            res = db.table("bitacora_centinela").insert(fila).execute()
            bit_id = res.data[0]["id"] if res.data else None
            logger.info(
                f"[Bitácora] tenant={tenant_id} | accion={accion} | "
                f"tel={telefono} | resultado={resultado} | id={bit_id}"
            )
            return bit_id
        except Exception as e:
            logger.error(f"[Bitácora] Error en insert: {e}")
            return None

    @staticmethod
    def historial_cliente(
        tenant_id: str,
        cliente_id: str = None,
        telefono: str = None,
        limit: int = 20,
    ) -> list[dict]:
        """Retorna el historial de acciones de un deudor específico."""
        db = get_client()
        if not db:
            return []
        try:
            q = db.table("bitacora_centinela").select("*").eq("tenant_id", tenant_id)
            if cliente_id:
                q = q.eq("cliente_id", cliente_id)
            elif telefono:
                q = q.eq("telefono", telefono)
            res = q.order("created_at", desc=True).limit(limit).execute()
            return res.data or []
        except Exception as e:
            logger.error(f"[Bitácora] Error en historial: {e}")
            return []

    @staticmethod
    def resumen_cartera(tenant_id: str) -> dict:
        """Retorna estadísticas de la cartera del tenant desde la vista v_resumen_cartera."""
        db = get_client()
        if not db:
            return {}
        try:
            res = (
                db.table("v_resumen_cartera")
                .select("*")
                .eq("tenant_id", tenant_id)
                .execute()
            )
            return res.data[0] if res.data else {}
        except Exception as e:
            logger.error(f"[Centinela] Error en resumen: {e}")
            return {}
