#!/usr/bin/env python3
"""
scripts/setup_ventas_collection.py
────────────────────────────────────────────────────────────────────────────────
Crea la colección PocketBase `ventas` para el dashboard Streamlit.

Uso (PowerShell):
    python scripts/setup_ventas_collection.py
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

COLLECTION_NAME = os.getenv("VENTAS_COLLECTION", "ventas").strip() or "ventas"

COLLECTION_PAYLOAD = {
    "name": COLLECTION_NAME,
    "type": "base",
    "fields": [
        {"name": "cliente", "type": "text", "required": True},
        {"name": "producto", "type": "text", "required": True},
        {"name": "monto", "type": "number", "required": True},
        {"name": "estado", "type": "text", "required": False},
    ],
    "indexes": [],
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

    for path in ("/api/collections/_superusers/auth-with-password", "/api/admins/auth-with-password"):
        try:
            response = httpx.post(
                f"{base_url}{path}",
                json={"identity": email, "password": password},
                timeout=20,
            )
            if response.status_code == 200:
                token = response.json().get("token")
                if token:
                    return token
        except httpx.HTTPError as exc:
            print(f"  auth {path}: {exc}")

    raise SystemExit("ERROR: No se pudo autenticar en PocketBase")


def main() -> int:
    base_url = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")
    print(f"PocketBase: {base_url}")
    print(f"Colección:  {COLLECTION_NAME}")

    token = _authenticate(base_url)
    headers = {"Authorization": token}

    exists = httpx.get(
        f"{base_url}/api/collections/{COLLECTION_NAME}",
        headers=headers,
        timeout=20,
    )
    if exists.status_code == 200:
        print(f"La colección '{COLLECTION_NAME}' ya existe.")
        return 0

    response = httpx.post(
        f"{base_url}/api/collections",
        headers={**headers, "Content-Type": "application/json"},
        json=COLLECTION_PAYLOAD,
        timeout=30,
    )
    if response.status_code not in (200, 201):
        print(f"ERROR {response.status_code}: {response.text[:800]}")
        return 1

    created = response.json()
    print("Colección creada:")
    print(json.dumps({"id": created.get("id"), "name": created.get("name")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
