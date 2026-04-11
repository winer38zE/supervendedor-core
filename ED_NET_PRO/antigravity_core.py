import os
from supabase import create_client

# Configuración del Centinela
URL = "https://zuvscvatsugwdesxnfpe.supabase.co"
KEY = "TU_SERVICE_ROLE_KEY" # La que ya tienes en el .env
supabase = create_client(URL, KEY)

def login_plataforma(email, password):
    """Sistema de entrada global ED NET PRO"""
    if password == "ednetpro_2026":
        print(f"🚀 [SISTEMA]: Acceso Concedido para {email}")
        return True
    else:
        print("❌ [ALERTA]: Password Incorrecto. Centinela bloqueando acceso.")
        return False

def check_tokens(org_id):
    """Verifica si el cliente tiene los $10 mínimos para operar"""
    res = supabase.table("organizaciones").select("saldo_tokens").eq("id", org_id).execute()
    saldo = res.data[0]['saldo_tokens']
    if saldo < 10:
        print(f"⚠️ [AVISO]: Saldo insuficiente (${saldo}). Recargue para usar Andrómeda.")
        return False
    return True

# Prueba de arranque
if __name__ == "__main__":
    print("--- VIGILANTE ACTIVO: MODULO ANTIGRAVITY ---")
    login_plataforma("cliente@test.com", "ednetpro_2026")