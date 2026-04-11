"""
app/database/__init__.py
Paquete de base de datos.

Re-exporta la API pública de supabase_client para mantener compatibilidad
con todos los imports existentes en el proyecto:

    from app.database import guardar_venta           # legado vapi_handler
    from app.database import guardar_llamada_completa # nuevo
    from app.database import get_client, SupabaseDB   # acceso directo
"""

from .supabase_client import (
    get_client,
    SupabaseDB,
    guardar_venta,
    upsert_lead_crm,
    insert_historial_llamada,
    guardar_llamada_completa,
)

__all__ = [
    "get_client",
    "SupabaseDB",
    "guardar_venta",
    "upsert_lead_crm",
    "insert_historial_llamada",
    "guardar_llamada_completa",
]
