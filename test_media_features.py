"""
test_media_features.py — Prueba de medios y visión multimodal (OpenAI)
────────────────────────────────────────────────────────────────────────────────
Ejecuta pruebas de:
  a) Visión (gpt-4o-mini) — analizar imagen desde URL pública
  b) TTS (tts-1)          — generar output_test.mp3 con voz de vendedor
  c) Whisper (whisper-1)  — transcribir audio local si existe

Uso:
  set OPENAI_API_KEY=sk-...
  python test_media_features.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.media_service import OpenAIMediaService


def _banner(title: str, icon: str = "▶") -> None:
    print(f"\n{'=' * 62}")
    print(f"  {icon}  {title}")
    print(f"{'=' * 62}")


def test_vision(service: OpenAIMediaService) -> None:
    """Prueba a) — Análisis de imagen desde URL web y/o archivo local."""
    _banner("PRUEBA VISIÓN — gpt-4o-mini", "👁️")

    # Unsplash permite descarga directa compatible con OpenAI Vision
    default_url = "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500"
    sample_url = os.getenv("TEST_VISION_IMAGE_URL", default_url).strip()

    prompt = (
        "Eres un vendedor de ropa deportiva en Colombia. "
        "Describe qué ves en la imagen y si podría ser útil para un catálogo. "
        "Responde en español, máximo 5 líneas."
    )

    # ── 1) URL web ────────────────────────────────────────────────────────────
    print("── Subprueba: URL web (Unsplash) ──")
    print(f"URL: {sample_url}")
    print(f"Prompt: {prompt[:80]}...\n")

    try:
        result = service.analyze_image(sample_url, prompt)
        print("✅ Análisis URL completado:\n")
        print(result)
    except Exception as exc:
        print(f"❌ Error en visión (URL): {exc}")

    # ── 2) Archivo local (.jpg / .png) si existe ──────────────────────────────
    local_candidates = [
        os.getenv("TEST_VISION_IMAGE_PATH", "").strip(),
        str(ROOT / "test_image.jpg"),
        str(ROOT / "test_image.png"),
        str(ROOT / "app" / "storage_vault" / "media_temp" / "test_image.jpg"),
    ]
    local_path = next((p for p in local_candidates if p and Path(p).is_file()), None)

    print("\n── Subprueba: imagen local (.jpg / .png) ──")
    if not local_path:
        print("⏭️  Sin imagen local — coloca test_image.jpg en la raíz")
        print("   o define TEST_VISION_IMAGE_PATH en .env")
        return

    print(f"Archivo: {local_path}\n")
    local_prompt = (
        "Analiza esta imagen local. Extrae cualquier dato útil para ventas "
        "(producto, texto visible, colores). Responde en español."
    )

    try:
        result_local = service.analyze_image(local_path, local_prompt)
        print("✅ Análisis local completado:\n")
        print(result_local)
    except Exception as exc:
        print(f"❌ Error en visión (local): {exc}")


def test_tts(service: OpenAIMediaService) -> None:
    """Prueba b) — Generación de voz TTS."""
    _banner("PRUEBA TTS — tts-1 / voz nova", "🔊")

    sales_text = (
        "¡Hola! Soy tu asesor de ED NET PRO. "
        "Tenemos enterizos deportivos en talla M con pago contra entrega en Cúcuta. "
        "¿Te aparto uno hoy mismo?"
    )
    output_file = str(ROOT / "output_test.mp3")

    print(f"Texto: {sales_text}\n")
    print(f"Salida: {output_file}\n")

    try:
        path = service.generate_voice_response(sales_text, output_file, voice="nova")
        size_kb = Path(path).stat().st_size / 1024
        print(f"✅ Audio generado: {path} ({size_kb:.1f} KB)")
    except Exception as exc:
        print(f"❌ Error en TTS: {exc}")


def test_whisper(service: OpenAIMediaService) -> None:
    """Prueba c) — Transcripción Whisper si hay audio local."""
    _banner("PRUEBA WHISPER — whisper-1", "🎙️")

    # Rutas candidatas: variable de entorno o archivos comunes de prueba
    candidates = [
        os.getenv("TEST_AUDIO_PATH", ""),
        str(ROOT / "test_audio.ogg"),
        str(ROOT / "test_audio.mp3"),
        str(ROOT / "app" / "storage_vault" / "media_temp" / "sample.ogg"),
    ]
    audio_path = next((p for p in candidates if p and Path(p).is_file()), None)

    if not audio_path:
        print("⏭️  Sin archivo de audio local para transcribir.")
        print("   Coloca un .ogg/.mp3 en la raíz como test_audio.ogg")
        print("   o define TEST_AUDIO_PATH en .env")
        return

    print(f"Archivo: {audio_path}\n")

    try:
        text = service.transcribe_audio(audio_path)
        print("✅ Transcripción:\n")
        print(text or "(vacío)")
    except Exception as exc:
        print(f"❌ Error en Whisper: {exc}")


def main() -> None:
    _banner("INICIO — OpenAIMediaService", "🚀")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("\n❌ OPENAI_API_KEY no encontrada en .env")
        print("   Agrega: OPENAI_API_KEY=sk-...")
        sys.exit(1)

    print(f"\n✅ OPENAI_API_KEY detectada ({api_key[:8]}...)")

    service = OpenAIMediaService()
    if not service.is_available:
        print("\n❌ OpenAIMediaService no pudo inicializarse.")
        print("   Verifica: pip install openai")
        sys.exit(1)

    # Ejecutar las 3 pruebas en secuencia
    test_vision(service)
    test_tts(service)
    test_whisper(service)

    _banner("FIN — Pruebas de medios completadas", "🏁")
    print("\nRevisa output_test.mp3 si la prueba TTS fue exitosa.\n")


if __name__ == "__main__":
    main()
