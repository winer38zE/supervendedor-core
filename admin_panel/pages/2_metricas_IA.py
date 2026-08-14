import sys
from pathlib import Path

_panel = Path(__file__).resolve().parents[1]
if str(_panel) not in sys.path:
    sys.path.insert(0, str(_panel))

import bootstrap  # noqa: F401

import pandas as pd
import plotly.express as px
import streamlit as st

from pb_store import fetch_ventas_dataframe
from ui import render_ventas_gestion_table, require_pocketbase, show_pb_notice

st.set_page_config(page_title="Cerebro IA", page_icon="🧠")

st.title("🧠 Rendimiento del Auto-Aprendizaje")
st.caption("Métricas derivadas de ventas en PocketBase")

require_pocketbase()

st.markdown("### ¿Qué ha aprendido el sistema hoy?")

df, notice_level, notice_msg = fetch_ventas_dataframe()
show_pb_notice(notice_level, notice_msg)

if df.empty:
    col1, col2 = st.columns(2)
    col1.metric("Ventas IA (PocketBase)", "0")
    col2.metric("Ingresos totales", "$ 0 COP")
    st.info("Sin ventas en PocketBase todavía. Usa el simulador del dashboard principal.")
else:
    total_ventas = int(df["monto"].sum()) if "monto" in df.columns else 0
    n_cerradas = len(df[df["estado"] == "Cerrado"]) if "estado" in df.columns else len(df)

    col1, col2 = st.columns(2)
    col1.metric("Ventas registradas", str(n_cerradas))
    col2.metric("Ingresos totales", f"$ {total_ventas:,.0f} COP")

    st.divider()

    if "producto" in df.columns and "monto" in df.columns:
        por_producto = (
            df.groupby("producto", as_index=False)["monto"]
            .sum()
            .rename(columns={"monto": "Ingresos"})
        )
        fig = px.bar(
            por_producto,
            x="producto",
            y="Ingresos",
            title="Ingresos por producto (PocketBase)",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Los registros no incluyen campos producto/monto para graficar.")

    st.divider()
    st.subheader("📋 Registros de ventas")
    render_ventas_gestion_table(df, key_prefix="metricas")
