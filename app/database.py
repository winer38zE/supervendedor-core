# app/database.py
import os
from supabase import create_client, Client

# --- PARTE 1: CEREBRO DE ZEUS (Memoria de Chat) ---
class SupabaseDB:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        self.client = None
        
        if not url or not key:
            print("⚠️ ERROR: Faltan credenciales de Supabase")
        else:
            try:
                self.client = create_client(url, key)
                print("✅ Supabase Conectado.")
            except Exception as e:
                print(f"🔥 Error conexión Supabase: {e}")

    def get_or_create_lead(self, phone: str):
        if not self.client: return {"id": "no-db", "phone": phone}
        try:
            res = self.client.table("leads").select("*").eq("phone", phone).execute()
            if res.data: return res.data[0]
            
            new_lead = {"phone": phone, "status": "NUEVO"}
            res = self.client.table("leads").insert(new_lead).execute()
            return res.data[0]
        except: return {"id": "error", "phone": phone}

    def save_message(self, lead_id: str, role: str, content: str):
        if not self.client or lead_id in ["no-db", "error"]: return
        try:
            self.client.table("messages").insert({
                "lead_id": lead_id, "role": role, "content": content
            }).execute()
        except: pass

    def get_chat_history(self, lead_id: str, limit=5):
        if not self.client or lead_id in ["no-db", "error"]: return []
        try:
            res = self.client.table("messages").select("role, content").eq("lead_id", lead_id).order("created_at", desc=True).limit(limit).execute()
            return res.data[::-1]
        except: return []

# --- PARTE 2: EL RESCATE DE VAPI (Lo que faltaba) ---
# Esta función suelta es la que busca vapi_handler.py
def guardar_venta(data: dict):
    """
    Función puente para que Vapi no rompa el sistema.
    """
    print(f"💰 Venta reportada por Vapi: {data}")
    # Aquí podríamos guardar en Supabase si quisiéramos, 
    # por ahora retornamos True para que no de error.
    return True