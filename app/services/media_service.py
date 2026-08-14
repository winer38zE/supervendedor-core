"""
app/services/media_service.py
────────────────────────────────────────────────────────────────────────────────
Servicio de medios y visión multimodal — OpenAI SDK oficial.

Capacidades:
  1. Whisper (whisper-1)  — transcribir audios de WhatsApp a texto en español.
  2. TTS (tts-1)          — generar respuestas de voz naturales para el vendedor.
  3. Visión (gpt-4o-mini) — analizar imágenes locales o URLs (productos, recibos).

Requisitos:
  - pip install openai
  - OPENAI_API_KEY en .env
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Formatos de audio soportados por WhatsApp / Evolution API
_AUDIO_EXTENSIONS = {".ogg", ".mp3", ".m4a", ".wav", ".webm", ".mpeg", ".mpga"}

# Voces TTS disponibles en OpenAI
_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}

# Imágenes soportadas para visión multimodal
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class OpenAIMediaService:
    """
    Wrapper unificado para audio (Whisper/TTS) y visión multimodal (GPT-4o-mini).

    Pensado para el flujo WhatsApp:
      audio entrante → transcribe_audio()
      respuesta texto → generate_voice_response()
      foto comprobante/producto → analyze_image()
    """

    def __init__(self, *, api_key: Optional[str] = None) -> None:
        self._api_key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
        self._client = None

        if not self._api_key:
            logger.warning(
                "[Media] OPENAI_API_KEY no configurada — servicio de medios desactivado."
            )
            return

        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
            logger.info("[Media] OpenAIMediaService inicializado")
        except ImportError:
            logger.error("[Media] Paquete 'openai' no instalado. Ejecuta: pip install openai")
        except Exception as exc:
            logger.exception("[Media] Error inicializando OpenAI client: %s", exc)

    @property
    def is_available(self) -> bool:
        """True si el cliente OpenAI está listo para usarse."""
        return self._client is not None

    def _require_client(self):
        if not self.is_available:
            raise RuntimeError(
                "OpenAIMediaService no disponible — configura OPENAI_API_KEY e instala openai"
            )
        return self._client

    # ── Método 1: Transcripción (Whisper) ─────────────────────────────────────

    def transcribe_audio(self, file_path: str) -> str:
        """
        Convierte un archivo de audio a texto en español usando whisper-1.

        Args:
            file_path: Ruta local al audio (.ogg, .mp3, .m4a, .wav, etc.).

        Returns:
            Texto transcrito.

        Raises:
            FileNotFoundError: Si el archivo no existe.
            ValueError:        Si la extensión no es soportada.
            RuntimeError:      Si OpenAI no está configurado o la API falla.
        """
        client = self._require_client()

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Archivo de audio no encontrado: {file_path}")

        ext = path.suffix.lower()
        if ext and ext not in _AUDIO_EXTENSIONS:
            raise ValueError(
                f"Formato de audio no soportado: {ext}. "
                f"Usa uno de: {', '.join(sorted(_AUDIO_EXTENSIONS))}"
            )

        try:
            with path.open("rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=os.getenv("OPENAI_WHISPER_MODEL", "whisper-1"),
                    file=audio_file,
                    language="es",
                    response_format="text",
                )

            # response_format="text" devuelve str; "json" devuelve objeto con .text
            text = transcript if isinstance(transcript, str) else getattr(transcript, "text", str(transcript))
            text = (text or "").strip()
            logger.info("[Media] Whisper transcribió %s chars desde %s", len(text), path.name)
            return text

        except Exception as exc:
            logger.exception("[Media] transcribe_audio falló: %s", file_path)
            raise RuntimeError(f"Error transcribiendo audio: {exc}") from exc

    # ── Método 2: Text-to-Speech (TTS) ────────────────────────────────────────

    def generate_voice_response(
        self,
        text: str,
        output_path: str,
        voice: str = "nova",
    ) -> str:
        """
        Genera un archivo de audio con voz natural a partir de texto de ventas.

        Args:
            text:        Texto a convertir (respuesta del bot / script de cierre).
            output_path: Ruta de salida (.mp3 recomendado; .ogg también soportado).
            voice:       Voz OpenAI (default 'nova' — tono amigable de vendedor).

        Returns:
            Ruta absoluta del archivo generado.
        """
        client = self._require_client()

        text = (text or "").strip()
        if not text:
            raise ValueError("El texto para TTS no puede estar vacío")

        voice = (voice or "nova").lower()
        if voice not in _TTS_VOICES:
            raise ValueError(
                f"Voz '{voice}' no válida. Opciones: {', '.join(sorted(_TTS_VOICES))}"
            )

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ext = out.suffix.lower()
        if ext not in {".mp3", ".ogg", ".wav", ".opus"}:
            out = out.with_suffix(".mp3")

        try:
            response = client.audio.speech.create(
                model=os.getenv("OPENAI_TTS_MODEL", "tts-1"),
                voice=voice,
                input=text,
            )

            # SDK reciente: write_to_file o streaming de bytes
            if hasattr(response, "write_to_file"):
                response.write_to_file(str(out))
            elif hasattr(response, "stream_to_file"):
                response.stream_to_file(str(out))
            else:
                out.write_bytes(response.content)

            logger.info("[Media] TTS generado: %s (%s bytes)", out, out.stat().st_size)
            return str(out.resolve())

        except Exception as exc:
            logger.exception("[Media] generate_voice_response falló")
            raise RuntimeError(f"Error generando voz: {exc}") from exc

    # ── Método 3: Visión multimodal (GPT-4o-mini) ─────────────────────────────

    def analyze_image(
        self,
        image_input: str,
        prompt: str = "Analiza esta imagen",
    ) -> str:
        """
        Analiza una imagen local o URL con gpt-4o-mini (visión).

        Casos de uso ED NET PRO:
          - Comprobante de pago / transferencia
          - Foto de producto enviada por el cliente
          - Captura de talla o referencia visual

        Args:
            image_input: Ruta local (C:\\...\\foto.jpg) o URL https://...
            prompt:      Pregunta o instrucción para el modelo.

        Returns:
            Respuesta textual del análisis.
        """
        client = self._require_client()

        image_input = (image_input or "").strip()
        prompt = (prompt or "Analiza esta imagen").strip()
        if not image_input:
            raise ValueError("image_input no puede estar vacío")

        image_url = self._resolve_image_url(image_input)
        model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url, "detail": "auto"},
                            },
                        ],
                    }
                ],
                max_tokens=int(os.getenv("OPENAI_VISION_MAX_TOKENS", "1024")),
            )

            answer = (completion.choices[0].message.content or "").strip()
            logger.info("[Media] Visión analizó imagen — %s chars de respuesta", len(answer))
            return answer

        except Exception as exc:
            logger.exception("[Media] analyze_image falló: %s", image_input[:80])
            raise RuntimeError(f"Error analizando imagen: {exc}") from exc

    def _resolve_image_url(self, image_input: str) -> str:
        """
        Resuelve el input de imagen para la API de visión de OpenAI.

        Soporta:
          - URLs web:  https://images.unsplash.com/...
          - Rutas locales absolutas o relativas: C:\\fotos\\recibo.jpg, ./img.png
        """
        raw = (image_input or "").strip().strip('"').strip("'")
        if not raw:
            raise ValueError("image_input no puede estar vacío")

        # ── URL web ───────────────────────────────────────────────────────────
        if self._is_web_url(raw):
            return raw

        # ── Archivo local (.jpg, .png, etc.) ─────────────────────────────────
        path = self._normalize_local_image_path(raw)
        if not path.is_file():
            raise FileNotFoundError(f"Imagen no encontrada: {image_input}")

        ext = path.suffix.lower()
        if ext not in _IMAGE_EXTENSIONS:
            raise ValueError(
                f"Formato de imagen no soportado: {ext or '(sin extensión)'}. "
                f"Usa uno de: {', '.join(sorted(_IMAGE_EXTENSIONS))}"
            )

        mime = _IMAGE_MIME.get(ext) or mimetypes.guess_type(str(path))[0]
        if not mime or not mime.startswith("image/"):
            mime = "image/jpeg"

        raw_bytes = path.read_bytes()
        b64 = base64.standard_b64encode(raw_bytes).decode("ascii")
        logger.debug("[Media] Imagen local codificada: %s (%s, %d bytes)", path.name, mime, len(raw_bytes))
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _is_web_url(value: str) -> bool:
        """True si el valor es una URL http(s) válida."""
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    @staticmethod
    def _normalize_local_image_path(value: str) -> Path:
        """Normaliza rutas locales (Windows/Unix, relativas, ~)."""
        expanded = os.path.expanduser(value)
        path = Path(expanded)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def download_image_to_temp(self, url: str, dest_dir: Optional[str] = None) -> str:
        """
        Descarga una imagen remota a disco (útil antes de reenviar por WhatsApp).
        Helper opcional para flujos que necesitan archivo local.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("download_image_to_temp requiere una URL http(s)")

        folder = Path(dest_dir or os.getenv("MEDIA_TEMP_DIR", "app/storage_vault/media_temp"))
        folder.mkdir(parents=True, exist_ok=True)

        suffix = Path(parsed.path).suffix or ".jpg"
        dest = folder / f"download_{abs(hash(url)) % 10_000_000}{suffix}"

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as http:
                resp = http.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return str(dest.resolve())
        except Exception as exc:
            raise RuntimeError(f"No se pudo descargar imagen: {exc}") from exc


# Singleton lazy para routers y agentes
_service: OpenAIMediaService | None = None


def get_media_service() -> OpenAIMediaService:
    """Instancia compartida del servicio de medios."""
    global _service
    if _service is None:
        _service = OpenAIMediaService()
    return _service
