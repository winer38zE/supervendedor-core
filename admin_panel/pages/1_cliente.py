import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from admin_panel.pb_store import fetch_ventas, pocketbase_ready

st.set_page_config(page_title="Gestión de Clientes", page_icon="👥")

st.title("👥 Base de Datos de Clientes")

pb_ok, pb_detail = pocketbase_ready()
if not pb_ok:
    st.warning(f"PocketBase no configurado: {pb_detail}")
    st.stop()

filtro = st.selectbox("Filtrar por Nicho", ["Todos", "Barbería", "Abogados", "Ventas"])

datos, notice_level, notice_msg = fetch_ventas()
if notice_msg and notice_level != "none":
    if notice_level == "warning":
        st.warning(notice_msg)
    else:
        st.info(notice_msg)

if datos:
    df = pd.DataFrame(datos)
    if filtro != "Todos" and "producto" in df.columns:
        df = df[df["producto"].astype(str).str.contains(filtro, case=False, na=False)]
    if df.empty:
        st.info("No hay registros que coincidan con el filtro.")
    else:
        st.dataframe(df, use_container_width=True)
else:
    st.info("No hay clientes registrados aún.")
