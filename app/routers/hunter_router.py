# app/routers/hunter_router.py — Single Tenant
"""
Endpoints del motor de prospección Hunter.
Sin multi-tenant: opera siempre bajo OWNER_ID (Edwuar).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.hunter import ProspectingEngine
from app.config import settings

router   = APIRouter()
OWNER_ID = settings.OWNER_ID


class CampanaRequest(BaseModel):
    query:       str = Field(..., min_length=2, max_length=200, description="Tipo de negocio a buscar")
    ciudad:      str = Field(..., min_length=2, max_length=100, description="Ciudad donde buscar")
    max_results: int = Field(default=20, ge=1, le=60,          description="Máximo de resultados")


@router.post("/campana", summary="Ejecutar campaña de prospección en Google Maps")
async def ejecutar_campana(body: CampanaRequest):
    """Busca negocios en Google Maps, los puntúa (1-10) y los guarda en Supabase."""
    try:
        engine    = ProspectingEngine(tenant_id=OWNER_ID)
        resultado = await engine.ejecutar_campana(
            query       = body.query,
            ciudad      = body.ciudad,
            max_results = body.max_results,
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en campaña: {e}")


@router.get("/leads-calientes", summary="Leads con score alto (>=7)")
def leads_calientes(
    score_minimo: int = Query(default=7, ge=1, le=10),
    limit:        int = Query(default=50, ge=1, le=500),
):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        return engine.obtener_leads_calientes(score_minimo=score_minimo, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prospectos", summary="Listar todos los prospectos")
def listar_prospectos(
    ciudad: str | None = Query(default=None),
    limit:  int        = Query(default=100, ge=1, le=500),
):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        return engine.obtener_prospectos(ciudad=ciudad, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/prospectos/{prospecto_id}/procesado", summary="Marcar prospecto como procesado")
def marcar_procesado(prospecto_id: str):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        ok     = engine.marcar_prospecto_procesado(prospecto_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        return {"status": "procesado", "prospecto_id": prospecto_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
