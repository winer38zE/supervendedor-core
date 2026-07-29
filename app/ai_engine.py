import os
from fastapi import APIRouter, HTTPException, status

router = APIRouter()

# Traemos la clave desde las variables de entorno que configuramos en el .env
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

@router.post("/v1/agente/procesar")
async def procesar_con_ia(mensaje: str):
    
    # ── Verificamos si hay clave antes de intentar aprender/procesar ──
    if not GEMINI_API_KEY or GEMINI_API_KEY.startswith("TU_"):
        # Registramos el error internamente en el servidor Hetzner
        print("[ERROR CRÍTICO]: GEMINI_API_KEY no configurada o inválida en el .env")
        
        # Lanzamos un error limpio que n8n pueda capturar sin tumbar el backend
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error de configuración del servidor: Falta credencial de IA."
        )
    
    # Si la clave pasa la auditoría, el Súper Vendedor ejecuta la acción de forma segura
    try:
        # Aquí iría tu llamada nativa a la API
        # respuesta = ejecutar_cerebro_ia(mensaje)
        return {"status": "success", "respuesta": "Lógica ejecutada de pinga"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en ejecución: {str(e)}")
        
def analizar_chat_para_aprender(transcripcion: str) -> None:
    if not transcripcion or not transcripcion.strip():  # ✅ Indentado
        print("[AI] Transcripción vacía")
        return
    
    print(f"[AI Learning] ✅ Procesando {len(transcripcion)} chars")    