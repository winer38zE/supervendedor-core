"""
admin_panel/pb_store.py
────────────────────────────────────────────────────────────────────────────────
Acceso a PocketBase para el dashboard Streamlit (colección ventas).

Variables (.env):
  POCKETBASE_URL, POCKETBASE_EMAIL, POCKETBASE_PASSWORD
  VENTAS_COLLECTION  (default: ventas)
  PLANES_CONFIG_COLLECTION  (default: planes_config)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.database import pocketbase_client as pb  # noqa: E402 — PocketBase HTTP, no Supabase

VENTAS_COLLECTION = os.getenv("VENTAS_COLLECTION", "ventas").strip() or "ventas"
PLANES_CONFIG_COLLECTION = os.getenv("PLANES_CONFIG_COLLECTION", "planes_config").strip() or "planes_config"

NoticeLevel = Literal["info", "warning", "none"]


def pocketbase_ready() -> tuple[bool, str]:
    """Verifica URL + credenciales admin."""
    url = os.getenv("POCKETBASE_URL", "").strip()
    email = os.getenv("POCKETBASE_EMAIL", os.getenv("PB_ADMIN_EMAIL", "")).strip()
    password = os.getenv("POCKETBASE_PASSWORD", os.getenv("PB_ADMIN_PASSWORD", "")).strip()

    if not url:
        return False, "Falta POCKETBASE_URL en .env"
    if not email or not password:
        return False, "Faltan POCKETBASE_EMAIL y POCKETBASE_PASSWORD en .env"

    token = pb.authenticate()
    if not token:
        return False, "No se pudo autenticar en PocketBase — revisa credenciales"
    return True, url


def _safe_json(response: Any) -> dict[str, Any] | None:
    """Parsea JSON solo si la respuesta HTTP fue exitosa (GET 200)."""
    if response is None or getattr(response, "status_code", 0) != 200:
        return None
    try:
        data = response.json()
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None


def _parse_pb_write_response(response: Any) -> tuple[int, dict[str, Any] | None, str]:
    """Extrae status, record JSON y texto de error de una respuesta POST/PATCH."""
    status = getattr(response, "status_code", 0)
    if status in (200, 201):
        try:
            body = response.json()
            if isinstance(body, dict):
                return status, body, ""
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        return status, None, ""
    detail = ""
    try:
        detail = response.text[:400]
    except Exception:
        pass
    return status, None, detail


def _extract_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    return []


def _friendly_fetch_notice(status_code: int) -> tuple[NoticeLevel, str]:
    if status_code == 404:
        return (
            "warning",
            f"La colección «{VENTAS_COLLECTION}» aún no existe. "
            "Puedes crearla con: python scripts/setup_ventas_collection.py",
        )
    if status_code == 400:
        return (
            "info",
            "No hay ventas registradas todavía o la colección está vacía. "
            "Usa el simulador del panel lateral para registrar la primera.",
        )
    if status_code in (401, 403):
        return (
            "warning",
            "Sin permisos para leer ventas. Revisa las reglas de la colección en PocketBase.",
        )
    return (
        "info",
        "Mostrando panel en modo demo (sin datos de ventas por ahora).",
    )


def fetch_ventas(*, per_page: int = 500) -> tuple[list[dict[str, Any]], NoticeLevel, str]:
    """
    Lista registros de ventas.

    Siempre devuelve una lista (posiblemente vacía). Nunca lanza excepción.
    El segundo valor indica si mostrar aviso: info | warning | none.
    """
    per_page = max(1, min(int(per_page), 500))
    base_path = f"/api/collections/{VENTAS_COLLECTION}/records"

    param_variants: list[dict[str, Any]] = [
        {"perPage": per_page, "sort": "-created"},
        {"perPage": per_page, "sort": "-@created"},
        {"perPage": per_page},
        {"page": 1, "perPage": min(per_page, 50)},
    ]

    last_status = 0
    for params in param_variants:
        try:
            response = pb.pb_request("GET", base_path, params=params)
        except Exception:
            continue

        last_status = getattr(response, "status_code", 0)
        payload = _safe_json(response)
        if payload is not None:
            items = _extract_items(payload)
            if items:
                return items, "none", ""
            return (
                items,
                "info",
                "PocketBase conectado. Aún no hay ventas — registra la primera con el simulador.",
            )

        if last_status not in (400, 404, 422):
            break

    level, message = _friendly_fetch_notice(last_status or 400)
    return [], level, message


def fetch_ventas_dataframe():
    """Atajo: ventas como DataFrame + aviso PocketBase."""
    import pandas as pd

    items, level, message = fetch_ventas()
    if not items:
        return pd.DataFrame(columns=["cliente", "producto", "monto", "estado"]), level, message
    df = pd.DataFrame(items)
    if "monto" in df.columns:
        df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0)
    return df, level, message


def delete_record(collection: str, record_id: str) -> dict[str, Any]:
    """Elimina un registro de PocketBase por ID."""
    rid = str(record_id).strip()
    if not rid:
        return {"ok": False, "message": "ID de registro inválido.", "status_code": 0}

    ready, detail = pocketbase_ready()
    if not ready:
        return {"ok": False, "message": f"PocketBase no disponible: {detail}", "status_code": 0}

    try:
        response = pb.pb_request(
            "DELETE",
            f"/api/collections/{collection}/records/{rid}",
        )
    except Exception as exc:
        return {"ok": False, "message": f"Error de conexión con PocketBase: {exc}", "status_code": 0}

    status = getattr(response, "status_code", 0)
    if status in (200, 204):
        return {
            "ok": True,
            "message": "Registro eliminado correctamente.",
            "status_code": status,
        }

    detail = ""
    try:
        detail = response.text[:200]
    except Exception:
        pass

    if status == 404:
        message = "El registro ya no existe o fue eliminado."
    else:
        message = f"No se pudo eliminar (código {status}). {detail}".strip()

    return {"ok": False, "message": message, "status_code": status}


def delete_venta(record_id: str) -> dict[str, Any]:
    """Elimina una venta de la colección ventas."""
    return delete_record(VENTAS_COLLECTION, record_id)


def insert_venta(
    *,
    cliente: str,
    producto: str,
    monto: float | int,
    estado: str = "Cerrado",
) -> tuple[bool, str, dict[str, Any] | None]:
    """POST a PocketBase — simulador de cierre de venta."""
    payload = {
        "cliente": cliente.strip(),
        "producto": producto.strip(),
        "monto": float(monto),
        "estado": estado.strip() or "Cerrado",
    }
    try:
        response = pb.pb_request(
            "POST",
            f"/api/collections/{VENTAS_COLLECTION}/records",
            json=payload,
        )
    except Exception as exc:
        return False, f"No se pudo conectar con PocketBase: {exc}", None

    status, data, detail = _parse_pb_write_response(response)
    if status in (200, 201):
        if isinstance(data, dict):
            return True, "¡Venta registrada en PocketBase!", data
        return True, "¡Venta registrada!", None

    if status == 404:
        return (
            False,
            f"La colección «{VENTAS_COLLECTION}» no existe. Ejecuta scripts/setup_ventas_collection.py",
            None,
        )
    if status == 400:
        return False, "Datos inválidos. Revisa cliente, producto y monto.", None

    detail = ""
    try:
        detail = response.text[:200]
    except Exception:
        pass
    return False, f"No se pudo guardar la venta (código {status}). {detail}".strip(), None


def _post_record(collection: str, payload: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        response = pb.pb_request(
            "POST",
            f"/api/collections/{collection}/records",
            json=payload,
        )
    except Exception as exc:
        return False, f"No se pudo conectar con PocketBase: {exc}", None

    status = getattr(response, "status_code", 0)
    if status in (200, 201):
        data = _safe_json(response)
        if isinstance(data, dict):
            return True, "Guardado correctamente en PocketBase.", data
        return True, "Guardado correctamente.", None

    if status == 404:
        return (
            False,
            f"La colección «{collection}» no existe. Ejecuta el script de migración correspondiente.",
            None,
        )
    if status == 400:
        return False, "Datos inválidos para PocketBase. Revisa los campos enviados.", None

    detail = ""
    try:
        detail = response.text[:200]
    except Exception:
        pass
    return False, f"No se pudo guardar (código {status}). {detail}".strip(), None


def _find_planes_record(client_id: str) -> dict[str, Any] | None:
    """Busca registro por client_id (fallback sin filter si PB devuelve 400)."""
    collection = PLANES_CONFIG_COLLECTION
    cid = client_id.strip()

    for sort in ("-created", "-@created", ""):
        params: dict[str, Any] = {"perPage": 200, "page": 1}
        if sort:
            params["sort"] = sort
        try:
            response = pb.pb_request(
                "GET",
                f"/api/collections/{collection}/records",
                params=params,
            )
        except Exception:
            continue
        payload = _safe_json(response)
        if payload is None:
            continue
        for row in _extract_items(payload):
            if str(row.get("client_id", "")).strip() == cid:
                return row
    return None


def save_planes_config(data: dict) -> dict[str, Any]:
    """
    POST/PATCH configuración de planes en PocketBase (colección planes_config).

    Args:
        data: dict con client_id, usar_bundle, planes_seleccionados,
              total_mes, valor_regular, descuento, detalle, etc.

    Returns:
        {"ok": bool, "message": str, "status_code": int, "record": dict|None}
    """
    collection = PLANES_CONFIG_COLLECTION

    if not isinstance(data, dict) or not data:
        return {
            "ok": False,
            "message": "Payload vacío o inválido.",
            "status_code": 0,
            "record": None,
        }

    payload = dict(data)
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        return {
            "ok": False,
            "message": "El campo client_id es obligatorio.",
            "status_code": 0,
            "record": None,
        }

    payload["client_id"] = client_id
    for num_field in ("total_mes", "valor_regular", "descuento"):
        if num_field in payload and payload[num_field] is not None:
            payload[num_field] = float(payload[num_field])

    ready, detail = pocketbase_ready()
    if not ready:
        return {
            "ok": False,
            "message": f"PocketBase no disponible: {detail}",
            "status_code": 0,
            "record": None,
        }

    try:
        existing = _find_planes_record(client_id)
        if existing:
            response = pb.pb_request(
                "PATCH",
                f"/api/collections/{collection}/records/{existing['id']}",
                json=payload,
            )
        else:
            response = pb.pb_request(
                "POST",
                f"/api/collections/{collection}/records",
                json=payload,
            )
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Error de conexión con PocketBase: {exc}",
            "status_code": 0,
            "record": None,
        }

    status_code, record, error_text = _parse_pb_write_response(response)

    if status_code in (200, 201):
        total = payload.get("total_mes", 0)
        return {
            "ok": True,
            "message": f"Configuración guardada: ${float(total):,.0f} COP/mes.",
            "status_code": status_code,
            "record": record,
        }

    if status_code == 404:
        message = (
            f"La colección «{collection}» no existe. "
            "Ejecuta: python scripts/setup_planes_config_collection.py"
        )
    elif status_code == 400:
        message = f"Datos inválidos. {error_text}".strip() or "Revisa los campos enviados."
    else:
        message = f"No se pudo guardar (código {status_code}). {error_text}".strip()

    return {
        "ok": False,
        "message": message,
        "status_code": status_code,
        "record": None,
    }


__all__ = [
    "delete_record",
    "delete_venta",
    "fetch_ventas",
    "fetch_ventas_dataframe",
    "insert_venta",
    "pocketbase_ready",
    "save_planes_config",
    "PLANES_CONFIG_COLLECTION",
    "VENTAS_COLLECTION",
]
