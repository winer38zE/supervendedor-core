from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter(prefix="/v1/cierre", tags=["Cierre Avanzado ED NET PRO"])

class PayloadDuda(BaseModel):
    remoteJid: str
    mensaje_cliente: str
    historial: str

@router.post("/analizar")
async def analizar_duda_avanzada(data: PayloadDuda):
    try:
        # Aquí es donde metes la inteligencia de verdad.
        # Analizamos lo que dice el cliente para tumbarle la objeción.
        texto = data.mensaje_cliente.lower()
        
        if "precio" in texto or "caro" in texto:
            respuesta = "¡Mano! Ojo que es calidad Shein premium y se lo entrego hoy mismo aquí en Cúcuta, sin esperas ni aduanas. ¿Le armo el paquete de una vez? ⚡"
        elif "talla" in texto or "medida" in texto:
            respuesta = "Todo bien mano, no se preocupe por la talla. Si no le llega a quedar como quiere, se lo cambiamos sin peros. ¿Qué talla es usted normalmente? 👕"
        else:
            # Respuesta genérica matadora si está dudando o tardando en responder
            respuesta = "¡Hágale pingo! Se me están agotando los conjuntos más firmes de esta semana. Dígame si se lo guardo de una vez o se lo dejamos a otro. 😉"
            
        return {
            "status": "success",
            "responder_whatsapp": True,
            "texto_ia": respuesta
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))