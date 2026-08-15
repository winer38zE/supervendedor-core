"""
app/database/pocketbase_client.py
────────────────────────────────────────────────────────────────────────────────
Cliente HTTP PocketBase (VPS) con autenticación admin/superuser.

Variables de entorno:
  POCKETBASE_URL       → http://178.105.48.103:8090
  POCKETBASE_EMAIL     → correo admin
  POCKETBASE_PASSWORD  → contraseña admin
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_token: Optional[str] = None


def _base_url() -> str:
    return os.environ.get("POCKETBASE_URL", "http://178.105.48.103:8090").rstrip("/")


def _credentials() -> tuple[str, str]:
    email = os.environ.get("POCKETBASE_EMAIL", os.environ.get("PB_ADMIN_EMAIL", ""))
    password = os.environ.get("POCKETBASE_PASSWORD", os.environ.get("PB_ADMIN_PASSWORD", ""))
    return email, password


def authenticate(force: bool = False) -> Optional[str]:
    """Obtiene token admin. Cache en memoria por proceso."""
    global _token
    if _token and not force:
        return _token

    email, password = _credentials()
    if not email or not password:
        logger.error("[PocketBase] Faltan POCKETBASE_EMAIL / POCKETBASE_PASSWORD")
        return None

    base = _base_url()
    payloads = [
        (f"{base}/api/collections/_superusers/auth-with-password", {"identity": email, "password": password}),
        (f"{base}/api/admins/auth-with-password", {"identity": email, "password": password}),
    ]

    for url, body in payloads:
        try:
            r = httpx.post(url, json=body, timeout=15)
            if r.status_code == 200:
                _token = r.json().get("token")
                logger.info("[PocketBase] Autenticación OK")
                return _token
        except Exception as e:
            logger.debug(f"[PocketBase] auth {url}: {e}")

    logger.error("[PocketBase] No se pudo autenticar — revisa URL, email y contraseña")
    return None


def _headers() -> dict[str, str]:
    token = authenticate()
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = token
    return h


def pb_request(
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    retry_auth: bool = True,
) -> httpx.Response:
    url = f"{_base_url()}{path}"
    r = httpx.request(method, url, headers=_headers(), params=params, json=json, timeout=30)
    if r.status_code == 401 and retry_auth:
        authenticate(force=True)
        r = httpx.request(method, url, headers=_headers(), params=params, json=json, timeout=30)
    return r


def _log_pb_error(action: str, collection: str, status: int, text: str, *, quiet: bool) -> None:
    if status == 404 and quiet:
        logger.debug("[PocketBase] %s %s: colección no encontrada (404)", action, collection)
        return
    logger.warning(f"[PocketBase] {action} {collection}: {status} {text[:200]}")


def list_records(
    collection: str,
    *,
    filter_expr: str = "",
    sort: str = "-created",
    page: int = 1,
    per_page: int = 50,
    quiet: bool = False,
) -> list[dict]:
    base_params: dict[str, Any] = {"page": page, "perPage": per_page}
    param_variants: list[dict[str, Any]] = []
    if sort:
        param_variants.append({**base_params, "sort": sort})
        if sort != "-@created":
            param_variants.append({**base_params, "sort": "-@created"})
    param_variants.append(dict(base_params))

    path = f"/api/collections/{collection}/records"
    last_status = 0
    last_text = ""

    for params in param_variants:
        if filter_expr:
            params = {**params, "filter": filter_expr}
        r = pb_request("GET", path, params=params)
        if r.status_code == 200:
            return r.json().get("items", [])
        last_status = r.status_code
        last_text = r.text
        if r.status_code not in (400, 422):
            break

    _log_pb_error("list", collection, last_status, last_text, quiet=quiet)
    return []


def collection_exists(collection: str) -> bool:
    """Comprueba si la colección existe (GET records con perPage=1)."""
    r = pb_request(
        "GET",
        f"/api/collections/{collection}/records",
        params={"page": 1, "perPage": 1},
    )
    return r.status_code == 200


def get_one_record(collection: str, record_id: str) -> Optional[dict]:
    r = pb_request("GET", f"/api/collections/{collection}/records/{record_id}")
    if r.status_code == 200:
        return r.json()
    return None


def create_record(collection: str, data: dict, *, quiet: bool = False) -> Optional[dict]:
    r = pb_request("POST", f"/api/collections/{collection}/records", json=data)
    if r.status_code in (200, 201):
        return r.json()
    _log_pb_error("create", collection, r.status_code, r.text, quiet=quiet)
    return None


def update_record(
    collection: str, record_id: str, data: dict, *, quiet: bool = False
) -> Optional[dict]:
    r = pb_request("PATCH", f"/api/collections/{collection}/records/{record_id}", json=data)
    if r.status_code == 200:
        return r.json()
    _log_pb_error("update", collection, r.status_code, r.text, quiet=quiet)
    return None


def upsert_by_filter(
    collection: str,
    data: dict,
    unique_fields: list[str],
    *,
    quiet: bool = False,
) -> Optional[dict]:
    """Busca por campos únicos; actualiza o crea."""
    parts = [f"({f}={_quote(data.get(f, ''))})" for f in unique_fields if data.get(f) is not None]
    if not parts:
        return create_record(collection, data, quiet=quiet)

    filt = "&&".join(parts)
    existing = list_records(collection, filter_expr=filt, per_page=1, quiet=quiet)
    if existing:
        rid = existing[0]["id"]
        return update_record(collection, rid, data, quiet=quiet)
    return create_record(collection, data, quiet=quiet)


def _quote(value: Any) -> str:
    if value is None:
        return "''"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("'", "\\'")
    return f"'{s}'"


def health_check() -> dict:
    email, _ = _credentials()
    token = authenticate()
    return {
        "backend": "pocketbase",
        "url": _base_url(),
        "authenticated": bool(token),
        "email_configured": bool(email),
    }
