# app/agents/hermes_negotiator.py
from vertexai.generative_models import GenerativeModel

class HermesNegotiator:
    def __init__(self, target_price: float, reserve_price: float):
        self.target_price = target_price # Precio ideal de venta
        self.reserve_price = reserve_price # Precio mínimo aceptable (sin perder dinero)
        self.model = GenerativeModel("gemini-1.5-pro")

    def calculate_counter_offer(self, user_offer: float) -> dict:
        """Calcula la contraoferta usando la lógica de la ZONA DE ACUERDO POSIBLE (ZOPA)."""
        
        if user_offer >= self.target_price:
            return {"action": "accept", "price": user_offer, "diff": 0}

        if user_offer < self.reserve_price:
            # Fuera del límite. Hacemos una pequeña concesión para atraerlos
            counter_price = self.reserve_price + ((self.target_price - self.reserve_price) * 0.1)
            return {"action": "reject_counter", "price": counter_price, "diff": self.target_price - counter_price}

        # El cliente está en la ZOPA (entre reserve y target). Aplicamos concesión estratégica.
        # Estrategia: Ceder la mitad de la diferencia restante entre el target y su oferta.
        concession_amount = (self.target_price - user_offer) * 0.5
        counter_price = self.target_price - concession_amount

        return {"action": "counter", "price": round(counter_price, 2), "diff": self.target_price - counter_price}

    def generate_response(self, decision: dict) -> str:
        """Usa Gemini para dar voz persuasiva a la decisión matemática."""
        
        action = decision['action']
        price = decision['price']
        
        if action == "accept":
            prompt = "El cliente acaba de aceptar nuestro precio. Escribe una respuesta entusiasta para cerrar la venta inmediatamente."
        elif action == "reject_counter":
            prompt = (
                f"El cliente ofreció muy poco. Debes rechazar, pero con respeto. Propón cortésmente {price} USD. "
                f"Usa un tono que sugiera que este precio es una concesión exclusiva y urgente."
            )
        elif action == "counter":
            prompt = (
                f"Hemos calculado la contraoferta a {price} USD. Escribe una respuesta persuasiva. "
                f"Usa el principio de reciprocidad: 'Hago este esfuerzo por ti, ahora es tu turno de cerrar el trato'."
            )
        
        response = self.model.generate_content(prompt, temperature=0.7)
        return response.text