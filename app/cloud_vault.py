# app/cloud_vault.py
"""
Cloud Vault — Gestión de archivos en AWS S3.
Expone:
  POST /cloud-vault/upload   → sube un archivo y devuelve su clave S3
  GET  /cloud-vault/url/{key} → genera una URL firmada temporal
"""

import os
import uuid
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

# ── Configuración ─────────────────────────────────────────────────────────────
AWS_REGION      = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET       = os.environ.get("S3_BUCKET", "")          # obligatorio en prod
URL_EXPIRY_SECS = int(os.environ.get("S3_URL_EXPIRY", 3600))  # 1 hora por defecto

router = APIRouter()


def _s3_client():
    """Devuelve un cliente S3 autenticado vía variables de entorno o IAM Role."""
    return boto3.client("s3", region_name=AWS_REGION)


# ── Funciones reutilizables (importables desde otros módulos) ──────────────────

def upload_file_to_s3(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    folder: str = "uploads",
) -> str:
    """
    Sube bytes a S3 y devuelve la clave del objeto.

    Args:
        file_bytes:   Contenido binario del archivo.
        filename:     Nombre original del archivo.
        content_type: MIME type del archivo.
        folder:       Carpeta virtual dentro del bucket.

    Returns:
        Clave S3 del objeto (str), p.ej. "uploads/abc123_foto.jpg"

    Raises:
        RuntimeError: Si la variable S3_BUCKET no está configurada.
        ClientError:  Si AWS rechaza la operación.
    """
    if not S3_BUCKET:
        raise RuntimeError("La variable de entorno S3_BUCKET no está configurada.")

    unique_key = f"{folder}/{uuid.uuid4().hex}_{filename}"
    client = _s3_client()

    client.put_object(
        Bucket=S3_BUCKET,
        Key=unique_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return unique_key


def generate_presigned_url(s3_key: str, expiry_seconds: int = URL_EXPIRY_SECS) -> str:
    """
    Genera una URL firmada para acceso temporal a un objeto S3.

    Args:
        s3_key:         Clave del objeto en S3.
        expiry_seconds: Segundos de validez de la URL.

    Returns:
        URL firmada (str).

    Raises:
        RuntimeError: Si S3_BUCKET no está configurado.
        ClientError:  Si AWS no puede generar la URL.
    """
    if not S3_BUCKET:
        raise RuntimeError("La variable de entorno S3_BUCKET no está configurada.")

    client = _s3_client()
    url = client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": S3_BUCKET, "Key": s3_key},
        ExpiresIn=expiry_seconds,
    )
    return url


_MOCK_S3_DIR = os.path.join(os.path.dirname(__file__), "agents", "mock_s3")


def get_s3_text_file(key: str) -> str:
    """
    Descarga y devuelve el contenido de un archivo .txt.

    Modo LOCAL (sin AWS): si S3_BUCKET no está configurado, busca el archivo
    en './app/agents/mock_s3/' ignorando el prefijo 'config/' de la clave.
    Ejemplo: key="config/heladeria_nfc/prompt.txt"
             → lee  ./app/agents/mock_s3/heladeria_nfc/prompt.txt

    Modo PRODUCCIÓN: descarga el objeto desde S3 usando las credenciales AWS.

    Args:
        key: Clave del objeto en S3 (p.ej. "config/cliente1/prompt.txt").

    Returns:
        Contenido del archivo como string.

    Raises:
        FileNotFoundError: En modo local si el archivo mock no existe.
        RuntimeError:      En modo prod si S3_BUCKET no está configurado.
        ClientError:       En modo prod si AWS rechaza la operación.
    """
    if not S3_BUCKET:
        # Modo local: quitar el prefijo "config/" y buscar en mock_s3/
        relative_key = key.removeprefix("config/")
        local_path = os.path.join(_MOCK_S3_DIR, relative_key)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(
                f"[Mock S3] Archivo no encontrado: {local_path}\n"
                f"Crea el archivo o configura S3_BUCKET para usar AWS."
            )
        print(f"[Mock S3] Leyendo archivo local: {local_path}")
        with open(local_path, encoding="utf-8") as f:
            return f.read()

    client = _s3_client()
    response = client.get_object(Bucket=S3_BUCKET, Key=key)
    return response["Body"].read().decode("utf-8")


# ── Endpoints HTTP ─────────────────────────────────────────────────────────────

@router.post("/upload", summary="Sube un archivo a S3")
async def upload_file(file: UploadFile = File(...)):
    """
    Recibe un archivo multipart y lo almacena en S3.
    Devuelve la clave S3 asignada al objeto.
    """
    try:
        content = await file.read()
        s3_key = upload_file_to_s3(
            file_bytes=content,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
        )
        return JSONResponse({"s3_key": s3_key, "bucket": S3_BUCKET})

    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Error AWS S3: {exc}")


@router.get("/url/{s3_key:path}", summary="Genera URL firmada para un objeto S3")
def get_signed_url(s3_key: str, expiry: int = URL_EXPIRY_SECS):
    """
    Genera una URL pre-firmada temporal para el objeto indicado.

    - **s3_key**: clave del objeto en S3 (puede incluir carpetas, p.ej. uploads/file.jpg)
    - **expiry**: segundos de validez (por defecto 3600)
    """
    try:
        url = generate_presigned_url(s3_key, expiry_seconds=expiry)
        return {"url": url, "expires_in_seconds": expiry}

    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(status_code=502, detail=f"Error AWS S3: {exc}")
