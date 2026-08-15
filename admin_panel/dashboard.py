import bootstrap  # noqa: F401 — configura sys.path (local + Streamlit Cloud)

import time

import pandas as pd
import plotly.express as px
import streamlit as st

from pb_store import fetch_ventas_dataframe, insert_venta
from api_store import fetch_live_channels_snapshot
from ui import render_ventas_gestion_table, require_pocketbase, show_pb_notice

st.set_page_config(
    page_title="Centro de Comando | ED NET PRO",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .metric-card {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 20px;
        border-radius: 10px;
        color: white;
    }
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        color: #00FF94 !important;
    }
    .channel-card-ok {
        border-left: 4px solid #00FF94;
        background: #14241c;
        padding: 14px 16px;
        border-radius: 8px;
        margin-bottom: 10px;
    }
    .channel-card-warn {
        border-left: 4px solid #FF4B4B;
        background: #241414;
        padding: 14px 16px;
        border-radius: 8px;
        margin-bottom: 10px;
    }
    .channel-title {
        font-size: 1.05rem;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .channel-meta {
        font-size: 0.85rem;
        color: #AAAAAA;
    }
</style>
""",
    unsafe_allow_html=True,
)


def _show_fetch_notice(level: str, message: str) -> None:
    show_pb_notice(level, message)


_, pb_detail = require_pocketbase()

st.title("⚡ ED NET PRO | Sistema de Control IA")
st.markdown("### Monitoreo en tiempo real de Agentes Vapi y WhatsApp")
st.caption(f"Backend: PocketBase · {pb_detail}")
st.divider()

df, notice_level, notice_msg = fetch_ventas_dataframe()
_show_fetch_notice(notice_level, notice_msg)

PRODUCTOS_PRECIOS: dict[str, int] = {
    "Tarjeta NFC": 150_000,
    "Chatbot IA": 350_000,
    "Suscripción IA": 200_000,
    "Consultoría B2B": 500_000,
}


def _sync_monto_simulador() -> None:
    """Actualiza el monto en session_state al cambiar el producto."""
    producto = st.session_state.get("sim_producto")
    if producto in PRODUCTOS_PRECIOS:
        st.session_state.sim_monto = PRODUCTOS_PRECIOS[producto]


def _render_canales_en_vivo() -> None:
    """Monitoreo de webhooks WhatsApp (Evolution) y Vapi conectados a ED NET PRO 3.0."""
    st.subheader("📡 Canales en vivo · WhatsApp & Vapi")
    st.caption("Estado consultado vía FastAPI `/api/v1/metrics/overview` y módulos MCP.")

    refresh = st.button("🔄 Actualizar estado de canales", key="refresh_channels")
    if refresh:
        st.cache_data.clear()

    snapshot = fetch_live_channels_snapshot()
    show_pb_notice(snapshot.get("notice_level", "none"), snapshot.get("notice_msg", ""))

    top1, top2, top3, top4 = st.columns(4)
    with top1:
        st.metric(
            "🌐 API FastAPI",
            "ONLINE" if snapshot["api_ok"] else "OFFLINE",
            delta=snapshot["api_base"],
        )
    with top2:
        st.metric("📦 Catálogo (muestra)", snapshot["catalogo_productos"])
    with top3:
        st.metric(
            "💰 Ventas API",
            f"$ {snapshot['ventas_api_ingresos']:,.0f}",
            delta=f"{snapshot['ventas_api_total']} registros",
        )
    with top4:
        st.metric("🏷️ Plataforma", f"v{snapshot['platform_version']}")

    cols = st.columns(3)
    for col, card in zip(cols, snapshot.get("cards", [])):
        css_class = "channel-card-ok" if card.get("status_ok") else "channel-card-warn"
        status_color = "#00FF94" if card.get("status_ok") else "#FF4B4B"
        webhooks_html = "<br>".join(f"• {url}" for url in card.get("webhooks", [])[:3])
        with col:
            st.markdown(
                f"""
<div class="{css_class}">
  <div class="channel-title">{card.get('icon', '')} {card.get('title', '')}</div>
  <div style="color:{status_color}; font-weight:700;">{card.get('status_label', '—')}</div>
  <div class="channel-meta">Instancia: {card.get('instance', '—')}</div>
  <div class="channel-meta">Módulo: {card.get('module', '—')}</div>
  <div class="channel-meta">Webhooks:<br>{webhooks_html}</div>
  <div class="channel-meta">Última consulta: {card.get('checked_at', '—')}</div>
</div>
""",
                unsafe_allow_html=True,
            )

    with st.expander("Detalle técnico (JSON)"):
        st.json(
            {
                "health": snapshot.get("health"),
                "canales": (snapshot.get("overview") or {}).get("canales"),
                "marketing": (snapshot.get("overview") or {}).get("marketing"),
            }
        )


def _render_simulador_ventas() -> None:
    if "sim_monto" not in st.session_state:
        st.session_state.sim_monto = PRODUCTOS_PRECIOS["Tarjeta NFC"]

    st.image("https://cdn-icons-png.flaticon.com/512/9626/9626622.png", width=80)
    st.header("🎮 Simulador de Ventas")
    st.write("Registra un cierre de prueba en PocketBase (`ventas`).")

    st.selectbox(
        "Producto",
        options=list(PRODUCTOS_PRECIOS.keys()),
        key="sim_producto",
        on_change=_sync_monto_simulador,
    )
    st.caption(f"Precio sugerido: ${PRODUCTOS_PRECIOS[st.session_state.sim_producto]:,} COP")

    with st.form("test_form"):
        cliente = st.text_input("Nombre Cliente", "Cliente Prueba")
        monto = st.number_input(
            "Monto (COP)",
            value=int(st.session_state.sim_monto),
            step=50_000,
            min_value=0,
        )
        btn = st.form_submit_button("🔥 SIMULAR CIERRE")

        if btn:
            producto = st.session_state.sim_producto
            if not cliente.strip():
                st.warning("El nombre del cliente es obligatorio.")
            elif monto <= 0:
                st.warning("El monto debe ser mayor a cero.")
            else:
                success, message, _record = insert_venta(
                    cliente=cliente.strip(),
                    producto=producto,
                    monto=monto,
                    estado="Cerrado",
                )
                if success:
                    st.session_state.sim_monto = int(monto)
                    st.success(message)
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.error(message)


total_ventas = float(df["monto"].sum()) if "monto" in df.columns and not df.empty else 0.0
total_leads = len(df)
ticket_promedio = total_ventas / total_leads if total_leads > 0 else 0.0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("💰 INGRESOS TOTALES", f"$ {total_ventas:,.0f} COP")
with col2:
    st.metric("🤖 VENTAS CERRADAS", f"{total_leads}", delta="Leads" if total_leads else None)
with col3:
    st.metric("💎 TICKET PROMEDIO", f"$ {ticket_promedio:,.0f} COP")
with col4:
    st.metric("🔥 ESTADO SISTEMA", "ONLINE", delta="Activo")

st.divider()

_render_canales_en_vivo()

st.divider()

c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📈 Rendimiento por Producto")
    if not df.empty and "producto" in df.columns and "monto" in df.columns:
        fig = px.bar(
            df,
            x="producto",
            y="monto",
            color="estado" if "estado" in df.columns else None,
            template="plotly_dark",
            title="Ingresos Generados",
            color_discrete_map={"Cerrado": "#00FF94", "Pendiente": "#FF4B4B"},
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos de productos aún. El gráfico aparecerá cuando registres ventas.")

with c2:
    st.subheader("📋 Últimas Transacciones")
    if not df.empty and "id" in df.columns:
        render_ventas_gestion_table(df, key_prefix="dashboard", max_rows=8)
    elif not df.empty:
        cols_show = [c for c in ("cliente", "monto", "estado") if c in df.columns]
        st.dataframe(
            df[cols_show].sort_values(by="monto", ascending=False),
            hide_index=True,
            height=300,
            use_container_width=True,
        )
    else:
        st.info("No hay transacciones registradas.")

with st.sidebar:
    _render_simulador_ventas()
