import os
import requests
from dotenv import load_dotenv

# Cargar las variables de tu archivo .env
load_dotenv()

def probar_mapas():
    # Leer la llave de Google Maps
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    
    if not api_key:
        print("❌ Error: No se encontró la GOOGLE_MAPS_API_KEY en el .env")
        return

    print("☁️ Conectando con los servidores de Google Cloud...")
    
    # Dirección de prueba en tu ciudad
    direccion = "Ventura Plaza, Cúcuta, Norte de Santander, Colombia"
    
    # Esta es la URL oficial de la Geocoding API
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={direccion}&key={api_key}"
    
    print(f"🗺️ Buscando coordenadas para: {direccion}...\n")
    
    # Hacer la petición a Google
    respuesta = requests.get(url)
    datos = respuesta.json()
    
    # Verificar si Google nos devolvió un resultado exitoso
    if datos['status'] == 'OK':
        latitud = datos['results'][0]['geometry']['location']['lat']
        longitud = datos['results'][0]['geometry']['location']['lng']
        
        print("✅ ¡Conexión exitosa a Google Cloud!")
        print("-" * 40)
        print(f"📍 Latitud:  {latitud}")
        print(f"📍 Longitud: {longitud}")
        print("-" * 40)
        print("Tus 100,000 pesos respaldan esta conexión profesional. 🚀")
    else:
        print(f"❌ La API devolvió un error: {datos['status']}")
        if 'error_message' in datos:
            print(f"Detalle del error: {datos['error_message']}")

if __name__ == "__main__":
    probar_mapas()