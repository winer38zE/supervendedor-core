# app/services/call_auditor.py
from app.services.llm_agent import get_llm_response # Asumiendo que tienes tu cliente de IA

async def auditar_llamada(transcript: str):
    """
    Analiza la transcripción para mejorar los cierres.
    """
    prompt = f"""
    Actúa como un experto en ventas B2B. Analiza esta transcripción:
    "{transcript}"
    
    Devuelve un JSON con:
    1. 'sentimiento': (positivo/negativo/neutral)
    2. 'objetivo_cumplido': (boolean)
    3. 'objecion_principal': (que freno la venta)
    4. 'score_de_cierre': (1-10)
    """
    
    analisis = await get_llm_response(prompt)
    return analisis