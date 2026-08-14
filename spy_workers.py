import os
from dotenv import load_dotenv
load_dotenv()
import requests
import pandas as pd
from pytrends.request import TrendReq
from datetime import datetime
from typing import List, Dict, Any

# ==========================================
# CONFIGURACIÓN DEL ENTORNO
# ==========================================
POCKETBASE_URL = os.getenv("POCKETBASE_URL", "http://178.105.48.103:8090")

# Credenciales de Meta API
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "TU_TOKEN_DE_META")

# ==========================================
# 1. MÓDULO DE GOOGLE TRENDS
# ==========================================
def get_market_trends(keywords: List[str], geo: str = "CO") -> List[Dict[str, Any]]:
    """
    Obtiene el interés de búsqueda. geo='CO' para Colombia, 
    puedes usar 'CO-NSA' para enfocarlo específicamente en Norte de Santander.
    """
    print(f"[*] Obteniendo datos de Trends para: {keywords} en {geo}...")
    pytrend = TrendReq(hl='es', tz=300, timeout=(10,25))
    
    pytrend.build_payload(kw_list=keywords, timeframe='now 7-d', geo=geo)
    interest_over_time_df = pytrend.interest_over_time()
    
    if interest_over_time_df.empty:
        return []

    # Tomar el último registro de interés
    latest_data = interest_over_time_df.iloc[-1]
    
    trends_data = []
    for kw in keywords:
        trends_data.append({
            "keyword": kw,
            "interest_score": int(latest_data[kw]),
            "date": datetime.now().isoformat()
        })
        
    return trends_data

# ==========================================
# 2. MÓDULO DE META AD LIBRARY
# ==========================================
def get_competitor_ads(page_id: str, search_terms: str = "") -> List[Dict[str, Any]]:
    """
    Consulta a la API de Meta Graph para obtener los anuncios activos.
    Requiere que la cuenta de desarrollador esté verificada para la Ad Library.
    """
    print(f"[*] Buscando anuncios activos en Meta para la página: {page_id}...")
    url = "https://graph.facebook.com/v19.0/ads_archive"
    
    params = {
        "access_token": META_ACCESS_TOKEN,
        "search_terms": search_terms, # Ahora sí usaremos este campo de verdad
        # "search_page_ids": page_id, # Lo apagamos para buscar en todo Facebook
        "ad_active_status": "ACTIVE",
        "ad_reached_countries": "['CO']",
        "fields": "id,ad_creation_time,ad_creative_bodies,page_name"
    }
    
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"[!] Error en Meta API: {response.text}")
        return []
        
    data = response.json().get('data', [])
    
    ads_list = []
    for ad in data:
        # Extraer el texto principal del anuncio
        bodies = ad.get('ad_creative_bodies', [''])
        ad_text = bodies[0] if bodies else ""
        
        ads_list.append({
            "ad_id": ad['id'],
            "competitor_name": ad['page_name'],
            "ad_copy": ad_text,
            "start_date": ad['ad_creation_time'],
            "status": "ACTIVE"
        })
        
    return ads_list

# ==========================================
# 3. MÓDULO DE POCKETBASE (INYECCIÓN DE DATOS)
# ==========================================
def save_trend_to_db(keyword, interest_score, geo_location):
    """Envía los datos de Google Trends a PocketBase"""
    url = f"{POCKETBASE_URL}/api/collections/spy_trends/records"
    data = {
        "keyword": keyword,
        "interest_score": interest_score,
        "geo_location": geo_location
    }
    
    try:
        response = requests.post(url, json=data)
        if response.status_code == 200:
            print(f"  [+] Tendencia para '{keyword}' guardada con éxito.")
        else:
            print(f"  [-] Error guardando tendencia: {response.text}")
    except Exception as e:
        print(f"  [!] Error de conexión con el servidor: {e}")

def save_ad_to_db(page_id, ad_id, copy_text, status="active"):
    """Envía los anuncios extraídos de Meta a PocketBase"""
    url = f"{POCKETBASE_URL}/api/collections/spy_meta_ads/records"
    data = {
        "page_id": str(page_id),
        "ad_id": str(ad_id),
        "copy_text": str(copy_text),
        "status": status
    }
    
    try:
        response = requests.post(url, json=data)
        if response.status_code == 200:
            print(f"  [+] Anuncio {ad_id} inyectado en la base de datos.")
        elif response.status_code == 400:
            print(f"  [*] El anuncio {ad_id} ya estaba en la base de datos (ignorado).")
        else:
            print(f"  [-] Error guardando anuncio: {response.text}")
    except Exception as e:
        print(f"  [!] Error de conexión con el servidor: {e}")

# ==========================================
# EJECUCIÓN PRINCIPAL
# ==========================================
if __name__ == "__main__":
    
    # 1. Analizar e Inyectar Tendencias (APAGADO TEMPORALMENTE POR BLOQUEO 429)
    # marcas_competencia = ["Nike", "Adidas"]
    # geo_zona = "CO-NSA"
    # trends = get_market_trends(marcas_competencia, geo=geo_zona)
    
    # for t in trends:
    #     save_trend_to_db(t["keyword"], t["interest_score"], geo_zona)
    
    # 2. Extraer e Inyectar Anuncios de Meta (ESTE SÍ CORRE)
    termino_busqueda = "Shein" 
    active_ads = get_competitor_ads(page_id="", search_terms=termino_busqueda) 
    
    for ad in active_ads:
        save_ad_to_db(
            page_id=ad["competitor_name"], # Guardamos el nombre de quien pauta
            ad_id=ad["ad_id"],
            copy_text=ad["ad_copy"],
            status=ad["status"]
        )
        
    print("\n[*] Proceso de espionaje finalizado con éxito.")