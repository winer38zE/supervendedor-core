def rewrite_copy_with_ai(original_text):
    """Envía el texto a tu instancia local de Ollama para su traducción y adaptación comercial."""
    # Apuntamos al puerto por defecto de Ollama en tu máquina
    url = "http://localhost:11434/api/chat"
    
    # La misma ingeniería de prompt enfocada en tu modelo de negocio
    prompt_system = """
    Eres un experto en copywriting directo y ventas por Facebook Ads en Colombia. 
    Te entregaré un anuncio de la competencia extraído de Meta. Tu trabajo es:
    1. Si está en inglés o portugués, tradúcelo al español natural de Colombia.
    2. Adáptalo específicamente para vender un catálogo de ropa deportiva estilo Shein.
    3. Incluye un fuerte llamado a la acción (Call to Action) enfocado en "Pago Contra Entrega en Cúcuta".
    4. El resultado final debe ser un texto persuasivo, con emojis bien ubicados, listo para que un distribuidor independiente lo copie y pegue en sus estados o grupos de venta. 
    5. Devuelve ÚNICAMENTE el texto final, sin introducciones ni explicaciones.
    """

    payload = {
        "model": "llama3", # Asegúrate de tener este modelo descargado, o cámbialo por "mistral" o el que prefieras
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": f"Optimiza este texto: {original_text}"}
        ],
        "stream": False # Apagamos el stream para recibir la respuesta completa de una vez
    }
    
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            # Ollama devuelve la respuesta en una estructura ligeramente distinta a Groq
            return res.json()["message"]["content"]
        else:
            return f"[-] Error en Ollama: {res.text}"
    except Exception as e:
        return f"[!] Error de conexión local. ¿Ollama está encendido?: {e}"