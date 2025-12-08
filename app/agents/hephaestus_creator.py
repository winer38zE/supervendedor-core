# app/agents/hephaestus_creator.py
import os
from vertexai.preview.vision_models import ImageGenerationModel

# Librería simulada para la creación de documentos (necesitarás instalar reportlab)
# from reportlab.pdfgen import canvas 

class HephaestusCreator:
    def __init__(self):
        # Hefesto usa el modelo Imagen para generar contenido visual
        self.image_model = ImageGenerationModel.from_pretrained("imagegeneration@006")
        
    def generate_visual_hook(self, product_name: str, user_context: str) -> str:
        """Genera una imagen ultra-persuasiva usando la IA de Google (Imagen 3)."""
        
        prompt = (
            f"Crea una toma de producto profesional, estilo cinemático 8k, del producto: '{product_name}'. "
            f"El contexto debe ser altamente personalizado: '{user_context}'. "
            f"Ejemplo: mostrar el producto siendo usado con éxito."
        )
        
        try:
            # Esto genera la imagen en la nube.
            images = self.image_model.generate_images(prompt=prompt, number_of_images=1, output_mime_type="image/jpeg")
            
            # Guardamos la imagen temporalmente para enviarla por WhatsApp
            file_name = f"visual_hook_{os.urandom(4).hex()}.jpeg"
            images[0].save(location=file_name) 
            
            return file_name
        except Exception as e:
            print(f"Error en la generación de Imagen: {e}")
            return "error_placeholder.jpg" # Devuelve un placeholder si falla

    def forge_instant_proposal(self, client_name: str, price: float) -> str:
        """Simula la creación de un PDF o propuesta formal de cierre."""
        
        # En la vida real, aquí usarías reportlab o fpdf para crear el PDF.
        file_name = f"propuesta_{client_name}_{os.urandom(4).hex()}.pdf"
        
        # Lógica simulada de creación de PDF
        # c = canvas.Canvas(file_name)
        # c.drawString(100, 750, f"Propuesta Exclusiva para: {client_name}")
        # c.drawString(100, 720, f"Precio Final: ${price}")
        # c.save()
        
        print(f"PDF simulado de propuesta de cierre generado: {file_name}")
        return file_name