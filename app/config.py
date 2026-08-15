# app/config.py
import logging
import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── ED NET PRO 3.0 — Core ─────────────────────────────────────────────────
    ENV: str = os.getenv("ENV", "development")
    INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "")
    MASTER_KEY: str = os.getenv("MASTER_KEY", "")
    OWNER_ID: str = os.getenv("OWNER_ID", "edwuar")
    PORT: int = int(os.getenv("PORT", "8000"))
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "")

    # URLs internas (MCP, n8n, Vapi tools → FastAPI)
    SUPERVENDEDOR_URL: str = os.getenv(
        "SUPERVENDEDOR_URL",
        os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000"),
    )
    FASTAPI_BASE_URL: str = os.getenv("FASTAPI_BASE_URL", "http://127.0.0.1:8000")

    # ── Base de datos CRM ─────────────────────────────────────────────────────
    DB_BACKEND: str = os.getenv("DB_BACKEND", "pocketbase")
    POCKETBASE_URL: str = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090")
    POCKETBASE_EMAIL: str = os.getenv("POCKETBASE_EMAIL", os.getenv("PB_ADMIN_EMAIL", ""))
    POCKETBASE_PASSWORD: str = os.getenv("POCKETBASE_PASSWORD", os.getenv("PB_ADMIN_PASSWORD", ""))
    VENTAS_COLLECTION: str = os.getenv("VENTAS_COLLECTION", "ventas")
    PLANES_CONFIG_COLLECTION: str = os.getenv("PLANES_CONFIG_COLLECTION", "planes_config")

    # Supabase (legacy — solo si DB_BACKEND=supabase)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # AI engines
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Hunter — Google Maps Places API
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # WhatsApp — Evolution API (canal principal ED NET PRO 3.0)
    EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "")
    EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "")
    EVOLUTION_INSTANCE: str = os.getenv("EVOLUTION_INSTANCE", "super_vendedor")

    # Vapi — voz + tool-calls
    VAPI_WEBHOOK_SECRET: str = os.getenv("VAPI_WEBHOOK_SECRET", "")

    # WhatsApp — Meta Cloud API (alternativo)
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_ID: str = os.getenv("WHATSAPP_PHONE_ID", "")

    # Single-tenant (legacy SAAS)
    # OWNER_ID definido arriba en Core

    # Google Calendar
    GOOGLE_CALENDAR_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    CALENDAR_TIMEZONE: str = os.getenv("CALENDAR_TIMEZONE", "America/Bogota")

    # Meta Ads (marketing digital)
    META_ACCESS_TOKEN: str = os.getenv("META_ACCESS_TOKEN", "")

    # Avatares — ElevenLabs + Replicate
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    REPLICATE_AVATAR_MODEL: str = os.getenv("REPLICATE_AVATAR_MODEL", "wan-video/wan-2.2-s2v")
    AVATAR_TEMP_DIR: str = os.getenv("AVATAR_TEMP_DIR", "app/storage_vault/avatar_temp")
    AVATAR_JOBS_COLLECTION: str = os.getenv("AVATAR_JOBS_COLLECTION", "avatar_jobs")
    AVATAR_WEBHOOK_SECRET: str = os.getenv("AVATAR_WEBHOOK_SECRET", "")

    # Content & Outliers — SQLAlchemy
    CONTENT_DATABASE_URL: str = os.getenv(
        "CONTENT_DATABASE_URL",
        "sqlite:///./app/storage_vault/content_outliers.db",
    )
    CONTENT_GEMINI_MODEL: str = os.getenv("CONTENT_GEMINI_MODEL", "gemini-2.0-flash")
    CONTENT_OUTLIER_THRESHOLD: float = float(os.getenv("CONTENT_OUTLIER_THRESHOLD", "1.5"))
    CONTENT_COMPOSITE_THRESHOLD: float = float(os.getenv("CONTENT_COMPOSITE_THRESHOLD", "1.2"))
    CONTENT_DEFAULT_LLM: str = os.getenv("CONTENT_DEFAULT_LLM", "openai")
    CONTENT_WEBHOOK_SECRET: str = os.getenv("CONTENT_WEBHOOK_SECRET", "")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


def log_startup_warnings() -> None:
    """Warnings claros al arrancar — no falla silenciosamente."""
    if settings.DB_BACKEND == "pocketbase":
        if not settings.POCKETBASE_URL.strip():
            logger.warning("[Config] POCKETBASE_URL vacío — Hunter/CRM no persistirán datos")
        if not settings.POCKETBASE_EMAIL.strip():
            logger.warning("[Config] POCKETBASE_EMAIL vacío — auth PocketBase fallará")
        if not settings.POCKETBASE_PASSWORD.strip():
            logger.warning("[Config] POCKETBASE_PASSWORD vacío — auth PocketBase fallará")

    if settings.ENV == "production" and not settings.INTERNAL_API_KEY.strip():
        logger.warning("[Config] INTERNAL_API_KEY vacía en producción — endpoints POST desprotegidos")

    if settings.ENV == "production" and not settings.MASTER_KEY.strip():
        logger.warning("[Config] MASTER_KEY vacía en producción — admin SAAS desprotegido")

    if settings.ENV == "production" and not settings.EVOLUTION_API_KEY.strip():
        logger.warning("[Config] EVOLUTION_API_KEY vacía en producción — webhook WhatsApp abierto")

    if settings.ENV == "production" and not settings.VAPI_WEBHOOK_SECRET.strip():
        logger.warning("[Config] VAPI_WEBHOOK_SECRET vacío en producción — webhook Vapi abierto")

    if not settings.ELEVENLABS_API_KEY.strip():
        logger.warning("[Config] ELEVENLABS_API_KEY vacía — módulo de avatares TTS desactivado")

    if not settings.REPLICATE_API_TOKEN.strip():
        logger.warning("[Config] REPLICATE_API_TOKEN vacío — módulo de avatares video desactivado")
