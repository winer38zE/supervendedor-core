from admin_panel.ui import ensure_project_root, require_pocketbase, show_pb_notice

ensure_project_root()

import pandas as pd
import streamlit as st

from admin_panel.pb_store import fetch_ventas_dataframe

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
        st.dataframe(df, use_container_width=True)
