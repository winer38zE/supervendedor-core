import os
from pathlib import Path
from dotenv import load_dotenv

# Fuerza la carga buscando el .env en la misma carpeta que este script
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Imprimir dónde está buscando
print(f"DEBUG: Buscando .env en: {env_path.absolute()}")
print(f"DEBUG: Token cargado: {os.getenv('META_ACCESS_TOKEN')}")


# Cargar el archivo .env ubicado en la raíz
load_dotenv() 

# Importar la clase después de cargar las variables
from app.marketing.meta_api import MetaAdsManager

# TEST: ¿Ya cargó el token?
print(f"DEBUG: META_ACCESS_TOKEN en el sistema: {os.getenv('META_ACCESS_TOKEN')}")

def probar_conexion():
    try:
        print("🚀 Conectando a Meta...")
        manager = MetaAdsManager()
        metricas = manager.get_account_metrics()
        print("✅ ¡Conexión exitosa!")
        print(metricas)
    except Exception as e:
        print(f"❌ Error en la conexión: {e}")

if __name__ == "__main__":
    probar_conexion()