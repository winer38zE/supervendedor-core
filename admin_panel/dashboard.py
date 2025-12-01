import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
import time

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Centro de Comando | ED NET PRO",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS VISUALES (MODO AGENCIA USA) ---
st.markdown("""
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
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 🔑 AQUÍ PEGAS TUS CLAVES DE SUPABASE (SIN BORRAR LAS COMILLAS)
# ---------------------------------------------------------
SUPABASE_URL = "https://pbuhisckvkyugkujovus.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBidWhpc2Nrdmt5dWdrdWpvdnVzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQ1MzIwNDEsImV4cCI6MjA4MDEwODA0MX0.hdGLppPIQmzggImyXX1q1rTP7Vn_rXAfcr58-IK9P40"

# --- CONEXIÓN A LA MEMORIA ---
@st.cache_resource
def init_db():
    try:
        if "PEGA_TU" in SUPABASE_URL: # Verificación de seguridad
            return None
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        return None

supabase = init_db()

# --- TÍTULO PRINCIPAL ---
st.title("⚡ ED NET PRO | Sistema de Control IA")
st.markdown("### Monitoreo en tiempo real de Agentes Vapi y WhatsApp")
st.divider()

# --- VERIFICACIÓN DE CONEXIÓN ---
if not supabase:
    st.error("⚠️ FALTAN LAS CLAVES: Abre el código en VS Code y pega la URL y API Key de Supabase en las líneas 35 y 36.")
    st.stop()

# --- TRAER DATOS EN VIVO ---
try:
    response = supabase.table("ventas").select("*").execute()
    datos = response.data
except:
    st.error("⚠️ Error: No se encuentra la tabla 'ventas' en Supabase. ¿Ya la creaste?")
    st.stop()

if datos:
    df = pd.DataFrame(datos)
    
    # Cálculos Matemáticos (KPIs)
    total_ventas = df['monto'].sum()
    total_leads = len(df)
    ticket_promedio = total_ventas / total_leads if total_leads > 0 else 0
    
    # --- FILA 1: MÉTRICAS ---
    col1, col2, col3, col4 = st.columns(4)
    
    st.metric("💰 INGRESOS TOTALES", f"$ {total_ventas:,.0f} COP")
    with col2:
        st.metric("🤖 VENTAS CERRADAS", f"{total_leads}", delta="Leads")
    with col3:
         st.metric("💎 TICKET PROMEDIO", f"$ {ticket_promedio:,.0f} COP")
    with col4:
        st.metric("🔥 ESTADO SISTEMA", "ONLINE", delta="Activo")

    st.divider()

    # --- FILA 2: GRÁFICOS DE INGENIERÍA ---
    c1, c2 = st.columns([2, 1])
    
    with c1:
        st.subheader("📈 Rendimiento por Producto")
        if not df.empty:
            fig = px.bar(df, x="producto", y="monto", color="estado", 
                         template="plotly_dark", title="Ingresos Generados",
                         color_discrete_map={"Cerrado": "#00FF94", "Pendiente": "#FF4B4B"})
            st.plotly_chart(fig, use_container_width=True)
            
    with c2:
        st.subheader("📋 Últimas Transacciones")
        if not df.empty:
            # Mostrar tabla limpia
            st.dataframe(
                df[['cliente', 'monto', 'estado']].sort_values(by='monto', ascending=False),
                hide_index=True,
                height=300,
                use_container_width=True
            )

else:
    st.info("👋 El sistema está conectado. Esperando la primera venta de la IA...")

# --- BARRA LATERAL: CONTROL MANUAL (SIMULADOR) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/9626/9626622.png", width=80)
    st.header("🎮 Simulador de Ventas")
    st.write("Usa esto para probar que el gráfico se mueve.")
    
    with st.form("test_form"):
        cliente = st.text_input("Nombre Cliente", "Cliente Prueba")
        prod = st.selectbox("Producto", ["Tarjeta NFC", "Suscripción IA", "Consultoría B2B"])
        monto = st.number_input("Monto (COP)", value=150000, step=50000)
        btn = st.form_submit_button("🔥 SIMULAR CIERRE")
        
        if btn:
            try:
                supabase.table("ventas").insert({
                    "cliente": cliente,
                    "producto": prod,
                    "monto": monto,
                    "estado": "Cerrado"
                }).execute()
                st.success("¡Venta registrada!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Error al guardar: {e}")