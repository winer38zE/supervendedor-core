from supabase import create_client
from .config import settings

# Conexión Segura usando las claves de config.py
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

def guardar_venta(cliente, monto, producto, estado, origen):
    """Guarda la venta en la nube de Supabase"""
    data = {
        "cliente": cliente,
        "monto": monto,
        "producto": producto,
        "estado": estado,
        "origen": origen
    }
    # Intentar escribir en la tabla 'ventas'
    try:
        supabase.table("ventas").insert(data).execute()
        print(f"✅ Venta guardada: {cliente}")
    except Exception as e:
        print(f"❌ Error guardando venta: {e}")