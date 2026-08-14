# app/routers/hunter_router.py — Single Tenant
"""
Endpoints del motor de prospección Hunter.
Integra ShakaQuantumProspector vía ProspectingEngine (probability_score por lead).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.hunter import ProspectingEngine
from app.config import settings
from app.agents.shaka_quantum_prospector import ShakaQuantumProspector
from app.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])
OWNER_ID = settings.OWNER_ID


class CampanaRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    ciudad: str = Field(..., min_length=2, max_length=100)
    max_results: int = Field(default=20, ge=1, le=60)


class ShakaScoreRequest(BaseModel):
    nombre: str = Field(..., min_length=2)
    categoria: str = Field(default="")
    ciudad: str = Field(default="")
    lead_score: int = Field(default=5, ge=1, le=10)


@router.post("/campana", summary="Ejecutar campaña de prospección")
async def ejecutar_campana(body: CampanaRequest):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        return await engine.ejecutar_campana(
            query=body.query,
            ciudad=body.ciudad,
            max_results=body.max_results,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en campaña: {e}")


@router.get("/leads-calientes", summary="Leads con score alto (>=7)")
def leads_calientes(
    score_minimo: int = Query(default=7, ge=1, le=10),
    limit: int = Query(default=50, ge=1, le=500),
):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        return engine.obtener_leads_calientes(score_minimo=score_minimo, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prospectos", summary="Listar todos los prospectos")
def listar_prospectos(
    ciudad: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        return engine.obtener_prospectos(ciudad=ciudad, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/shaka/score", summary="Evaluar prospecto con Shaka")
def shaka_score_preview(body: ShakaScoreRequest):
    shaka = ShakaQuantumProspector()
    prospecto = {
        "nombre_negocio": body.nombre,
        "categoria": body.categoria,
        "ciudad": body.ciudad,
        "rating": 4.0,
        "total_reviews": 10,
        "telefono": "",
        "sitio_web": "",
        "lugar_id": body.nombre,
    }
    return shaka.score_hunter_lead(prospecto, body.lead_score)


@router.patch("/prospectos/{prospecto_id}/procesado", summary="Marcar prospecto procesado")
def marcar_procesado(prospecto_id: str):
    try:
        engine = ProspectingEngine(tenant_id=OWNER_ID)
        ok = engine.marcar_prospecto_procesado(prospecto_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Prospecto no encontrado")
        return {"status": "procesado", "prospecto_id": prospecto_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
