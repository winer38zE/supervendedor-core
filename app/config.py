# app/config.py
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str        = os.getenv("SUPABASE_URL", "https://tu-url.supabase.co")
    SUPABASE_KEY: str        = os.getenv("SUPABASE_KEY", "tu-key")

    # AI engines
    OPENAI_API_KEY: str      = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str   = os.getenv("ANTHROPIC_API_KEY", "")
    GROQ_API_KEY: str        = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str      = os.getenv("GEMINI_API_KEY", "")   # google-generativeai

    # Hunter — Google Maps Places API
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # WhatsApp — Evolution API (principal)
    EVOLUTION_API_URL: str   = os.getenv("EVOLUTION_API_URL", "")
    EVOLUTION_API_KEY: str   = os.getenv("EVOLUTION_API_KEY", "")
    EVOLUTION_INSTANCE: str  = os.getenv("EVOLUTION_INSTANCE", "super_vendedor")

    # WhatsApp — Meta Cloud API (alternativo)
    WHATSAPP_TOKEN: str      = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_ID: str   = os.getenv("WHATSAPP_PHONE_ID", "")

    # Single-tenant: identidad del dueño del sistema
    OWNER_ID: str            = os.getenv("OWNER_ID", "edwuar")

    # Google Calendar (mantener para agendar citas)
    GOOGLE_CALENDAR_ID: str  = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    CALENDAR_TIMEZONE: str   = os.getenv("CALENDAR_TIMEZONE", "America/Bogota")
    PUBLIC_URL: str          = os.getenv("PUBLIC_URL", "")

    class Config:
        env_file      = ".env"
        extra         = "ignore"   # ignorar vars del .env que no estén declaradas


settings = Settings()
