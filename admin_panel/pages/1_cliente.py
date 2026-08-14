import sys
from pathlib import Path

# pages/ → admin_panel/ en sys.path antes de bootstrap
_panel = Path(__file__).resolve().parents[1]
if str(_panel) not in sys.path:
    sys.path.insert(0, str(_panel))

import bootstrap  # noqa: F401

import pandas as pd
import streamlit as st

from pb_store import fetch_ventas_dataframe
from ui import render_ventas_gestion_table, require_pocketbase, show_pb_notice

st.set_page_config(page_title="Gestión de Clientes", page_icon="👥")

st.title("👥 Base de Datos de Clientes")
st.caption("Datos desde PocketBase · colección `ventas`")

require_pocketbase()

filtro = st.selectbox("Filtrar por Nicho", ["Todos", "Barbería", "Abogados", "Ventas"])

df, notice_level, notice_msg = fetch_ventas_dataframe()
show_pb_notice(notice_level, notice_msg)

if df.empty:
    st.info("No hay clientes registrados aún en PocketBase.")
else:
    if filtro != "Todos" and "producto" in df.columns:
        df = df[df["producto"].astype(str).str.contains(filtro, case=False, na=False)]
    if df.empty:
        st.info("No hay registros que coincidan con el filtro.")
    else:
        render_ventas_gestion_table(df, key_prefix="clientes")
