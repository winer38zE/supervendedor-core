"""Utilidades compartidas del panel admin Streamlit."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def ensure_project_root() -> Path:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT


def show_pb_notice(level: str, message: str) -> None:
    """Muestra avisos amigables de PocketBase (sin mencionar Supabase)."""
    if not message or level == "none":
        return
    if level == "warning":
        st.warning(message)
    else:
        st.info(message)


def require_pocketbase() -> tuple[bool, str]:
    ensure_project_root()
    from pb_store import pocketbase_ready

    ok, detail = pocketbase_ready()
    if not ok:
        st.warning(f"PocketBase no configurado: {detail}")
        st.info(
            "Configura `POCKETBASE_URL`, `POCKETBASE_EMAIL` y `POCKETBASE_PASSWORD` en `.env`."
        )
        st.stop()
    return ok, detail
