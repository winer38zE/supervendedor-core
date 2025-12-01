# ⚡ Super Vendedor IA - ED NET PRO

Plataforma de Ingeniería de Ventas Automatizada con Inteligencia Artificial, Voz en Tiempo Real y Análisis Predictivo.

## 🏗️ Arquitectura del Sistema
Este sistema utiliza una arquitectura de microservicios moderna ("Agencia USA"):

- **Cerebro Conversacional:** Vapi.ai (Voz) + Flowise (Lógica RAG)
- **Motor Backend:** Python FastAPI (Procesamiento asíncrono)
- **Memoria Persistente:** Supabase (PostgreSQL + Realtime)
- **Centro de Comando:** Streamlit (Dashboard de Métricas en Vivo)
- **Auto-Aprendizaje:** OpenAI GPT-4o (Optimización de Prompts)

## 🚀 Instalación y Despliegue

### 1. Requisitos Previos
- Python 3.9+
- Cuenta en Supabase
- API Keys de OpenAI y Vapi

### 2. Instalación Local
```bash
# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
# Renombrar .env.example a .env y colocar claves