"""
Local Vault — Almacenamiento en disco del VPS (Hetzner).
No usa Supabase; prompts/config se leen de disco local o mock_s3.
Metadatos opcionales en PocketBase vía app/database/pocketbase_client.py.
"""

import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

STORAGE_DIR = os.environ.get(
    "LOCAL_STORAGE_DIR", os.path.join(os.path.dirname(__file__), "storage_vault")
)
BASE_URL = os.environ.get("BASE_URL", "http://178.105.48.103:8000")

os.makedirs(STORAGE_DIR, exist_ok=True)

router = APIRouter()


def upload_file_to_s3(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    folder: str = "uploads",
) -> str:
    folder_path = os.path.join(STORAGE_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    unique_key = f"{folder}/{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(STORAGE_DIR, unique_key)
    with open(full_path, "wb") as f:
        f.write(file_bytes)
    return unique_key


def generate_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    return f"{BASE_URL}/cloud-vault/files/{s3_key}"


def get_s3_text_file(key: str) -> str:
    full_path = os.path.join(STORAGE_DIR, key)
    if os.path.isfile(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    _MOCK_S3_DIR = os.path.join(os.path.dirname(__file__), "agents", "mock_s3")
    relative_key = key.removeprefix("config/")
    local_path = os.path.join(_MOCK_S3_DIR, relative_key)

    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Archivo no localizado: {key}")

    with open(local_path, "r", encoding="utf-8") as f:
        return f.read()


@router.post("/upload", summary="Sube un archivo al almacenamiento del VPS")
async def upload_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        file_key = upload_file_to_s3(
            file_bytes=content,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
        )
        return JSONResponse({"s3_key": file_key, "bucket": "local-vps-hetzner"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error de almacenamiento local: {exc}")


@router.get("/url/{s3_key:path}", summary="Genera la URL de acceso para el archivo")
def get_signed_url(s3_key: str, expiry: int = 3600):
    try:
        url = generate_presigned_url(s3_key, expiry_seconds=expiry)
        return {"url": url, "expires_in_seconds": expiry}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/files/{file_key:path}", summary="Sirve imágenes/archivos públicos")
def serve_file(file_key: str):
    full_path = os.path.join(STORAGE_DIR, file_key)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(full_path)
