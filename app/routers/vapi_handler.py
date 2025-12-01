from fastapi import APIRouter, Request
from ..database import guardar_venta
from ..ai_engine import analizar_chat_para_aprender

# ESTA ES LA LÍNEA QUE FALTABA O ESTABA MAL:
router = APIRouter(prefix="/vapi", tags=["Vapi Voice"])

@router.post("/webhook")
async def vapi_webhook(request: Request):
    try:
        data = await request.json()
        message_type = data.get("message", {}).get("type")
        
        if message_type == "end-of-call-report":
            call = data.get("message", {})
            cliente = call.get("customer", {}).get("number", "Anonimo")
            analisis = call.get("analysis", {})
            exito = analisis.get("successEvaluation", False)
            
            estado = "Cerrado" if exito else "Perdida"
            monto = 150000 if exito else 0
            
            print(f"📞 Vapi: {cliente} | Estado: {estado}")

            guardar_venta(cliente, monto, "Llamada IA", estado, "Vapi")
            
            if exito:
                transcripcion = call.get("transcript", "")
                if transcripcion:
                    analizar_chat_para_aprender(transcripcion)
                    
            return {"status": "Procesado"}
        
        return {"status": "Ignorado"}

    except Exception as e:
        print(f"Error Vapi: {e}")
        return {"status": "Error"}