#!/usr/bin/env python3
"""
scripts/seed_clients_config_example.py
────────────────────────────────────────────────────────────────────────────────
Crea o actualiza un registro de ejemplo en clients_config para el tenant CHAT_TENANT_ID.

Uso (PowerShell):
    python scripts/seed_clients_config_example.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _load_setup_module():
    spec = importlib.util.spec_from_file_location(
        "setup_clients_config",
        str(ROOT / "scripts" / "setup_clients_config_collection.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _example_payload(client_id: str) -> dict:
    return {
        "client_id": client_id,
        "niche": "moda femenina accesible Colombia",
        "brand_voice": "cercana, colombiana, orientada a ventas por WhatsApp",
        "product_focus": "vestidos y enterizos verano",
        "catalog_query": "vestido verano mujer",
        "content_platform": "instagram",
        "content_caption": (
            "El error que cometen el 90% de las tiendas online al vender por WhatsApp..."
        ),
        "content_enabled": True,
        "content_webhook_url": os.getenv("N8N_WEBHOOK_BASE_URL", "").rstrip("/")
        + "/webhook/content-finished",
        "launch_ads": False,
        "auto_producto": True,
        "use_trends": True,
        "single_pass": True,
        "skip_meta_create": True,
        "llm_preference": "openai",
        "remix_level": 0.5,
        "default_views": 100000,
        "default_likes": 8000,
        "default_comments": 400,
        "default_shares": 1200,
        "last_caption": "Caption viral de referencia para remix",
        "last_metrics": {
            "views": 100000,
            "likes": 8000,
            "comments": 400,
            "shares": 1200,
        },
    }


def main() -> int:
    base_url = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")
    client_id = os.getenv("CHAT_TENANT_ID", "edwuar").strip() or "edwuar"
    setup = _load_setup_module()
    token = setup._authenticate(base_url)
    headers = {"Authorization": token}

    print(f"PocketBase: {base_url}")
    print(f"Tenant:     {client_id}")

    tenants_resp = httpx.get(
        f"{base_url}/api/collections/tenants/records",
        params={"perPage": 5},
        headers=headers,
        timeout=30,
    )
    if tenants_resp.status_code == 200:
        items = tenants_resp.json().get("items", [])
        print(f"\nTenants encontrados ({len(items)}):")
        for t in items:
            print(f"  - {t.get('id')} | {t.get('nombre', '?')} | estado={t.get('estado')}")
    else:
        print(f"\nWARN: no se pudo listar tenants ({tenants_resp.status_code})")

    payload = _example_payload(client_id)
    find_resp = httpx.get(
        f"{base_url}/api/collections/clients_config/records",
        params={"filter": f'client_id="{client_id}"', "perPage": 1},
        headers=headers,
        timeout=30,
    )
    existing_id = None
    if find_resp.status_code == 200 and find_resp.json().get("items"):
        existing_id = find_resp.json()["items"][0]["id"]

    if existing_id:
        resp = httpx.patch(
            f"{base_url}/api/collections/clients_config/records/{existing_id}",
            json=payload,
            headers=headers,
            timeout=30,
        )
        action = "Actualizado"
    else:
        resp = httpx.post(
            f"{base_url}/api/collections/clients_config/records",
            json=payload,
            headers=headers,
            timeout=30,
        )
        action = "Creado"

    if resp.status_code not in (200, 201):
        print(f"\nERROR {resp.status_code}: {resp.text[:800]}")
        return 1

    record = resp.json()
    print(f"\n{action} clients_config:")
    print(json.dumps({"id": record.get("id"), "client_id": record.get("client_id")}, indent=2))
    print("\nListo. Prueba: GET /api/v1/content/tenants/active")
    return 0


if __name__ == "__main__":
    sys.exit(main())
