import openai
from .config import settings

# Configurar OpenAI con la clave del archivo config
openai.api_key = settings.OPENAI_API_KEY

def analizar_chat_para_aprender(historial_chat):
    """
    Lee el chat y extrae la técnica ganadora.
    """
    # Verificamos si hay clave antes de intentar aprender
    if not settings.OPENAI_API_KEY:
        print("⚠️ No hay API Key de OpenAI, saltando aprendizaje.")
        return "Aprendizaje desactivado (Falta Key)"

    try:
        # Llamada a GPT-4 para analizar la venta
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un experto en ventas. Extrae en 1 frase corta qué técnica de cierre funcionó en este chat."},
                {"role": "user", "content": str(historial_chat)}
            ]
        )
        mejor_tecnica = response.choices[0].message.content
        
        # Guardar la técnica en un archivo de texto (Memoria local)
        # Aseguramos que la carpeta prompts existe
        with open("prompts/vendedor_v1.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[NUEVO APRENDIZAJE]: {mejor_tecnica}")
            
        return mejor_tecnica

    except Exception as e:
        print(f"Error en el motor de IA: {e}")
        return f"Error aprendiendo: {str(e)}"