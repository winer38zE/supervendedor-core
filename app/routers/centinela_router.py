"""
app/routers/centinela_router.py
────────────────────────────────────────────────────────────────────────────────
Router Centinela — API REST para el módulo de recuperación de cartera.

Endpoints:
  POST   /centinela/deudores/cargar          → carga masiva de deudores
  POST   /centinela/deudores                 → registra un deudor individual
  GET    /centinela/deudores                 → lista deudores del tenant
  POST   /centinela/quita/calcular           → calcula propuesta de quita (sin guardar)
  GET    /centinela/quita/tabla              → tabla de referencia de quitas
  POST   /centinela/bitacora                 → registra una acción de cobro
  GET    /centinela/bitacora/{cliente_id}    → historial de acciones de un deudor
  PUT    /centinela/deudores/{id}/estado     → actualiza estado del deudor
  GET    /centinela/resumen                  → estadísticas de la cartera
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.centinela import (
    CalculadoraQuitas,
    CentinelaService,
    calcular_intereses,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════════
# Modelos de request / response
# ══════════════════════════════════════════════════════════════════════════════

class DeudorIn(BaseModel):
    tenant_id:            str
    nombre:               str
    telefono:             str
    deuda_original:       float = Field(..., gt=0)
    dias_mora:            int   = Field(..., ge=0)
    cedula:               str   = ""
    tasa_interes_diaria:  float = Field(0.001, ge=0)
    canal_contacto:       str   = "whatsapp"
    fecha_vencimiento:    Optional[str] = None
    notas:                str   = ""
    metadata:             dict  = {}


class CargaMasivaIn(BaseModel):
    tenant_id: str
    deudores:  list[dict]   # lista de dicts con campos de DeudorIn sin tenant_id


class QuitaCalcularIn(BaseModel):
    deuda:      float = Field(..., gt=0)
    dias_mora:  int   = Field(..., ge=0)
    intereses:  float = 0.0
    quita_pct:  Optional[float] = None  # None = usar el máximo permitido


class AccionBitacoraIn(BaseModel):
    tenant_id:       str
    accion:          str
    telefono:        str   = ""
    cliente_id:      Optional[str] = None
    descripcion:     str   = ""
    monto_propuesto: float = 0
    monto_acordado:  float = 0
    quita_ofrecida:  float = 0
    resultado:       str   = "pendiente"
    transcripcion:   str   = ""
    resumen_ia:      str   = ""
    duracion_seg:    int   = 0
    agente_ia:       str   = "centinela"
    metadata:        dict  = {}


class ActualizarEstadoIn(BaseModel):
    nuevo_estado: str
    quita_pct:    Optional[float] = None
    quita_monto:  Optional[float] = None


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/deudores/cargar")
def cargar_lista_deudores(body: CargaMasivaIn):
    """Carga masiva de deudores. Inserta o actualiza por (tenant_id, telefono)."""
    if not body.deudores:
        raise HTTPException(status_code=400, detail="La lista de deudores está vacía.")
    resultado = CentinelaService.cargar_lista_deudores(body.tenant_id, body.deudores)
    return {
        "status":   "completado",
        "total":    len(body.deudores),
        **resultado,
    }


@router.post("/deudores")
def registrar_deudor(body: DeudorIn):
    """Registra o actualiza un deudor individual."""
    data = CentinelaService.registrar_cliente(
        tenant_id           = body.tenant_id,
        nombre              = body.nombre,
        telefono            = body.telefono,
        deuda_original      = body.deuda_original,
        dias_mora           = body.dias_mora,
        tasa_interes_diaria = body.tasa_interes_diaria,
        cedula              = body.cedula,
        canal_contacto      = body.canal_contacto,
        fecha_vencimiento   = body.fecha_vencimiento,
        notas               = body.notas,
        metadata            = body.metadata,
    )
    if not data:
        raise HTTPException(status_code=500, detail="Error guardando el deudor en la base de datos.")
    return {"status": "ok", "deudor": data}


@router.get("/deudores")
def listar_deudores(
    tenant_id: str = Query(..., description="ID del tenant"),
    estado:    Optional[str] = Query(None, description="Filtrar por estado"),
    limit:     int = Query(100, ge=1, le=500),
    offset:    int = Query(0, ge=0),
):
    """Lista los deudores del tenant, opcionalmente filtrados por estado."""
    clientes = CentinelaService.obtener_clientes(tenant_id, estado, limit, offset)
    return {"total": len(clientes), "deudores": clientes}


@router.post("/quita/calcular")
def calcular_quita(body: QuitaCalcularIn):
    """
    Calcula la propuesta de quita sin guardar nada en DB.
    El agente IA puede llamar esto antes de hacer una oferta al deudor.
    """
    resultado = CalculadoraQuitas.calcular(
        deuda      = body.deuda,
        dias_mora  = body.dias_mora,
        intereses  = body.intereses,
        quita_pct  = body.quita_pct,
    )
    return resultado


@router.get("/quita/tabla")
def tabla_quitas():
    """Retorna la tabla completa de tramos de quita para referencia del agente."""
    return {
        "tabla": CalculadoraQuitas.tabla_referencia(),
        "nota":  "El agente puede ofrecer hasta el quita_max_pct según los días de mora. "
                 "Siempre negociar empezando por el mínimo.",
    }


@router.post("/bitacora")
def registrar_accion(body: AccionBitacoraIn):
    """Registra una acción de cobro en la bitácora (inmutable)."""
    bit_id = CentinelaService.registrar_accion(
        tenant_id       = body.tenant_id,
        accion          = body.accion,
        telefono        = body.telefono,
        cliente_id      = body.cliente_id,
        descripcion     = body.descripcion,
        monto_propuesto = body.monto_propuesto,
        monto_acordado  = body.monto_acordado,
        quita_ofrecida  = body.quita_ofrecida,
        resultado       = body.resultado,
        transcripcion   = body.transcripcion,
        resumen_ia      = body.resumen_ia,
        duracion_seg    = body.duracion_seg,
        agente_ia       = body.agente_ia,
        metadata        = body.metadata,
    )
    if not bit_id:
        raise HTTPException(status_code=500, detail="Error guardando en bitácora.")
    return {"status": "registrado", "bitacora_id": bit_id}


@router.get("/bitacora/{cliente_id}")
def historial_deudor(
    cliente_id: str,
    tenant_id:  str = Query(...),
    limit:      int = Query(20, ge=1, le=100),
):
    """Historial de todas las acciones ejecutadas sobre un deudor."""
    historial = CentinelaService.historial_cliente(
        tenant_id  = tenant_id,
        cliente_id = cliente_id,
        limit      = limit,
    )
    return {"total": len(historial), "historial": historial}


@router.put("/deudores/{cliente_id}/estado")
def actualizar_estado(cliente_id: str, body: ActualizarEstadoIn):
    """Actualiza el estado de negociación de un deudor."""
    ok = CentinelaService.actualizar_estado(
        cliente_id   = cliente_id,
        nuevo_estado = body.nuevo_estado,
        quita_pct    = body.quita_pct,
        quita_monto  = body.quita_monto,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Estado inválido o error de DB.")
    return {"status": "actualizado", "cliente_id": cliente_id, "estado": body.nuevo_estado}


@router.get("/resumen")
def resumen_cartera(tenant_id: str = Query(..., description="ID del tenant")):
    """Estadísticas globales de la cartera del tenant."""
    resumen = CentinelaService.resumen_cartera(tenant_id)
    if not resumen:
        return {"tenant_id": tenant_id, "mensaje": "Sin datos aún — carga la primera lista de deudores."}
    return resumen
