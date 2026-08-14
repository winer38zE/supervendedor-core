"""
app/services/tenant_config_service.py
────────────────────────────────────────────────────────────────────────────────
Configuración multi-tenant para automatización de contenido y ventas.

Lee tenants + clients_config desde PocketBase/Supabase (vía get_client).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

ACTIVE_STATES = ("trial", "activo")


def _db():
    from app.database.supabase_client import get_client
    return get_client()


def get_tenant_config(tenant_id: str) -> Optional[dict[str, Any]]:
    """Config de contenido/ventas para un tenant (clients_config + tenant)."""
    db = _db()
    if not db:
        return None

    config: dict[str, Any] = {"tenant_id": tenant_id, "client_id": tenant_id}

    try:
        t_res = db.table("tenants").select("*").eq("id", tenant_id).single().execute()
        tenant = t_res.data if isinstance(t_res.data, dict) else (t_res.data[0] if t_res.data else None)
        if tenant:
            config.update(tenant)
    except Exception as exc:
        logger.debug("[TenantConfig] tenants %s: %s", tenant_id, exc)

    try:
        c_res = (
            db.table("clients_config")
            .select("*")
            .eq("client_id", tenant_id)
            .limit(1)
            .execute()
        )
        row = c_res.data[0] if c_res.data else None
        if row:
            config.update(row)
    except Exception as exc:
        logger.debug("[TenantConfig] clients_config %s: %s", tenant_id, exc)

    return config


def list_active_tenants_for_content(*, limit: int = 100) -> list[dict[str, Any]]:
    """
    Tenants listos para pipeline automático:
      - estado trial o activo (tabla tenants)
      - content_enabled != false en clients_config
    Si no hay tabla tenants, usa solo clients_config como fuente.
    """
    db = _db()
    if not db:
        return []

    tenants: list[dict] = []
    try:
        for estado in ACTIVE_STATES:
            res = (
                db.table("tenants")
                .select("id, nombre, email, telefono, estado, trial_expira_at, plan")
                .eq("estado", estado)
                .limit(limit)
                .execute()
            )
            tenants.extend(res.data or [])
    except Exception as exc:
        logger.debug("[TenantConfig] tenants no disponible: %s", exc)

    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for t in tenants:
        tid = str(t.get("id", ""))
        if not tid or tid in seen:
            continue
        seen.add(tid)

        cfg = get_tenant_config(tid) or {}
        if cfg.get("content_enabled") is False:
            continue

        result.append(build_pipeline_payload_from_config(cfg, tenant_row=t))

    if result:
        return result[:limit]

    # Fallback PocketBase: solo clients_config (sin colección tenants)
    try:
        cfg_res = (
            db.table("clients_config")
            .select("*")
            .limit(limit)
            .execute()
        )
        for row in cfg_res.data or []:
            if row.get("content_enabled") is False:
                continue
            tid = str(row.get("client_id") or row.get("tenant_id") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            cfg = get_tenant_config(tid) or row
            result.append(
                build_pipeline_payload_from_config(
                    cfg,
                    tenant_row={"id": tid, "nombre": row.get("negocio_nombre", tid), "estado": "activo"},
                )
            )
    except Exception as exc:
        logger.warning("[TenantConfig] Error listando clients_config: %s", exc)

    return result[:limit]


def build_pipeline_payload_from_config(
    cfg: dict[str, Any],
    *,
    tenant_row: Optional[dict] = None,
) -> dict[str, Any]:
    """Payload base para POST /content/pipeline/run por tenant."""
    tid = str(cfg.get("tenant_id") or cfg.get("client_id") or tenant_row.get("id", ""))
    row = tenant_row or {}

    return {
        "tenant_id": tid,
        "tenant_nombre": row.get("nombre") or cfg.get("negocio_nombre", tid),
        "platform": cfg.get("content_platform") or "instagram",
        "niche": cfg.get("niche") or cfg.get("negocio_nombre") or "ventas online",
        "brand_voice": cfg.get("brand_voice") or "cercano, colombiano, orientado a ventas",
        "product_focus": cfg.get("product_focus") or cfg.get("producto_focus") or "",
        "catalog_query": cfg.get("catalog_query") or "",
        "remix_level": float(cfg.get("remix_level") or 0.5),
        "single_pass": cfg.get("single_pass", True) is not False,
        "launch_ads": cfg.get("launch_ads", True) is not False,
        "auto_producto": cfg.get("auto_producto", True) is not False,
        "use_trends": cfg.get("use_trends", True) is not False,
        "llm_preference": cfg.get("llm_preference") or "openai",
        "webhook_url": cfg.get("content_webhook_url") or cfg.get("webhook_url") or "",
        "skip_meta_create": cfg.get("skip_meta_create", False) is True,
        "estado": row.get("estado") or cfg.get("estado", "activo"),
        "metrics": cfg.get("last_metrics") or {
            "views": int(cfg.get("default_views") or 100000),
            "likes": int(cfg.get("default_likes") or 8000),
            "comments": int(cfg.get("default_comments") or 400),
            "shares": int(cfg.get("default_shares") or 1200),
        },
        "caption": cfg.get("last_caption") or cfg.get("content_caption") or "",
    }


def is_trial_expired(tenant: dict) -> bool:
    exp = tenant.get("trial_expira_at") or ""
    if not exp:
        return False
    try:
        expira = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= expira
    except Exception:
        return False
