"""
app/routers/agents_router.py
Endpoints centralizados: catálogo Nyx Bridge, followup CRM, snapshot Shein.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field

from app.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])


class FollowupRunResponse(BaseModel):
    scanned: int
    sent: int
    skipped: int
    errors: int


class ZopaRequest(BaseModel):
    q: str = Field(default="", description="Texto o nombre de producto")


class SheinScrapeRequest(BaseModel):
    save_excel: bool = Field(default=True)


@router.get("/catalog/snapshot", summary="Snapshot del catálogo Shein + ZOPA")
def catalog_snapshot():
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    return {
        "summary": bridge.get_catalog_summary(),
        "products": bridge.get_products(limit=20),
        "default_zopa": bridge.get_default_zopa(),
    }


@router.post("/catalog/refresh", summary="Recargar catálogo desde Excel/cache")
def catalog_refresh():
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    count = bridge.refresh()
    return {"status": "ok", "products_loaded": count, "summary": bridge.get_catalog_summary()}


@router.get("/catalog/zopa", summary="ZOPA dinámica (lectura, GET)")
def catalog_zopa_get(q: str = Query(default="", description="Texto o nombre de producto")):
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    zopa = bridge.get_zopa_for_message(q) if q else bridge.get_default_zopa()
    product = bridge.find_product(q) if q else bridge.get_featured_product()
    return {"zopa": zopa, "product": product}


@router.post("/catalog/zopa", summary="ZOPA dinámica por producto (POST)")
def catalog_zopa_post(body: ZopaRequest):
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    q = body.q
    zopa = bridge.get_zopa_for_message(q) if q else bridge.get_default_zopa()
    product = bridge.find_product(q) if q else bridge.get_featured_product()
    return {"zopa": zopa, "product": product}


@router.post(
    "/followup/run",
    response_model=FollowupRunResponse,
    summary="Ejecutar ciclo de reactivación CRM",
)
async def run_followup():
    from app.agents.closing_followup_agent import get_followup_agent

    agent = get_followup_agent()
    result = await agent.run_followup_cycle()
    return FollowupRunResponse(
        scanned=result["scanned"],
        sent=result["sent"],
        skipped=result["skipped"],
        errors=result["errors"],
    )


@router.post("/shein/scrape", summary="Ejecutar scraper Shein e ingerir catálogo")
async def shein_scrape(body: SheinScrapeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_shein_pipeline, body.save_excel)
    return {"status": "started", "message": "Scraper Shein en ejecución"}


async def _run_shein_pipeline(save_excel: bool) -> None:
    try:
        from shein_analyzer.scraper import scrape_enterizos_deportivos
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        products = await scrape_enterizos_deportivos(save_excel=save_excel)
        bridge = get_catalog_bridge()
        count = bridge.ingest_shein_products(products)
        print(f"[SheinPipeline] {count} productos ingeridos al catalog bridge")
    except Exception as e:
        print(f"[SheinPipeline] Error: {e}")


@router.get("/health", summary="Estado de agentes cableados")
def agents_health():
    from app.agents.catalog_bridge_agent import get_catalog_bridge

    bridge = get_catalog_bridge()
    return {
        "agents_active": [
            "athena_analyst",
            "hermes_negotiator",
            "business_evolver",
            "prompts_factory",
            "shaka_quantum_prospector",
            "hephaestus_creator",
            "catalog_bridge_agent",
            "objection_killer_agent",
            "closing_followup_agent",
        ],
        "catalog": bridge.get_catalog_summary(),
    }
