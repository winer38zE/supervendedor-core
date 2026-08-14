"""
app/services/gemini_service.py
────────────────────────────────────────────────────────────────────────────────
Servicio Google Gemini 2.0 Flash — alto volumen / bajo costo.

Casos de uso ED NET PRO:
  - Lectura de catálogos PDF largos
  - Extracción estructurada JSON desde comprobantes de pago e imágenes de producto
  - Datos listos para persistir en PocketBase

Requisitos:
  - pip install google-genai
  - GEMINI_API_KEY en .env
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

_DEFAULT_RECEIPT_PROMPT = (
    "Analiza esta imagen (comprobante de pago, factura o foto de producto). "
    "Devuelve SOLO un JSON válido con claves cuando aplique: "
    "tipo_documento, monto, moneda, numero_transaccion, banco_emisor, fecha, "
    "referencia, producto, talla, color, descripcion, confianza (0-1). "
    "Usa null para campos no visibles."
)


class GeminiService:
    """
    Wrapper Gemini 2.0 Flash para documentos pesados y visión estructurada.

    Si GEMINI_API_KEY no está configurada, is_available=False y los métodos
    lanzan RuntimeError controlado sin tumbar FastAPI.
    """

    def __init__(self, *, api_key: Optional[str] = None) -> None:
        self._api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.client = None

        if not self._api_key:
            logger.warning(
                "[Gemini] GEMINI_API_KEY no configurada — GeminiService desactivado. "
                "Añade la clave en .env para catálogos PDF y extracción de comprobantes."
            )
            return

        try:
            from google import genai

            self.client = genai.Client(api_key=self._api_key)
            logger.info("[Gemini] GeminiService inicializado (modelo=%s)", GEMINI_MODEL)
        except ImportError:
            logger.error(
                "[Gemini] Paquete 'google-genai' no instalado. Ejecuta: pip install google-genai"
            )
        except Exception as exc:
            logger.exception("[Gemini] Error inicializando cliente: %s", exc)

    @property
    def is_available(self) -> bool:
        """True si el cliente Gemini está listo."""
        return self.client is not None

    def _require_client(self):
        if not self.is_available:
            raise RuntimeError(
                "GeminiService no disponible — configura GEMINI_API_KEY e instala google-genai"
            )
        return self.client

    # ── Método 1: Catálogos / PDFs ───────────────────────────────────────────

    def analyze_pdf_catalog(self, file_path: str, prompt: str) -> str:
        """
        Sube un PDF o documento pesado vía Files API y devuelve texto analizado.

        Args:
            file_path: Ruta local al PDF/catálogo.
            prompt:    Instrucción de análisis (resumen, productos, precios, etc.).

        Returns:
            Texto generado por Gemini.

        Raises:
            FileNotFoundError, RuntimeError
        """
        client = self._require_client()
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        prompt = (prompt or "Resume y extrae los productos clave de este catálogo.").strip()
        uploaded = None

        try:
            uploaded = client.files.upload(file=str(path.resolve()))
            self._wait_until_active(uploaded)

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded, prompt],
            )
            text = (getattr(response, "text", None) or "").strip()
            if not text:
                raise RuntimeError("Gemini devolvió respuesta vacía para el catálogo PDF")
            logger.info("[Gemini] PDF analizado (%s) — %s chars", path.name, len(text))
            return text

        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception("[Gemini] analyze_pdf_catalog falló: %s", path.name)
            raise RuntimeError(f"Error analizando catálogo PDF: {exc}") from exc
        finally:
            self._delete_remote_file(uploaded)

    # ── Método 2: Imágenes / comprobantes ─────────────────────────────────────

    def analyze_image_or_receipt(self, image_path_or_url: str, prompt: str) -> dict:
        """
        Extrae datos estructurados de una imagen (comprobante o producto).

        Args:
            image_path_or_url: Ruta local o URL https://...
            prompt:            Instrucción; si está vacía usa prompt por defecto de recibo.

        Returns:
            dict listo para insertar/actualizar en PocketBase.
        """
        client = self._require_client()
        raw_input = (image_path_or_url or "").strip()
        if not raw_input:
            raise ValueError("image_path_or_url no puede estar vacío")

        prompt = (prompt or _DEFAULT_RECEIPT_PROMPT).strip()
        temp_path: Optional[Path] = None

        try:
            from google.genai import types

            local_path, temp_path = self._resolve_image_path(raw_input)
            mime_type = self._mime_for_path(local_path)
            image_bytes = local_path.read_bytes()

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            raw_text = (getattr(response, "text", None) or "").strip()
            data = self._parse_json_text(raw_text)
            data.setdefault("fuente_imagen", raw_input)
            data.setdefault("modelo", GEMINI_MODEL)
            logger.info("[Gemini] Imagen analizada — claves: %s", list(data.keys()))
            return data

        except (ValueError, RuntimeError):
            raise
        except Exception as exc:
            logger.exception("[Gemini] analyze_image_or_receipt falló: %s", raw_input[:80])
            raise RuntimeError(f"Error analizando imagen: {exc}") from exc
        finally:
            if temp_path and temp_path.is_file():
                try:
                    temp_path.unlink()
                except OSError as exc:
                    logger.debug("[Gemini] No se pudo borrar temp %s: %s", temp_path, exc)

    # ── Método 3: Extracción JSON genérica ────────────────────────────────────

    def extract_json_data(self, file_path: str, prompt: str) -> dict:
        """
        Sube un archivo, fuerza respuesta JSON y devuelve un dict parseado.

        Útil para PDFs/tablas donde se necesita estructura directa en PocketBase.

        Args:
            file_path: Ruta local al archivo (PDF, imagen, etc.).
            prompt:    Instrucción que describe el JSON esperado.

        Returns:
            dict parseado y limpio.
        """
        client = self._require_client()
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        prompt = (
            prompt or "Extrae la información relevante y responde SOLO con JSON válido."
        ).strip()
        uploaded = None

        try:
            from google.genai import types

            uploaded = client.files.upload(file=str(path.resolve()))
            self._wait_until_active(uploaded)

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            raw_text = (getattr(response, "text", None) or "").strip()
            data = self._parse_json_text(raw_text)
            data.setdefault("archivo_origen", path.name)
            data.setdefault("modelo", GEMINI_MODEL)
            logger.info("[Gemini] JSON extraído de %s — %s claves", path.name, len(data))
            return data

        except (FileNotFoundError, RuntimeError, ValueError):
            raise
        except Exception as exc:
            logger.exception("[Gemini] extract_json_data falló: %s", path.name)
            raise RuntimeError(f"Error extrayendo JSON: {exc}") from exc
        finally:
            self._delete_remote_file(uploaded)

    # ── Helpers internos ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_text(raw: str) -> Dict[str, Any]:
        """Limpia bloques ```json ... ``` y parsea a dict."""
        text = (raw or "").strip()
        if not text:
            raise ValueError("Respuesta vacía — no se pudo extraer JSON")

        # Quitar fences markdown
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        else:
            brace = re.search(r"(\{.*\})", text, re.DOTALL)
            if brace:
                text = brace.group(1).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("[Gemini] JSON inválido: %s", text[:200])
            raise ValueError(f"No se pudo parsear JSON de Gemini: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("La respuesta JSON debe ser un objeto (dict)")
        return parsed

    def _wait_until_active(self, uploaded: Any, *, timeout_sec: int = 120) -> None:
        """Espera a que un archivo remoto pase de PROCESSING a ACTIVE."""
        if uploaded is None:
            return

        state = getattr(uploaded, "state", None)
        if state is None or str(state) == "ACTIVE":
            return

        client = self._require_client()
        name = getattr(uploaded, "name", None)
        if not name:
            return

        deadline = time.time() + timeout_sec
        while str(getattr(uploaded, "state", "")) == "PROCESSING" and time.time() < deadline:
            time.sleep(2)
            uploaded = client.files.get(name=name)

        if str(getattr(uploaded, "state", "")) == "FAILED":
            raise RuntimeError(f"Procesamiento remoto falló para archivo: {name}")

    def _delete_remote_file(self, uploaded: Any) -> None:
        """Elimina archivo subido a Gemini tras procesarlo (ahorro y privacidad)."""
        if uploaded is None or not self.is_available:
            return
        name = getattr(uploaded, "name", None)
        if not name:
            return
        try:
            self.client.files.delete(name=name)
            logger.debug("[Gemini] Archivo remoto eliminado: %s", name)
        except Exception as exc:
            logger.debug("[Gemini] No se pudo eliminar archivo remoto %s: %s", name, exc)

    def _resolve_image_path(self, image_input: str) -> tuple[Path, Optional[Path]]:
        """Devuelve (path_local, temp_path_opcional)."""
        raw = image_input.strip().strip('"').strip("'")
        if self._is_web_url(raw):
            temp = self._download_image(raw)
            return temp, temp
        path = Path(raw).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Imagen no encontrada: {image_input}")
        return path.resolve(), None

    @staticmethod
    def _is_web_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    def _download_image(self, url: str) -> Path:
        """Descarga imagen remota a carpeta temporal del proyecto."""
        folder = Path(os.getenv("MEDIA_TEMP_DIR", "app/storage_vault/media_temp"))
        folder.mkdir(parents=True, exist_ok=True)
        suffix = Path(urlparse(url).path).suffix or ".jpg"
        dest = folder / f"gemini_img_{abs(hash(url)) % 10_000_000}{suffix}"

        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as http:
                resp = http.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            return dest.resolve()
        except Exception as exc:
            raise RuntimeError(f"No se pudo descargar imagen: {exc}") from exc

    @staticmethod
    def _mime_for_path(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in _IMAGE_MIME:
            return _IMAGE_MIME[ext]
        guessed, _ = mimetypes.guess_type(str(path))
        return guessed or "application/octet-stream"


# Singleton lazy — mismo patrón que media_service / llm_router
_service: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """Instancia compartida del servicio Gemini."""
    global _service
    if _service is None:
        _service = GeminiService()
    return _service
