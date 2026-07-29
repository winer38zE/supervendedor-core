"""
test_media_generation.py
Script de PRUEBA suelto para verificar que tu GEMINI_API_KEY funciona,
generando una imagen (Nano Banana) y, opcionalmente, un video (Veo 3.1).

No depende de FastAPI ni de la base de datos: es solo para probar rápido
en la terminal de Cursor.

Instalación (si falta algo):
    pip install httpx python-dotenv

Requiere en tu .env (el mismo que ya tienes en el proyecto):
    GEMINI_API_KEY=tu_api_key

Cómo correrlo (PowerShell, en la carpeta del proyecto):
    python test_media_generation.py                # solo imagen
    python test_media_generation.py --video         # imagen + video
"""

import os
import sys
import time
import base64

import httpx
from dotenv import load_dotenv

load_dotenv()  # lee tu .env existente

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

if not GEMINI_API_KEY:
    print("❌ No encontré GEMINI_API_KEY en tu .env. Agrégala y vuelve a correr.")
    sys.exit(1)

HEADERS = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}


def probar_imagen():
    print("🎨 Generando imagen de prueba con Nano Banana...")
    prompt = (
        "A professional 8k photograph of a woman's vibrant purple seamless sports leggings and matching sports bra set, displayed on a minimalist wooden mannequin in a bright, modern, sunlit gym in Cúcuta, Colombia. Detailed texture of the elastic fabric, cinematic lighting, high-resolution. Isolated product shot."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"imageConfig": {"aspectRatio": "1:1"}},
    }

    resp = httpx.post(
        f"{BASE_URL}/models/gemini-2.5-flash-image:generateContent",
        headers=HEADERS,
        json=payload,
        timeout=60,
    )

    if resp.status_code != 200:
        print(f"❌ Error {resp.status_code}: {resp.text}")
        return

    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        images = [p["inlineData"]["data"] for p in parts if "inlineData" in p]
    except (KeyError, IndexError):
        print(f"❌ Respuesta inesperada: {data}")
        return

    if not images:
        print(f"❌ No vino ninguna imagen en la respuesta: {data}")
        return

    filename = f"test_image_{int(time.time())}.png"
    with open(filename, "wb") as f:
        f.write(base64.b64decode(images[0]))

    print(f"✅ Imagen guardada como: {filename}")


def probar_video():
    print("🎬 Generando video de prueba con Veo 3.1 (esto tarda un par de minutos)...")
    prompt = (
        "Video publicitario de 8 segundos: camiseta deportiva negra en un gimnasio, "
        "cámara girando lentamente alrededor del producto, iluminación dramática, "
        "estilo comercial profesional"
    )
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"resolution": "720p"},
    }

    resp = httpx.post(
        f"{BASE_URL}/models/veo-3.1-generate-preview:predictLongRunning",
        headers=HEADERS,
        json=payload,
        timeout=60,
    )

    if resp.status_code != 200:
        print(f"❌ Error {resp.status_code}: {resp.text}")
        return

    operation_name = resp.json().get("name")
    if not operation_name:
        print(f"❌ No vino operation name: {resp.json()}")
        return

    print(f"   Operación en curso: {operation_name}")
    waited = 0
    max_wait = 300
    interval = 10

    while waited < max_wait:
        poll_resp = httpx.get(f"{BASE_URL}/{operation_name}", headers=HEADERS, timeout=30)
        if poll_resp.status_code != 200:
            print(f"❌ Error consultando estado: {poll_resp.text}")
            return

        data = poll_resp.json()
        if data.get("done"):
            try:
                samples = data["response"]["generateVideoResponse"]["generatedSamples"]
                video_uri = samples[0]["video"]["uri"]
                print(f"✅ Video listo. URI: {video_uri}")
                print("   (para descargarlo necesitas mandar tu API key en el header x-goog-api-key)")
            except (KeyError, IndexError):
                print(f"❌ Respuesta inesperada: {data}")
            return

        print(f"   ...esperando ({waited}s)")
        time.sleep(interval)
        waited += interval

    print(f"⏱️ Timeout. Puedes seguir consultando manualmente con: {operation_name}")


if __name__ == "__main__":
    probar_imagen()

    if "--video" in sys.argv:
        probar_video()
    else:
        print("\nTip: corre con --video si también quieres probar Veo (tarda más y cuesta más).")