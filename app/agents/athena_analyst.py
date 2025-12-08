# app/agents/athena_analyst.py
from datetime import datetime
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel

class AthenaAnalyst:
    def __init__(self, project_id: str = "gen-lang-client-0772548156"):
        # Atenea usa Gemini para la parte más sensible: el sentimiento
        self.model = GenerativeModel("gemini-1.5-pro")
        
    def analyze_sentiment(self, text: str) -> float:
        """Usa Gemini para clasificar el tono y la intención de compra (0.0 a 1.0)."""
        prompt = (
            f"Analiza el siguiente texto de un cliente. Devuelve SOLO un número decimal "
            f"del 0.0 (totalmente hostil/sin interés) al 1.0 (entusiasta/listo para comprar): '{text}'"
        )
        try:
            response = self.model.generate_content(prompt, temperature=0.0).text
            # Intentamos convertir la respuesta (ej. "0.95") a float
            return float(response.strip())
        except Exception:
            # Fallback si Gemini no devuelve un número limpio
            return 0.5 

    def calculate_velocity(self, last_bot_time: datetime, user_reply_time: datetime) -> float:
        """Calcula la velocidad de respuesta (inversa de la fricción)."""
        # Asumimos que el tiempo se mide en segundos
        time_difference_seconds = (user_reply_time - last_bot_time).total_seconds()
        
        # Una respuesta rápida (ej. 30 segundos) da alta velocidad. Una respuesta lenta da baja velocidad.
        # Fórmula: 1 / (log(tiempo_en_segundos) + 1). Esto penaliza el tiempo exponencialmente.
        if time_difference_seconds <= 10:
            return 1.0 # Máxima velocidad si es casi instantáneo
        
        # Lógica de cálculo de velocidad (simulada)
        velocity_score = 1 / (0.1 * time_difference_seconds + 1)
        return max(0.1, velocity_score) # Mínimo 0.1

    def get_sales_momentum(self, last_user_message: str, last_interaction_time: datetime, current_time: datetime) -> dict:
        """Combina Sentimiento (Masa) y Velocidad para dar un dictamen estratégico."""
        
        sentiment = self.analyze_sentiment(last_user_message)
        velocity = self.calculate_velocity(last_interaction_time, current_time)
        
        # La fórmula de la Física de Ventas: Momentum = Sentimiento x Velocidad
        momentum = sentiment * velocity

        if momentum > 0.8:
            return {"status": "HOT_LEAD", "advice": "¡Cierre urgente! No negocies más."}
        elif momentum < 0.3:
            return {"status": "CHURN_RISK", "advice": "Cliente frío. Activar Hefesto o Cronos (oferta evolutiva)."}
        else:
            return {"status": "WARM_LEAD", "advice": "Continuar con el diálogo de ventas normal."}