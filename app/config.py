import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

class Settings(BaseSettings):
    # --- TUS LLAVES DE SUPABASE ---
    # Reemplaza el texto entre comillas con tus claves reales
    SUPABASE_URL: str = "https://pbuhisckvkyugkujovus.supabase.co"
    SUPABASE_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBidWhpc2Nrdmt5dWdrdWpvdnVzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjQ1MzIwNDEsImV4cCI6MjA4MDEwODA0MX0.hdGLppPIQmzggImyXX1q1rTP7Vn_rXAfcr58-IK9P40"
    
    # --- TU CEREBRO (OPENAI) ---
    # Si tienes clave de OpenAI, pégala aquí. Si no, déjala vacía por ahora.
    OPENAI_API_KEY: str = "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"

    class Config:
        env_file = ".env"

settings = Settings()