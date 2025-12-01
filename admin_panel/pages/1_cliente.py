import streamlit as st
from app.database import supabase

st.set_page_config(page_title="Gestión de Clientes", page_icon="👥")

st.title("👥 Base de Datos de Clientes")

if not supabase:
    st.error("Conecta Supabase primero.")
    st.stop()

# Filtros
filtro = st.selectbox("Filtrar por Nicho", ["Todos", "Barbería", "Abogados", "Ventas"])

# Traer datos
query = supabase.table("ventas").select("*")
if filtro != "Todos":
    query = query.ilike("producto", f"%{filtro}%") # Asumiendo que producto tiene el nicho

datos = query.execute().data

if datos:
    st.dataframe(datos, use_container_width=True)
else:
    st.info("No hay clientes registrados aún.")
    