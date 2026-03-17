import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# app/config.py
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://tu-url.supabase.co")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "tu-key")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "") # Añadido para Zeus
    
    class Config:
        env_file = ".env"

settings = Settings()

