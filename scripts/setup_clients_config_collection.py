#!/usr/bin/env python3
"""
scripts/setup_clients_config_collection.py
────────────────────────────────────────────────────────────────────────────────
Crea la colección PocketBase `clients_config` para automatización multi-tenant
de contenido (n8n loop + pipeline batch).

Uso (PowerShell):
    python scripts/setup_clients_config_collection.py

Requiere en .env:
    POCKETBASE_URL
    POCKETBASE_EMAIL
    POCKETBASE_PASSWORD
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

COLLECTION_NAME = "clients_config"

COLLECTION_PAYLOAD = {
    "name": COLLECTION_NAME,
    "type": "base",
    "fields": [
        {"name": "client_id", "type": "text", "required": True},
        {"name": "niche", "type": "text", "required": False},
        {"name": "brand_voice", "type": "text", "required": False},
        {"name": "product_focus", "type": "text", "required": False},
        {"name": "catalog_query", "type": "text", "required": False},
        {"name": "content_platform", "type": "text", "required": False},
        {"name": "content_caption", "type": "text", "required": False},
        {"name": "content_enabled", "type": "bool", "required": False},
        {"name": "content_webhook_url", "type": "text", "required": False},
        {"name": "launch_ads", "type": "bool", "required": False},
        {"name": "auto_producto", "type": "bool", "required": False},
        {"name": "use_trends", "type": "bool", "required": False},
        {"name": "single_pass", "type": "bool", "required": False},
        {"name": "skip_meta_create", "type": "bool", "required": False},
        {"name": "llm_preference", "type": "text", "required": False},
        {"name": "remix_level", "type": "number", "required": False},
        {"name": "default_views", "type": "number", "required": False},
        {"name": "default_likes", "type": "number", "required": False},
        {"name": "default_comments", "type": "number", "required": False},
        {"name": "default_shares", "type": "number", "required": False},
        {"name": "last_caption", "type": "text", "required": False},
        {"name": "last_metrics", "type": "json", "required": False},
    ],
    "indexes": [
        f"CREATE UNIQUE INDEX `idx_{COLLECTION_NAME}_client_id` ON `{COLLECTION_NAME}` (`client_id`)",
    ],
    "listRule": None,
    "viewRule": None,
    "createRule": None,
    "updateRule": None,
    "deleteRule": None,
}


def _authenticate(base_url: str) -> str:
    email = os.getenv("POCKETBASE_EMAIL", os.getenv("PB_ADMIN_EMAIL", "")).strip()
    password = os.getenv("POCKETBASE_PASSWORD", os.getenv("PB_ADMIN_PASSWORD", "")).strip()
    if not email or not password:
        raise SystemExit("ERROR: Configura POCKETBASE_EMAIL y POCKETBASE_PASSWORD en .env")

    endpoints = [
        f"{base_url}/api/collections/_superusers/auth-with-password",
        f"{base_url}/api/admins/auth-with-password",
    ]
    for url in endpoints:
        try:
            response = httpx.post(url, json={"identity": email, "password": password}, timeout=20)
            if response.status_code == 200:
                token = response.json().get("token")
                if token:
                    return token
        except httpx.HTTPError as exc:
            print(f"  auth {url}: {exc}")

    raise SystemExit("ERROR: No se pudo autenticar en PocketBase — revisa credenciales")


def _collection_exists(base_url: str, token: str, name: str) -> bool:
    response = httpx.get(
        f"{base_url}/api/collections/{name}",
        headers={"Authorization": token},
        timeout=20,
    )
    return response.status_code == 200


def main() -> int:
    base_url = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")
    print(f"PocketBase: {base_url}")
    print(f"Colección:  {COLLECTION_NAME}")

    token = _authenticate(base_url)
    print("Auth OK")

    if _collection_exists(base_url, token, COLLECTION_NAME):
        print(f"La colección '{COLLECTION_NAME}' ya existe — nada que hacer.")
        return 0

    response = httpx.post(
        f"{base_url}/api/collections",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json=COLLECTION_PAYLOAD,
        timeout=30,
    )

    if response.status_code not in (200, 201):
        print(f"ERROR {response.status_code}: {response.text[:800]}")
        return 1

    created = response.json()
    print("Colección creada:")
    print(json.dumps({"id": created.get("id"), "name": created.get("name")}, indent=2))
    print("\nListo. Crea un registro por tenant con client_id = tenant.id")
    return 0


if __name__ == "__main__":
    sys.exit(main())
