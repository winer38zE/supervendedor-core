import streamlit as st
import pandas as pd
import plotly.express as px
from app.database import supabase

st.set_page_config(page_title="Cerebro IA", page_icon="🧠")

st.title("🧠 Rendimiento del Auto-Aprendizaje")

st.markdown("### ¿Qué ha aprendido el sistema hoy?")

# Simulación de datos de aprendizaje (hasta que tengas datos reales)
col1, col2 = st.columns(2)
col1.metric("Nuevas Frases Aprendidas", "5", "+2 hoy")
col2.metric("Tasa de Precisión", "89%", "+1.5%")

st.divider()

# Gráfico de Efectividad
data_ia = pd.DataFrame({
    'Día': ['Lun', 'Mar', 'Mie', 'Jue', 'Vie'],
    'Ventas IA': [2, 3, 5, 8, 12],
    'Ventas Manuales': [5, 4, 3, 2, 1]
})

fig = px.line(data_ia, x='Día', y=['Ventas IA', 'Ventas Manuales'], 
              title="IA vs Humano (Semana Actual)", markers=True)
st.plotly_chart(fig)

st.success("🤖 El sistema está optimizando los guiones automáticamente cada 24h.")