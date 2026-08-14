"""
app/marketing/meta_api.py
────────────────────────────────────────────────────────────────────────────────
Cliente Meta Marketing API — campañas, insights, presupuesto.

Variables .env:
  META_ACCESS_TOKEN
  META_AD_ACCOUNT_ID          (con o sin prefijo act_)
  META_PAGE_ID                (requerido para creativos)
  META_PIXEL_ID               (opcional, conversiones)
  META_DEFAULT_DAILY_BUDGET   (COP, default 30000)
  META_DEFAULT_OBJECTIVE      (default OUTCOME_SALES)
  META_DEFAULT_LINK_URL       (landing / WhatsApp link)
  META_GRAPH_VERSION          (default v21.0)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.api import FacebookAdsApi

load_dotenv()

logger = logging.getLogger(__name__)

# Presupuesto diario por defecto en unidades de moneda (COP), Meta usa centavos
DEFAULT_DAILY_BUDGET_COP = float(os.environ.get("META_DEFAULT_DAILY_BUDGET", "30000"))
DEFAULT_OBJECTIVE = os.environ.get("META_DEFAULT_OBJECTIVE", "OUTCOME_SALES")
DEFAULT_LINK_URL = os.environ.get("META_DEFAULT_LINK_URL", "https://wa.me/573000000000")


def _cop_to_meta_amount(cop: float) -> int:
    """Meta espera presupuesto en unidad mínima (centavos para COP)."""
    return max(100, int(round(cop * 100)))


def _meta_amount_to_cop(amount: int) -> float:
    return round(amount / 100.0, 2)


def _default_targeting_colombia() -> dict[str, Any]:
    """Segmentación base: Colombia (Cúcuta vía región si está configurada)."""
    geo: dict[str, Any] = {"countries": ["CO"]}
    region_key = os.environ.get("META_GEO_REGION_KEY", "").strip()
    city_key = os.environ.get("META_GEO_CITY_KEY", "").strip()
    if city_key:
        geo["cities"] = [{"key": city_key, "radius": 40, "distance_unit": "kilometer"}]
    elif region_key:
        geo["regions"] = [{"key": region_key}]
    return {
        "geo_locations": geo,
        "age_min": int(os.environ.get("META_AGE_MIN", "18")),
        "age_max": int(os.environ.get("META_AGE_MAX", "55")),
    }


class MetaAdsManager:
    """Wrapper de alto nivel sobre facebook-business SDK."""

    def __init__(self, *, access_token: str | None = None, ad_account_id: str | None = None):
        self.access_token = (access_token or os.environ.get("META_ACCESS_TOKEN", "")).strip()
        self.ad_account_id = (ad_account_id or os.environ.get("META_AD_ACCOUNT_ID", "")).strip()
        self.page_id = os.environ.get("META_PAGE_ID", "").strip()
        self.pixel_id = os.environ.get("META_PIXEL_ID", "").strip()

        if not self.ad_account_id:
            raise ValueError("Falta META_AD_ACCOUNT_ID en .env")
        if not self.access_token:
            raise ValueError("Falta META_ACCESS_TOKEN en .env")

        FacebookAdsApi.init(access_token=self.access_token)

        act = self.ad_account_id if self.ad_account_id.startswith("act_") else f"act_{self.ad_account_id}"
        self.account_id = act
        self.account = AdAccount(act)

        logger.info("[MetaAds] Cuenta %s | page_id=%s", act, bool(self.page_id))

    # ── Métricas cuenta ───────────────────────────────────────────────────────

    def get_account_metrics(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        date_preset: str = "last_30d",
    ) -> dict[str, Any]:
        """Insights a nivel cuenta."""
        params: dict[str, Any] = {"level": "account"}
        if since and until:
            params["time_range"] = {"since": since, "until": until}
        else:
            params["date_preset"] = date_preset

        fields = [
            "spend", "impressions", "clicks", "ctr", "cpc",
            "actions", "action_values", "cost_per_action_type",
        ]
        raw = self.account.get_insights(fields=fields, params=params)
        return _normalize_insights_list(raw)

    def get_account_spend_today(self) -> float:
        """Gasto acumulado de la cuenta hoy (COP)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data = self.get_account_metrics(since=today, until=today)
        rows = data.get("rows") or []
        if not rows:
            return 0.0
        return float(rows[0].get("spend", 0) or 0)

    # ── Campañas — listado ────────────────────────────────────────────────────

    def listar_campanas(
        self,
        *,
        effective_status: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Lista campañas de la cuenta.
        effective_status default: ACTIVE + PAUSED (para auditoría).
        """
        statuses = effective_status or ["ACTIVE", "PAUSED"]
        cursor = self.account.get_campaigns(
            fields=["id", "name", "status", "effective_status", "objective", "created_time", "updated_time"],
            params={"effective_status": statuses, "limit": limit},
        )
        return [_sdk_to_dict(c) for c in cursor]

    def listar_campanas_activas(self, limit: int = 100) -> list[dict[str, Any]]:
        """Solo campañas con effective_status ACTIVE."""
        return self.listar_campanas(effective_status=["ACTIVE"], limit=limit)

    # ── Insights por campaña ──────────────────────────────────────────────────

    def get_campaign_insights(
        self,
        campaign_id: str,
        *,
        date_preset: str = "last_7d",
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """
        Métricas de una campaña + KPIs derivados (CPA, ROAS proxy).

        Returns:
            {
              "campaign_id": str,
              "rows": [...],
              "summary": {
                "spend", "impressions", "clicks", "ctr", "cpc",
                "conversions", "cpa", "purchase_value", "roas",
                "hours_since_created" (si disponible),
              }
            }
        """
        params: dict[str, Any] = {}
        if since and until:
            params["time_range"] = {"since": since, "until": until}
        else:
            params["date_preset"] = date_preset

        fields = [
            "campaign_id", "campaign_name", "spend", "impressions", "clicks",
            "ctr", "cpc", "actions", "action_values", "cost_per_action_type",
            "date_start", "date_stop",
        ]
        campaign = Campaign(campaign_id)
        raw = campaign.get_insights(fields=fields, params=params)
        normalized = _normalize_insights_list(raw)
        summary = _build_summary(normalized.get("rows") or [])

        created_hours = None
        try:
            meta = campaign.api_get(fields=["created_time"])
            created_hours = _hours_since(meta.get("created_time"))
            summary["hours_since_created"] = created_hours
            summary["campaign_name"] = meta.get("name")
        except Exception as e:
            logger.debug("[MetaAds] created_time: %s", e)

        return {
            "campaign_id": campaign_id,
            "rows": normalized.get("rows") or [],
            "summary": summary,
        }

    def get_campaign_insights_24h(self, campaign_id: str) -> dict[str, Any]:
        """Atajo — últimas 24 horas (para reglas de escalado)."""
        until_dt = datetime.now(timezone.utc)
        since_dt = until_dt - timedelta(hours=24)
        return self.get_campaign_insights(
            campaign_id,
            since=since_dt.strftime("%Y-%m-%d"),
            until=until_dt.strftime("%Y-%m-%d"),
        )

    # ── Control de campaña ────────────────────────────────────────────────────

    def pausar_campana(self, campaign_id: str) -> dict[str, Any]:
        """Pausa campaña."""
        campaign = Campaign(campaign_id)
        result = campaign.api_update(params={"status": "PAUSED"})
        logger.info("[MetaAds] Campaña pausada: %s", campaign_id)
        return _sdk_to_dict(result)

    def activar_campana(self, campaign_id: str) -> dict[str, Any]:
        """Activa campaña (uso manual — fase 1 no auto-activa)."""
        campaign = Campaign(campaign_id)
        result = campaign.api_update(params={"status": "ACTIVE"})
        logger.info("[MetaAds] Campaña activada: %s", campaign_id)
        return _sdk_to_dict(result)

    def subir_presupuesto(
        self,
        adset_id: str,
        porcentaje: float = 20.0,
        *,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Incrementa daily_budget del Ad Set en `porcentaje` %.

        Returns:
            {adset_id, presupuesto_anterior_cop, presupuesto_nuevo_cop, porcentaje}
        """
        adset = AdSet(adset_id)
        adset.api_get(fields=["daily_budget", "lifetime_budget", "name", "campaign_id"])
        daily = adset.get("daily_budget")
        if not daily:
            raise ValueError(f"Ad Set {adset_id} no tiene daily_budget (¿CBO a nivel campaña?)")

        anterior = int(daily)
        nuevo = int(anterior * (1 + porcentaje / 100.0))
        adset.api_update(params={"daily_budget": nuevo})

        cid = campaign_id or adset.get("campaign_id")
        logger.info(
            "[MetaAds] Presupuesto AdSet %s: %s → %s COP (+%s%%)",
            adset_id,
            _meta_amount_to_cop(anterior),
            _meta_amount_to_cop(nuevo),
            porcentaje,
        )
        return {
            "adset_id": adset_id,
            "campaign_id": cid,
            "presupuesto_anterior_cop": _meta_amount_to_cop(anterior),
            "presupuesto_nuevo_cop": _meta_amount_to_cop(nuevo),
            "porcentaje": porcentaje,
        }

    def obtener_adsets_de_campana(self, campaign_id: str) -> list[dict[str, Any]]:
        """Lista Ad Sets de una campaña (útil para escalado de presupuesto)."""
        campaign = Campaign(campaign_id)
        cursor = campaign.get_ad_sets(
            fields=["id", "name", "status", "daily_budget", "lifetime_budget", "targeting"],
            params={"limit": 50},
        )
        return [_sdk_to_dict(a) for a in cursor]

    # ── Creación completa (siempre PAUSED por defecto) ────────────────────────

    def crear_campana_completa(
        self,
        *,
        nombre: str,
        copy: dict[str, str],
        creative_path: str | None = None,
        image_hash: str | None = None,
        video_id: str | None = None,
        link_url: str | None = None,
        daily_budget_cop: float | None = None,
        targeting: dict[str, Any] | None = None,
        objective: str | None = None,
        status: str = "PAUSED",
        special_ad_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Crea Campaign + AdSet + AdCreative + Ad en estado PAUSED (por defecto).

        copy keys: titulo, texto_principal, descripcion (opc), cta (opc)

        Returns:
            {
              campaign_id, adset_id, ad_id, creative_id,
              status, nombre, daily_budget_cop, targeting
            }
        """
        if not self.page_id:
            raise ValueError("Falta META_PAGE_ID en .env — necesario para AdCreative")

        budget_cop = daily_budget_cop or DEFAULT_DAILY_BUDGET_COP
        obj = objective or DEFAULT_OBJECTIVE
        url = link_url or DEFAULT_LINK_URL
        tgt = targeting or _default_targeting_colombia()
        spec_categories = special_ad_categories if special_ad_categories is not None else []

        titulo = copy.get("titulo", nombre)[:40]
        mensaje = copy.get("texto_principal", "")
        descripcion = copy.get("descripcion", "")
        cta_type = _map_cta(copy.get("cta", "WHATSAPP_MESSAGE"))

        # 1) Campaign
        campaign_params = {
            "name": nombre[:200],
            "objective": obj,
            "status": status,
            "special_ad_categories": spec_categories,
            "is_adset_budget_sharing_enabled": False,
        }
        campaign = self.account.create_campaign(params=campaign_params)
        campaign_id = campaign["id"]

        # 2) Ad Set
        adset_params: dict[str, Any] = {
            "name": f"{nombre[:120]} — AdSet",
            "campaign_id": campaign_id,
            "daily_budget": _cop_to_meta_amount(budget_cop),
            "billing_event": "IMPRESSIONS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": tgt,
            "status": status,
            **_adset_optimization_for_objective(obj),
        }
        if self.pixel_id and obj in ("OUTCOME_SALES", "CONVERSIONS"):
            adset_params["promoted_object"] = {"pixel_id": self.pixel_id, "custom_event_type": "PURCHASE"}

        adset = self.account.create_ad_set(params=adset_params)
        adset_id = adset["id"]

        # 3) Creative — imagen o video
        if not image_hash and creative_path:
            image_hash = self._subir_imagen(creative_path)

        creative_params = self._build_creative_params(
            nombre=nombre,
            titulo=titulo,
            mensaje=mensaje,
            descripcion=descripcion,
            link_url=url,
            cta_type=cta_type,
            image_hash=image_hash,
            video_id=video_id,
        )
        creative = self.account.create_ad_creative(params=creative_params)
        creative_id = creative["id"]

        # 4) Ad
        ad = self.account.create_ad(params={
            "name": f"{nombre[:120]} — Ad",
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": status,
        })
        ad_id = ad["id"]

        logger.info(
            "[MetaAds] Campaña creada PAUSED | campaign=%s adset=%s ad=%s",
            campaign_id, adset_id, ad_id,
        )

        return {
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "ad_id": ad_id,
            "creative_id": creative_id,
            "status": status,
            "nombre": nombre,
            "daily_budget_cop": budget_cop,
            "targeting": tgt,
            "objective": obj,
            "link_url": url,
        }

    def _subir_imagen(self, path: str) -> str:
        """Sube imagen al Ad Account y devuelve image_hash."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Creative no encontrado: {path}")

        img = AdImage(parent_id=self.account_id)
        img[AdImage.Field.filename] = str(p.resolve())
        img.remote_create()
        h = img.get(AdImage.Field.hash)
        if not h:
            raise RuntimeError("Meta no devolvió image_hash tras subir creative")
        return h

    def _build_creative_params(
        self,
        *,
        nombre: str,
        titulo: str,
        mensaje: str,
        descripcion: str,
        link_url: str,
        cta_type: str,
        image_hash: str | None,
        video_id: str | None,
    ) -> dict[str, Any]:
        if video_id:
            object_story_spec: dict[str, Any] = {
                "page_id": self.page_id,
                "video_data": {
                    "video_id": video_id,
                    "title": titulo,
                    "message": mensaje,
                    "call_to_action": {"type": cta_type, "value": {"link": link_url}},
                },
            }
        else:
            if not image_hash:
                raise ValueError("Se requiere creative_path, image_hash o video_id para el anuncio")
            link_data: dict[str, Any] = {
                "link": link_url,
                "message": mensaje,
                "name": titulo,
                "call_to_action": {"type": cta_type, "value": {"link": link_url}},
            }
            if descripcion:
                link_data["description"] = descripcion
            if image_hash:
                link_data["image_hash"] = image_hash
            object_story_spec = {
                "page_id": self.page_id,
                "link_data": link_data,
            }

        return {
            "name": f"{nombre[:100]} — Creative",
            "object_story_spec": object_story_spec,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Helpers — normalización insights / SDK
# ══════════════════════════════════════════════════════════════════════════════

def _sdk_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    try:
        return dict(obj)
    except Exception:
        return {"raw": str(obj)}


def _normalize_insights_list(raw: Any) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in raw or []:
        row = _sdk_to_dict(item)
        if "spend" in row:
            row["spend"] = float(row.get("spend") or 0)
        if "ctr" in row:
            row["ctr"] = float(row.get("ctr") or 0)
        if "cpc" in row:
            row["cpc"] = float(row.get("cpc") or 0)
        rows.append(row)
    return {"rows": rows, "total_rows": len(rows)}


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "spend": 0.0, "impressions": 0, "clicks": 0, "ctr": 0.0, "cpc": 0.0,
            "conversions": 0, "cpa": None, "purchase_value": 0.0, "roas": None,
        }

    spend = sum(float(r.get("spend") or 0) for r in rows)
    impressions = sum(int(r.get("impressions") or 0) for r in rows)
    clicks = sum(int(r.get("clicks") or 0) for r in rows)
    ctr = (clicks / impressions * 100) if impressions else 0.0
    cpc = (spend / clicks) if clicks else 0.0

    conversions = 0
    purchase_value = 0.0
    cpa_from_meta = None

    for r in rows:
        for action in r.get("actions") or []:
            at = (action.get("action_type") or "").lower()
            val = int(action.get("value") or 0)
            if at in ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase", "lead"):
                conversions += val
        for av in r.get("action_values") or []:
            at = (av.get("action_type") or "").lower()
            if "purchase" in at:
                purchase_value += float(av.get("value") or 0)
        for cpa in r.get("cost_per_action_type") or []:
            at = (cpa.get("action_type") or "").lower()
            if "purchase" in at or at == "lead":
                try:
                    cpa_from_meta = float(cpa.get("value"))
                except (TypeError, ValueError):
                    pass

    cpa = cpa_from_meta
    if cpa is None and conversions > 0:
        cpa = round(spend / conversions, 2)

    roas = round(purchase_value / spend, 2) if spend > 0 and purchase_value > 0 else None

    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": round(ctr, 4),
        "cpc": round(cpc, 2),
        "conversions": conversions,
        "cpa": cpa,
        "purchase_value": round(purchase_value, 2),
        "roas": roas,
    }


def _hours_since(iso_time: str | None) -> float | None:
    if not iso_time:
        return None
    try:
        ts = iso_time.replace("+0000", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


def _adset_optimization_for_objective(objective: str) -> dict[str, str]:
    obj = (objective or "").upper()
    if obj in ("OUTCOME_SALES", "CONVERSIONS"):
        return {"optimization_goal": "OFFSITE_CONVERSIONS"}
    if obj in ("OUTCOME_TRAFFIC", "LINK_CLICKS"):
        return {"optimization_goal": "LINK_CLICKS"}
    if obj in ("OUTCOME_ENGAGEMENT", "MESSAGES"):
        return {"optimization_goal": "CONVERSATIONS"}
    return {"optimization_goal": "LINK_CLICKS"}


def _map_cta(cta: str) -> str:
    """Mapea CTA legible a constante Meta."""
    c = (cta or "").upper().replace(" ", "_")
    mapping = {
        "WHATSAPP": "WHATSAPP_MESSAGE",
        "WHATSAPP_MESSAGE": "WHATSAPP_MESSAGE",
        "COMPRAR": "SHOP_NOW",
        "SHOP_NOW": "SHOP_NOW",
        "VER_MAS": "LEARN_MORE",
        "LEARN_MORE": "LEARN_MORE",
        "SEND_MESSAGE": "SEND_MESSAGE",
        "CONTACTAR": "CONTACT_US",
        "CONTACT_US": "CONTACT_US",
    }
    return mapping.get(c, "LEARN_MORE")
