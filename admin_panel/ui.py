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


def render_ventas_gestion_table(df, *, key_prefix: str = "ventas", max_rows: int | None = None) -> None:
    """
    Tabla de ventas con columna Acciones (eliminar con confirmación en popover).
    Requiere columna `id` de PocketBase en el DataFrame.
    """
    import pandas as pd

    from pb_store import delete_venta

    if df is None or df.empty:
        st.info("No hay registros para mostrar.")
        return

    if "id" not in df.columns:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.warning("Los registros no incluyen ID — no se puede eliminar desde el panel.")
        return

    display_cols = [c for c in ("cliente", "producto", "monto", "estado") if c in df.columns]
    if not display_cols:
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    view = df.copy()
    if "monto" in view.columns:
        view = view.sort_values(by="monto", ascending=False)
    if max_rows:
        view = view.head(max_rows)

    header = st.columns(len(display_cols) + 1)
    labels = {"cliente": "Cliente", "producto": "Producto", "monto": "Monto", "estado": "Estado"}
    for i, col_name in enumerate(display_cols):
        header[i].markdown(f"**{labels.get(col_name, col_name.title())}**")
    header[-1].markdown("**Acciones**")

    for _, row in view.iterrows():
        record_id = str(row["id"])
        cols = st.columns(len(display_cols) + 1)
        for i, col_name in enumerate(display_cols):
            val = row[col_name]
            if col_name == "monto":
                cols[i].write(f"${float(val):,.0f} COP")
            else:
                cols[i].write(val if pd.notna(val) else "—")

        with cols[-1]:
            with st.popover("🗑️ Eliminar", key=f"{key_prefix}_pop_{record_id}"):
                st.warning(
                    f"¿Eliminar la venta de **{row.get('cliente', '—')}** "
                    f"({row.get('producto', '—')})? Esta acción no se puede deshacer."
                )
                if st.button(
                    "Sí, eliminar",
                    key=f"{key_prefix}_del_{record_id}",
                    type="primary",
                ):
                    result = delete_venta(record_id)
                    if result.get("ok"):
                        st.success(result.get("message", "Eliminado"))
                        st.rerun()
                    else:
                        st.error(result.get("message", "Error al eliminar"))
