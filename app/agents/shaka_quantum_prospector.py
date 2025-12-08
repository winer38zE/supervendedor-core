# app/agents/shaka_quantum_prospector.py
import random
from vertexai.generative_models import GenerativeModel

class ShakaQuantumProspector:
    def __init__(self, target_channel: str = "WhatsApp"):
        self.model = GenerativeModel("gemini-1.5-pro")
        self.target_channel = target_channel
        
    def calculate_initial_probability(self, lead_data: dict) -> float:
        """
        Calcula la probabilidad inicial de compra (El 'Estado de Superposición' del cliente).
        
        Input de ejemplo: {'name': 'Camus', 'source': 'Instagram Ad', 'past_interest': 'Zapatillas'}
        """
        data_str = json.dumps(lead_data)
        
        # Shaka usa a Gemini para escanear el cosmos (los datos del lead)
        prompt = (
            f"Analiza el siguiente perfil de prospecto: {data_str}. "
            f"Basado en la fuente y el interés, devuelve SOLAMENTE un número decimal "
            f"del 0.0 al 1.0 que represente la probabilidad inicial de que compre en este momento."
        )
        try:
            response = self.model.generate_content(prompt, temperature=0.0).text
            return float(response.strip())
        except Exception:
            return 0.25 # Probabilidad base si falla

    def collapse_wave_function(self, lead_id: str, probability_score: float) -> dict:
        """
        El 'Colapso Cuántico': Decide la acción perfecta (Canal y Mensaje) para iniciar la venta.
        """
        
        # 1. Decision de Canal (Entanglement/Canal Óptimo)
        if probability_score > 0.8:
            channel = "Direct_Call_Vapi" # Probabilidad alta, vamos directo al cierre.
        elif probability_score > 0.5:
            channel = "WhatsApp_Personalized"
        else:
            channel = "Email_RAG_Nurture" # Probabilidad baja, nutrimos con contenido.
            
        # 2. Generacion del Mensaje (El Ataque de la 'Explosión Galáctica')
        
        prompt = (
            f"El lead {lead_id} tiene una probabilidad de {probability_score*100:.0f}% de comprar. "
            f"Genera una línea de apertura de ventas directa y profesional para el canal {channel} "
            f"que maximice el colapso de la función de onda en una venta."
        )
        
        opening_line = self.model.generate_content(prompt, temperature=0.8).text
        
        return {
            "lead_id": lead_id,
            "probability": probability_score,
            "action": "PROSPECTAR_PROACTIVO",
            "channel": channel,
            "opening_line": opening_line
        }