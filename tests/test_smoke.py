"""
Tests de humo — Super Vendedor Core
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENV", "development")
os.environ.setdefault("DB_BACKEND", "pocketbase")
os.environ.setdefault("FOLLOWUP_SCHEDULER_ENABLED", "false")
# Sin INTERNAL_API_KEY → development permite acceso sin header

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    """GET /health permanece público para monitoreo (Coolify, uptime)."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "healthy"


def test_catalog_snapshot_returns_200():
    r = client.get("/agents/catalog/snapshot")
    assert r.status_code == 200
    data = r.json()
    assert "products" in data
    assert "summary" in data


def test_catalog_zopa_get_returns_prices():
    r = client.get("/agents/catalog/zopa", params={"q": "enterizo"})
    assert r.status_code == 200
    data = r.json()
    zopa = data.get("zopa", {})
    assert "target_price" in zopa
    assert "reserve_price" in zopa
    assert zopa["target_price"] > 0
    assert zopa["reserve_price"] > 0


def test_api_key_required_when_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "test-secret-key")

    r = client.get("/agents/catalog/snapshot")
    assert r.status_code == 401

    r_ok = client.get("/agents/catalog/snapshot", headers={"X-API-Key": "test-secret-key"})
    assert r_ok.status_code == 200

    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "")


def test_whatsapp_webhook_returns_200():
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "573001234567@s.whatsapp.net", "fromMe": False, "id": "test-msg-001"},
            "message": {"conversation": "hola"},
            "messageTimestamp": 1234567890,
        },
    }
    r = client.post("/whatsapp/webhook", json=payload)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_whatsapp_webhook_idempotent():
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "573009999999@s.whatsapp.net", "fromMe": False, "id": "dup-msg-001"},
            "message": {"conversation": "precio"},
        },
    }
    r1 = client.post("/whatsapp/webhook", json=payload)
    r2 = client.post("/whatsapp/webhook", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True


def test_vapi_webhook_returns_200():
    payload = {
        "message": {
            "type": "assistant-request",
            "call": {"id": "call-test-001", "metadata": {"client_id": "default"}},
        }
    }
    r = client.post("/vapi/webhook", json=payload)
    assert r.status_code == 200


def test_ads_status_returns_200():
    r = client.get("/ads/status")
    assert r.status_code == 200
    data = r.json()
    assert "meta_configured" in data
    assert data["endpoints"]["run_cycle"] == "POST /ads/run-cycle"


def test_ads_run_cycle_mocked(monkeypatch):
    async def fake_cycle(**kwargs):
        return {
            "ok": True,
            "ejecutado_at": "2026-07-29T00:00:00+00:00",
            "trends": {"mejor_oportunidad": None},
            "nueva_campana": {"skipped": True, "motivo": "test"},
            "reglas": {"pausadas": [], "escaladas": []},
            "errores": [],
            "resumen_whatsapp": "test",
            "whatsapp_enviado": False,
        }

    monkeypatch.setattr("app.routers.ads_router.run_ads_cycle", fake_cycle)

    r = client.post(
        "/ads/run-cycle",
        json={"launch_new_campaign": False, "evaluar_reglas": False},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True
