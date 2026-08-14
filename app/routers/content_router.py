"""
app/routers/content_router.py
────────────────────────────────────────────────────────────────────────────────
Sistema de Contenido y Outliers — ingeniería inversa de contenido viral.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.content import crud
from app.content.exceptions import ContentError, ContentPaymentRequiredError
from app.content.models import GeneratedScript
from app.content.schemas import (
    ContentAdsProduct,
    ContentPipelineRequest,
    ContentPipelineResponse,
    OutlierAnalyzeRequest,
    OutlierAnalyzeResponse,
    ProfileCreate,
    ProfileResponse,
    ScriptGenerateRequest,
    ScriptGenerateResponse,
)
from app.database.sqlalchemy_session import SessionLocal, get_db
from app.security import verify_api_key
from app.services.content_ads_bridge import (
    launch_ads_from_script_sync,
    resolve_producto_from_catalog,
)
from app.services.content_remix_service import get_content_remix_service
from app.services.content_webhook import notify_content_webhook_sync
from app.services.billing import (
    CONTENT_PIPELINE_COST_USD,
    can_run_content_pipeline,
    deduct_content_pipeline_credit,
)
from app.services.tenant_config_service import (
    build_pipeline_payload_from_config,
    get_tenant_config,
    list_active_tenants_for_content,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _handle_content_error(exc: ContentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _resolve_producto_for_ads(
    *,
    producto: ContentAdsProduct | None,
    auto_producto: bool,
    launch_ads: bool,
    use_trends: bool = True,
    catalog_query: str | None = None,
    niche: str = "",
    product_focus: str | None = None,
) -> tuple[ContentAdsProduct | None, str | None, Optional[str]]:
    if not launch_ads:
        return None, None, None
    if producto is not None:
        return producto, "manual", None
    if auto_producto:
        resolved, trend_kw, source = resolve_producto_from_catalog(
            catalog_query=catalog_query or "",
            niche=niche,
            product_focus=product_focus or "",
            use_trends=use_trends,
        )
        return resolved, source, trend_kw
    return None, None, None


def _fire_webhook(webhook_url: str | None, payload: dict[str, Any]) -> None:
    if webhook_url:
        notify_content_webhook_sync(str(webhook_url), payload)


def _queue_ads_launch(
    script_id: str,
    producto: ContentAdsProduct,
    *,
    skip_meta_create: bool = False,
    webhook_url: str | None = None,
    webhook_base: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        script = db.get(GeneratedScript, script_id)
        if not script:
            logger.error("[Content] Ads queue: script %s no encontrado", script_id)
            return
        result = launch_ads_from_script_sync(
            script,
            producto,
            skip_meta_create=skip_meta_create,
            daily_budget_cop=producto.daily_budget_cop,
        )
        wh_payload = {
            "event": "content.pipeline.ads_finished",
            **(webhook_base or {}),
            "ads_ok": result.get("ok"),
            "campaign_id": result.get("campaign_id"),
            "ads_error": result.get("error"),
        }
        _fire_webhook(webhook_url, wh_payload)
        if result.get("ok"):
            logger.info("[Content] Ads OK script=%s campaign=%s", script_id, result.get("campaign_id"))
        else:
            logger.warning("[Content] Ads falló script=%s: %s", script_id, result.get("error"))
    except Exception:
        logger.exception("[Content] Error en background ads script=%s", script_id)
    finally:
        db.close()


def _queue_pipeline_ads(
    script_id: str,
    producto: ContentAdsProduct,
    *,
    skip_meta_create: bool = False,
    webhook_url: str | None = None,
    webhook_base: dict[str, Any] | None = None,
) -> None:
    _queue_ads_launch(
        script_id,
        producto,
        skip_meta_create=skip_meta_create,
        webhook_url=webhook_url,
        webhook_base=webhook_base,
    )


def _check_billing_gate(tenant_id: str) -> str:
    allowed, reason = can_run_content_pipeline(tenant_id)
    if not allowed:
        raise ContentPaymentRequiredError(
            f"Tenant '{tenant_id}' no puede ejecutar pipeline: {reason}. "
            f"Recarga wallet (mín. ${CONTENT_PIPELINE_COST_USD} USD) o activa trial."
        )
    return reason


def _finalize_pipeline(
    payload: ContentPipelineRequest,
    result: ContentPipelineResponse,
    background_tasks: BackgroundTasks,
) -> ContentPipelineResponse:
    deduct_content_pipeline_credit(
        payload.tenant_id,
        referencia_id=result.script_id or result.outlier_id,
        llm_calls=result.llm_calls,
    )
    billing_reason = can_run_content_pipeline(payload.tenant_id)[1]

    producto, catalog_source, trend_kw = _resolve_producto_for_ads(
        producto=payload.producto,
        auto_producto=payload.auto_producto,
        launch_ads=payload.launch_ads and not result.skipped,
        use_trends=payload.use_trends,
        catalog_query=payload.catalog_query,
        niche=payload.niche,
        product_focus=payload.product_focus,
    )

    result = result.model_copy(
        update={
            "producto": producto,
            "catalog_source": catalog_source,
            "trend_keyword": trend_kw,
            "billing_mode": billing_reason,
        }
    )

    webhook_base = {
        "tenant_id": payload.tenant_id,
        "outlier_id": result.outlier_id,
        "script_id": result.script_id,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "llm_calls": result.llm_calls,
        "mode": result.mode,
        "composite_score": result.composite_score,
        "script_preview": result.script_preview,
        "producto_titulo": producto.titulo if producto else None,
        "trend_keyword": trend_kw,
        "billing_mode": billing_reason,
    }

    if payload.webhook_url:
        event = "content.pipeline.skipped" if result.skipped else "content.pipeline.completed"
        background_tasks.add_task(
            _fire_webhook,
            str(payload.webhook_url),
            {"event": event, "ads_queued": False, **webhook_base},
        )

    if payload.launch_ads and producto and not result.skipped and result.script_id:
        wh_url = str(payload.webhook_url) if payload.webhook_url else None
        background_tasks.add_task(
            _queue_pipeline_ads,
            result.script_id,
            producto,
            skip_meta_create=payload.skip_meta_create,
            webhook_url=wh_url,
            webhook_base={**webhook_base, "ads_queued": True},
        )
        result = result.model_copy(update={"ads_queued": True})

    return result


def _run_single_tenant_pipeline(
    payload_dict: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    """Ejecuta pipeline para un tenant (uso en batch background)."""
    metrics = payload_dict.pop("metrics", {})
    caption = payload_dict.pop("caption", None)
    platform = payload_dict.pop("platform", "instagram")

    from app.content.schemas import VideoMetrics

    req = ContentPipelineRequest(
        **{
            k: v
            for k, v in payload_dict.items()
            if k
            in ContentPipelineRequest.model_fields
            and k not in ("metrics", "caption", "platform", "tenant_nombre", "estado")
        },
        platform=platform,
        metrics=VideoMetrics(**metrics),
        caption=caption or None,
    )

    _check_billing_gate(req.tenant_id)
    service = get_content_remix_service()
    result = service.run_pipeline(db, req)
    deduct_content_pipeline_credit(
        req.tenant_id,
        referencia_id=result.script_id or result.outlier_id,
        llm_calls=result.llm_calls,
    )

    producto = None
    if req.launch_ads and not result.skipped and result.script_id:
        producto, _, _ = _resolve_producto_for_ads(
            producto=req.producto,
            auto_producto=req.auto_producto,
            launch_ads=True,
            use_trends=req.use_trends,
            catalog_query=req.catalog_query,
            niche=req.niche,
            product_focus=req.product_focus,
        )
        if producto:
            script = db.get(GeneratedScript, result.script_id)
            if script:
                launch_ads_from_script_sync(
                    script,
                    producto,
                    skip_meta_create=req.skip_meta_create,
                )

    return {
        "tenant_id": req.tenant_id,
        "ok": True,
        "skipped": result.skipped,
        "script_id": result.script_id,
        "llm_calls": result.llm_calls,
    }


def _batch_pipeline_worker(tenants_payload: list[dict[str, Any]]) -> None:
    db = SessionLocal()
    summary: list[dict] = []
    try:
        for item in tenants_payload:
            tid = item.get("tenant_id", "?")
            try:
                summary.append(_run_single_tenant_pipeline(dict(item), db))
            except ContentPaymentRequiredError as exc:
                summary.append({"tenant_id": tid, "ok": False, "error": str(exc)})
            except Exception as exc:
                logger.exception("[Content] Batch falló tenant=%s", tid)
                summary.append({"tenant_id": tid, "ok": False, "error": str(exc)})
        logger.info("[Content] Batch completado: %d tenants", len(summary))
    finally:
        db.close()


@router.get("/tenants/active", summary="Tenants activos listos para pipeline (n8n loop)")
def list_active_tenants(limit: int = 100) -> dict[str, Any]:
    """Devuelve payloads pre-armados por tenant para automatización multi-cliente."""
    tenants = list_active_tenants_for_content(limit=min(limit, 500))
    return {
        "total": len(tenants),
        "costo_estimado_usd": round(
            sum(1 for t in tenants if t.get("estado") != "trial") * CONTENT_PIPELINE_COST_USD, 2
        ),
        "tenants": tenants,
    }


@router.get("/tenants/{tenant_id}/config", summary="Config de contenido de un tenant")
def get_tenant_content_config(tenant_id: str) -> dict[str, Any]:
    cfg = get_tenant_config(tenant_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' no encontrado")
    allowed, billing = can_run_content_pipeline(tenant_id)
    return {
        "config": cfg,
        "pipeline_payload": build_pipeline_payload_from_config(cfg),
        "billing_allowed": allowed,
        "billing_mode": billing,
        "costo_pipeline_usd": CONTENT_PIPELINE_COST_USD,
    }


@router.post(
    "/pipeline/run-batch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ejecutar pipeline para TODOS los tenants activos (1 cron n8n)",
)
def run_content_pipeline_batch(
    background_tasks: BackgroundTasks,
    limit: int = 50,
) -> dict[str, Any]:
    """
    **Más eficiente para 1000 clientes:** un solo cron n8n llama este endpoint
    y el servidor procesa cada tenant en background con gate de billing.
    """
    tenants = list_active_tenants_for_content(limit=min(limit, 500))
    if not tenants:
        return {"queued": 0, "message": "No hay tenants activos con content_enabled"}

    background_tasks.add_task(_batch_pipeline_worker, tenants)
    return {
        "queued": len(tenants),
        "message": f"Pipeline encolado para {len(tenants)} tenants",
        "tenant_ids": [t["tenant_id"] for t in tenants],
        "costo_max_estimado_usd": round(
            sum(1 for t in tenants if t.get("estado") != "trial") * CONTENT_PIPELINE_COST_USD,
            2,
        ),
    }


@router.post("/profiles", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def register_profile(payload: ProfileCreate, db: Session = Depends(get_db)) -> ProfileResponse:
    try:
        return ProfileResponse.model_validate(crud.create_profile(db, payload))
    except ContentError as exc:
        raise _handle_content_error(exc) from exc
    except Exception as exc:
        logger.exception("[Content] Error registrando perfil")
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}") from exc


@router.post("/outliers/analyze", response_model=OutlierAnalyzeResponse, status_code=status.HTTP_201_CREATED)
def analyze_outlier(payload: OutlierAnalyzeRequest, db: Session = Depends(get_db)) -> OutlierAnalyzeResponse:
    try:
        return get_content_remix_service().analyze_outlier(db, payload)
    except ContentError as exc:
        raise _handle_content_error(exc) from exc
    except Exception as exc:
        logger.exception("[Content] Error analizando outlier")
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}") from exc


@router.post("/scripts/generate", response_model=ScriptGenerateResponse, status_code=status.HTTP_201_CREATED)
def generate_script(
    payload: ScriptGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScriptGenerateResponse:
    try:
        producto, _, _ = _resolve_producto_for_ads(
            producto=payload.producto,
            auto_producto=payload.auto_producto,
            launch_ads=payload.launch_ads,
            catalog_query=payload.catalog_query,
            niche=payload.niche,
            product_focus=payload.product_focus,
        )
        result = get_content_remix_service().generate_script(db, payload)
        if payload.launch_ads and producto:
            background_tasks.add_task(
                _queue_ads_launch,
                result.id,
                producto,
                skip_meta_create=payload.skip_meta_create,
            )
            return result.model_copy(update={"ads_queued": True})
        return result
    except ContentError as exc:
        raise _handle_content_error(exc) from exc
    except Exception as exc:
        logger.exception("[Content] Error generando guion")
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}") from exc


@router.post(
    "/pipeline/run",
    response_model=ContentPipelineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pipeline económico (filtro + 1 LLM + ads + webhook)",
)
def run_content_pipeline(
    payload: ContentPipelineRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ContentPipelineResponse:
    try:
        _check_billing_gate(payload.tenant_id)
        service = get_content_remix_service()
        result = service.run_pipeline(db, payload)
        return _finalize_pipeline(payload, result, background_tasks)
    except ContentError as exc:
        raise _handle_content_error(exc) from exc
    except Exception as exc:
        logger.exception("[Content] Error en pipeline")
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}") from exc
