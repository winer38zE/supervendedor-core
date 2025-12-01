from fastapi import APIRouter, Request
from ..database import guardar_venta

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    
    # Extraer datos que vienen de Make o Flowise
    cliente = data.get("cliente", "Cliente Chat")
    monto = data.get("monto", 0)
    producto = data.get("producto", "Consulta")
    
    print(f"💬 Mensaje recibido de {cliente}")
    
    guardar_venta(cliente, monto, producto, "Cerrado", "WhatsApp")
    
    return {"status": "OK"}