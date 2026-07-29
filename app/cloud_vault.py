"""
Local Vault — Gestión de archivos en el almacenamiento local del VPS Hetzner.
Mantiene compatibilidad exacta de funciones para evitar romper otros módulos.
Expone:
  POST /cloud-vault/upload        → sube un archivo al disco local del VPS
  GET  /cloud-vault/url/{key}     → devuelve la URL pública del archivo en el servidor
  GET  /cloud-vault/files/{path}  → endpoint público para servir las imágenes a WhatsApp
"""

import os
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, FileResponse

# ── Configuración Local para Hetzner VPS ──────────────────────────────────────
# Directorio físico en el VPS donde se guardarán los archivos/imágenes
STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR", os.path.join(os.path.dirname(__file__), "storage_vault"))
# Tu IP de Hetzner o Dominio de producción (Se lee del .env para flexibilidad)
BASE_URL = os.environ.get("BASE_URL", "http://178.105.48.103:8000")

# Asegura que la carpeta contenedora exista en el servidor
os.makedirs(STORAGE_DIR, exist_ok=True)

router = APIRouter()

# ── Funciones Compatibles (Mismo nombre, lógica interna local) ──────────────────

def upload_file_to_s3(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    folder: str = "uploads",
) -> str:
    """
    Sube los bytes del archivo directamente a una carpeta en el disco del VPS.
    Mantiene el nombre de la función para no dañar las importaciones de otros routers.
    """
    # Generar subcarpeta (ej: storage_vault/uploads)
    folder_path = os.path.join(STORAGE_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    
    # Crear un nombre único para evitar colisiones de archivos de ropa o imágenes
    unique_key = f"{folder}/{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(STORAGE_DIR, unique_key)
    
    # Escribir el archivo binario en el disco local
    with open(full_path, "wb") as f:
        f.write(file_bytes)
        
    return unique_key


def generate_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    """
    En lugar de una URL firmada de AWS, genera el enlace público directo
    hacia el nuevo endpoint de descarga que lee del disco local.
    """
    # El prefijo '/cloud-vault' se asume al incluir el router en main.py
    return f"{BASE_URL}/cloud-vault/files/{s3_key}"


def get_s3_text_file(key: str) -> str:
    """
    Lee archivos de configuración o prompts directamente del disco local.
    Si no existe, mantiene el fallback al sistema de mocks original.
    """
    full_path = os.path.join(STORAGE_DIR, key)
    
    if os.path.isfile(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
            
    # Fallback al Mock original por si estás en entorno local de pruebas
    _MOCK_S3_DIR = os.path.join(os.path.dirname(__file__), "agents", "mock_s3")
    relative_key = key.removeprefix("config/")
    local_path = os.path.join(_MOCK_S3_DIR, relative_key)
    
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Archivo no localizado en almacenamiento local ni mock: {key}")
        
    print(f"[Mock Local] Leyendo configuración local: {local_path}")
    with open(local_path, "r", encoding="utf-8") as f:
        return f.read()


# ── Endpoints HTTP Actualizados ───────────────────────────────────────────────

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
        raise HTTPException(status_code=500, detail=f"Error de almacenamiento local: {str(exc)}")


@router.get("/url/{s3_key:path}", summary="Genera la URL de acceso para el archivo")
def get_signed_url(s3_key: str, expiry: int = 3600):
    try:
        url = generate_presigned_url(s3_key, expiry_seconds=expiry)
        return {"url": url, "expires_in_seconds": expiry}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── NUEVO ENDPOINT: Servidor de archivos estáticos nativo ──────────────────────
@router.get("/files/{file_key:path}", summary="Sirve de forma pública las imágenes guardadas")
def serve_file(file_key: str):
    """
    Este endpoint es vital. Permite que Evolution API, n8n o cualquier navegador
    pueda acceder y descargar las imágenes del catálogo directamente desde tu VPS.
    """
    full_path = os.path.join(STORAGE_DIR, file_key)
    
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="El archivo solicitado no existe en el servidor.")
        
    return FileResponse(full_path)"""
Local Vault — Gestión de archivos en el almacenamiento local del VPS Hetzner.
Mantiene compatibilidad exacta de funciones para evitar romper otros módulos.
Expone:
  POST /cloud-vault/upload        → sube un archivo al disco local del VPS
  GET  /cloud-vault/url/{key}     → devuelve la URL pública del archivo en el servidor
  GET  /cloud-vault/files/{path}  → endpoint público para servir las imágenes a WhatsApp
"""

import os
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, FileResponse

# ── Configuración Local para Hetzner VPS ──────────────────────────────────────
# Directorio físico en el VPS donde se guardarán los archivos/imágenes
STORAGE_DIR = os.environ.get("LOCAL_STORAGE_DIR", os.path.join(os.path.dirname(__file__), "storage_vault"))
# Tu IP de Hetzner o Dominio de producción (Se lee del .env para flexibilidad)
BASE_URL = os.environ.get("BASE_URL", "http://178.105.48.103:8000")

# Asegura que la carpeta contenedora exista en el servidor
os.makedirs(STORAGE_DIR, exist_ok=True)

router = APIRouter()

# ── Funciones Compatibles (Mismo nombre, lógica interna local) ──────────────────

def upload_file_to_s3(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    folder: str = "uploads",
) -> str:
    """
    Sube los bytes del archivo directamente a una carpeta en el disco del VPS.
    Mantiene el nombre de la función para no dañar las importaciones de otros routers.
    """
    # Generar subcarpeta (ej: storage_vault/uploads)
    folder_path = os.path.join(STORAGE_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    
    # Crear un nombre único para evitar colisiones de archivos de ropa o imágenes
    unique_key = f"{folder}/{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(STORAGE_DIR, unique_key)
    
    # Escribir el archivo binario en el disco local
    with open(full_path, "wb") as f:
        f.write(file_bytes)
        
    return unique_key


def generate_presigned_url(s3_key: str, expiry_seconds: int = 3600) -> str:
    """
    En lugar de una URL firmada de AWS, genera el enlace público directo
    hacia el nuevo endpoint de descarga que lee del disco local.
    """
    # El prefijo '/cloud-vault' se asume al incluir el router en main.py
    return f"{BASE_URL}/cloud-vault/files/{s3_key}"


def get_s3_text_file(key: str) -> str:
    """
    Lee archivos de configuración o prompts directamente del disco local.
    Si no existe, mantiene el fallback al sistema de mocks original.
    """
    full_path = os.path.join(STORAGE_DIR, key)
    
    if os.path.isfile(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
            
    # Fallback al Mock original por si estás en entorno local de pruebas
    _MOCK_S3_DIR = os.path.join(os.path.dirname(__file__), "agents", "mock_s3")
    relative_key = key.removeprefix("config/")
    local_path = os.path.join(_MOCK_S3_DIR, relative_key)
    
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Archivo no localizado en almacenamiento local ni mock: {key}")
        
    print(f"[Mock Local] Leyendo configuración local: {local_path}")
    with open(local_path, "r", encoding="utf-8") as f:
        return f.read()


# ── Endpoints HTTP Actualizados ───────────────────────────────────────────────

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
        raise HTTPException(status_code=500, detail=f"Error de almacenamiento local: {str(exc)}")


@router.get("/url/{s3_key:path}", summary="Genera la URL de acceso para el archivo")
def get_signed_url(s3_key: str, expiry: int = 3600):
    try:
        url = generate_presigned_url(s3_key, expiry_seconds=expiry)
        return {"url": url, "expires_in_seconds": expiry}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── NUEVO ENDPOINT: Servidor de archivos estáticos nativo ──────────────────────
@router.get("/files/{file_key:path}", summary="Sirve de forma pública las imágenes guardadas")
def serve_file(file_key: str):
    """
    Este endpoint es vital. Permite que Evolution API, n8n o cualquier navegador
    pueda acceder y descargar las imágenes del catálogo directamente desde tu VPS.
    """
    full_path = os.path.join(STORAGE_DIR, file_key)
    
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="El archivo solicitado no existe en el servidor.")
        
    return FileResponse(full_path)