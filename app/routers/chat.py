"""
app/routers/chat.py
────────────────────────────────────────────────────────────────────────────────
Orquestador unificado de chat para n8n.

Pipeline:
  Multimodal (Whisper/Visión) → PocketBase (lead/conversación/handoff)
  → Mem0 (contexto) → LLMRouter (OpenAI/Claude) → persistencia → TTS opcional

Endpoint: POST /api/v1/chat
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.security import verify_api_key
from app.services.gemini_service import get_gemini_service
from app.services.llm_router import ModelPreference, get_llm_router
from app.services.media_service import get_media_service
from app.services.memory_service import get_customer_memory

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Chat"],
    dependencies=[Depends(verify_api_key)],
)

def _collection_candidates(env_key: str, default: str, *fallbacks: str) -> list[str]:
    primary = os.getenv(env_key, default)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in (primary, default, *fallbacks):
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


LEADS_CANDIDATES = _collection_candidates("CHAT_LEADS_COLLECTION", "leads", "leads_crm")
CONV_CANDIDATES = _collection_candidates(
    "CHAT_CONVERSATIONS_COLLECTION", "conversations", "chat_conversations"
)
MSG_CANDIDATES = _collection_candidates("CHAT_MESSAGES_COLLECTION", "messages", "chat_messages")
EXTRACTION_CANDIDATES = _collection_candidates(
    "CHAT_EXTRACTIONS_COLLECTION", "media_extractions", "image_extractions"
)

_COLLECTION_CACHE: dict[str, Optional[str]] = {}
TENANT_ID = os.getenv("CHAT_TENANT_ID", settings.OWNER_ID)
MEDIA_TEMP_DIR = Path(os.getenv("MEDIA_TEMP_DIR", "app/storage_vault/media_temp"))

_AUDIO_EXT = {".ogg", ".mp3", ".m4a", ".wav", ".webm", ".mpeg", ".mpga"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# ══════════════════════════════════════════════════════════════════════════════
# Esquemas Pydantic
# ══════════════════════════════════════════════════════════════════════════════


class ChatRequest(BaseModel):
    phone: str = Field(..., description="Número del cliente")
    message: Optional[str] = Field("", description="Texto del mensaje")
    message_type: Literal["text", "audio", "image"] = Field(
        "text", description="Tipo: text | audio | image"
    )
    media_url: Optional[str] = Field(
        None, description="Ruta local o URL de audio/imagen"
    )
    respond_with_audio: bool = Field(
        False, description="Generar respuesta en audio (TTS)"
    )
    provider: ModelPreference = Field(
        "auto", description="Enrutamiento LLM: auto | openai | claude"
    )


class ChatResponse(BaseModel):
    response_text: str
    audio_path: Optional[str] = None
    bot_active: bool = True
    lead_id: str
    conversation_id: str
    model_used: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Endpoint principal
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/chat", response_model=ChatResponse)
async def chat_orchestrator(body: ChatRequest) -> ChatResponse:
    """Orquestador unificado — punto de entrada para n8n / WhatsApp externo."""
    phone = _normalize_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Número de teléfono inválido")

    try:
        # 1) Multimodal: audio → Whisper | imagen → Gemini (fallback OpenAI)
        user_text, image_extraction = await _process_multimodal_input(body)

        # 2) Lead + conversación activa (PocketBase)
        lead_id = _get_or_create_lead(phone)
        conversation_id, bot_active = _get_or_create_conversation(phone, lead_id)

        # 2b) Datos estructurados de imagen → PocketBase
        if image_extraction and body.message_type == "image":
            _persist_image_extraction(
                phone,
                lead_id,
                conversation_id,
                (body.media_url or "").strip(),
                image_extraction,
            )

        # 3) Handoff humano — bot pausado
        if not bot_active:
            return ChatResponse(
                response_text=(
                    "Un asesor humano está atendiendo tu conversación. "
                    "El bot está pausado temporalmente — te responderemos pronto."
                ),
                audio_path=None,
                bot_active=False,
                lead_id=lead_id,
                conversation_id=conversation_id,
                model_used="handoff",
            )

        # 4) Contexto Mem0
        memory = get_customer_memory()
        memory_context = ""
        if memory.is_available:
            memory_context = memory.get_memories_context(phone, user_text)

        # 5) Respuesta híbrida OpenAI / Claude
        system_prompt = _build_system_prompt(user_text, memory_context)
        llm = get_llm_router()
        bot_reply, model_used = llm.generate_response(
            system_prompt, user_text, body.provider
        )

        # 6) Persistencia PocketBase + Mem0
        _persist_message(conversation_id, lead_id, phone, "user", user_text, body)
        _persist_message(
            conversation_id,
            lead_id,
            phone,
            "assistant",
            bot_reply,
            message_type="text",
            media_url=None,
        )
        if memory.is_available:
            memory.save_interaction(phone, user_text, bot_reply)

        # 7) TTS opcional
        audio_path: Optional[str] = None
        if body.respond_with_audio:
            audio_path = _generate_audio_reply(bot_reply)

        return ChatResponse(
            response_text=bot_reply,
            audio_path=audio_path,
            bot_active=True,
            lead_id=lead_id,
            conversation_id=conversation_id,
            model_used=model_used,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[Chat] Error orquestador phone=%s", body.phone)
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando chat: {exc}",
        ) from exc


# ══════════════════════════════════════════════════════════════════════════════
# System prompt
# ══════════════════════════════════════════════════════════════════════════════


def _build_system_prompt(user_text: str, memory_context: str) -> str:
    """Ensambla el system prompt con identidad, Mem0 y catálogo/ZOPA."""
    parts = [
        "Eres el Super Vendedor de ED NET PRO — ropa deportiva estilo Shein en Colombia.",
        "Vendes con empatía, urgencia sana y enfoque en pago contra entrega en Cúcuta.",
        "Responde en español colombiano, máximo 4 oraciones, sin markdown.",
        "Cierra con una pregunta o llamado a la acción cuando tenga sentido.",
    ]
    if memory_context:
        parts.append(memory_context)

    try:
        from app.agents.catalog_bridge_agent import get_catalog_bridge

        bridge = get_catalog_bridge()
        zopa = bridge.get_zopa_for_message(user_text)
        parts.append(
            f"Producto contextual: {zopa.get('titulo', 'catálogo')}. "
            f"Precio objetivo: ${zopa.get('target_price', 0):,.0f} COP. "
            f"Precio mínimo: ${zopa.get('reserve_price', 0):,.0f} COP."
        )
    except Exception as exc:
        logger.debug("[Chat] Catalog bridge omitido: %s", exc)

    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Multimodal
# ══════════════════════════════════════════════════════════════════════════════


async def _process_multimodal_input(body: ChatRequest) -> tuple[str, Optional[dict]]:
    """Normaliza entrada a texto. Para imágenes devuelve también JSON extraído por Gemini."""
    base_text = (body.message or "").strip()
    media = (body.media_url or "").strip()
    msg_type = body.message_type
    media_svc = get_media_service()

    if msg_type == "audio":
        if not media:
            raise HTTPException(status_code=400, detail="message_type=audio requiere media_url")
        if not media_svc.is_available:
            raise HTTPException(status_code=503, detail="Servicio Whisper no disponible")
        local_path = await _ensure_local_media(media, kind="audio")
        transcript = media_svc.transcribe_audio(local_path)
        combined = f"{base_text}\n{transcript}".strip() if base_text else transcript.strip()
        if not combined:
            raise HTTPException(status_code=400, detail="No se pudo transcribir el audio")
        return combined, None

    if msg_type == "image":
        if not media:
            raise HTTPException(status_code=400, detail="message_type=image requiere media_url")

        image_source = media
        if not _is_web_url(media) and not Path(media).is_file():
            image_source = await _ensure_local_media(media, kind="image")

        extraction: Optional[dict] = None
        analysis = ""

        # Prioridad: Gemini 2.0 Flash (JSON estructurado, bajo costo)
        gemini = get_gemini_service()
        if gemini.is_available:
            try:
                extraction = gemini.analyze_image_or_receipt(image_source, "")
                analysis = _format_extraction_summary(extraction)
                logger.info("[Chat] Imagen procesada con Gemini — tipo=%s", extraction.get("tipo_documento"))
            except Exception as exc:
                logger.warning("[Chat] Gemini imagen falló, fallback OpenAI: %s", exc)

        # Fallback: visión OpenAI
        if not analysis:
            if not media_svc.is_available:
                raise HTTPException(
                    status_code=503,
                    detail="Servicios de visión no disponibles (Gemini/OpenAI)",
                )
            prompt = (
                "Eres un vendedor de ropa deportiva ED NET PRO en Colombia. "
                "Analiza la imagen: ¿es producto, comprobante de pago o consulta? "
                "Extrae datos útiles (monto, referencia, talla, color, producto). "
                "Responde en español de forma concisa."
            )
            analysis = media_svc.analyze_image(image_source, prompt)

        if base_text:
            user_text = f"{base_text}\n[Análisis imagen]: {analysis}".strip()
        else:
            user_text = f"[Análisis imagen]: {analysis}"

        return user_text, extraction

    if base_text:
        return base_text, None

    raise HTTPException(
        status_code=400,
        detail="Se requiere message, media_url o message_type válido",
    )


def _format_extraction_summary(data: dict) -> str:
    """Resume el JSON de Gemini para el prompt del LLM de ventas."""
    tipo = str(data.get("tipo_documento") or "imagen")
    parts = [f"Tipo detectado: {tipo}"]

    monto = data.get("monto")
    if monto is not None:
        moneda = data.get("moneda") or "COP"
        parts.append(f"Monto: {monto} {moneda}")

    for key, label in (
        ("numero_transaccion", "Transacción"),
        ("banco_emisor", "Banco"),
        ("referencia", "Referencia"),
        ("fecha", "Fecha"),
        ("producto", "Producto"),
        ("talla", "Talla"),
        ("color", "Color"),
        ("descripcion", "Detalle"),
    ):
        val = data.get(key)
        if val:
            parts.append(f"{label}: {val}")

    conf = data.get("confianza")
    if conf is not None:
        parts.append(f"Confianza extracción: {conf}")

    return ". ".join(parts)


def _is_web_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def _ensure_local_media(url_or_path: str, *, kind: str) -> str:
    if _is_web_url(url_or_path):
        return await _download_media(url_or_path, kind=kind)
    path = Path(url_or_path)
    if path.is_file():
        return str(path.resolve())
    raise HTTPException(status_code=400, detail=f"Archivo {kind} no encontrado: {url_or_path}")


async def _download_media(url: str, *, kind: str) -> str:
    MEDIA_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(url).path).suffix or (".ogg" if kind == "audio" else ".jpg")
    dest = MEDIA_TEMP_DIR / f"chat_{kind}_{uuid.uuid4().hex[:8]}{suffix}"
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return str(dest.resolve())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo descargar {kind}: {exc}") from exc


def _generate_audio_reply(text: str) -> Optional[str]:
    media = get_media_service()
    if not media.is_available:
        return None
    try:
        out_dir = MEDIA_TEMP_DIR / "tts_replies"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"reply_{uuid.uuid4().hex[:8]}.mp3"
        return media.generate_voice_response(text, str(out_path), voice="nova")
    except Exception as exc:
        logger.warning("[Chat] TTS falló: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PocketBase
# ══════════════════════════════════════════════════════════════════════════════


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in (phone or "") if c.isdigit())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pb_quote(value: str) -> str:
    return f"'{str(value).replace(chr(39), chr(92) + chr(39))}'"


def _resolve_collection(kind: str, candidates: list[str]) -> Optional[str]:
    if kind in _COLLECTION_CACHE:
        return _COLLECTION_CACHE[kind]

    from app.database.pocketbase_client import collection_exists

    for name in candidates:
        try:
            if collection_exists(name):
                _COLLECTION_CACHE[kind] = name
                logger.debug("[Chat] PocketBase '%s' → colección '%s'", kind, name)
                return name
        except Exception as exc:
            logger.debug("[Chat] Probe colección '%s': %s", name, exc)

    _COLLECTION_CACHE[kind] = None
    logger.debug("[Chat] PocketBase sin colección '%s' — modo local", kind)
    return None


def _get_or_create_lead(phone: str) -> str:
    collection = _resolve_collection("leads", LEADS_CANDIDATES)
    if not collection:
        return f"local-{phone}"

    try:
        from app.database.pocketbase_client import upsert_by_filter

        row = upsert_by_filter(
            collection,
            {
                "tenant_id": TENANT_ID,
                "telefono": phone,
                "fuente": "whatsapp",
                "estado": "contactado",
                "lead_score": 5,
                "metadata": {"canal": "n8n_chat", "ultimo_contacto": _now_iso()},
                "updated_at": _now_iso(),
            },
            unique_fields=["tenant_id", "telefono"],
            quiet=True,
        )
        if row and row.get("id"):
            return str(row["id"])
    except Exception as exc:
        logger.debug("[Chat] Lead PocketBase omitido: %s", exc)

    return f"local-{phone}"


def _get_or_create_conversation(phone: str, lead_id: str) -> tuple[str, bool]:
    collection = _resolve_collection("conversations", CONV_CANDIDATES)
    if not collection:
        return f"conv-{phone}", True

    try:
        from app.database.pocketbase_client import create_record, list_records, update_record

        filt = f"(tenant_id={_pb_quote(TENANT_ID)}&&telefono={_pb_quote(phone)}&&status='active')"
        existing = list_records(collection, filter_expr=filt, per_page=1, quiet=True)

        if existing:
            conv = existing[0]
            conv_id = str(conv["id"])
            bot_active = bool(conv.get("bot_active", True))
            update_record(
                collection,
                conv_id,
                {"updated_at": _now_iso(), "lead_id": lead_id},
                quiet=True,
            )
            return conv_id, bot_active

        created = create_record(
            collection,
            {
                "tenant_id": TENANT_ID,
                "telefono": phone,
                "lead_id": lead_id,
                "status": "active",
                "bot_active": True,
                "updated_at": _now_iso(),
            },
            quiet=True,
        )
        if created and created.get("id"):
            return str(created["id"]), bool(created.get("bot_active", True))

    except Exception as exc:
        logger.debug("[Chat] Conversación PocketBase omitida: %s", exc)

    return f"conv-{phone}", True


def _persist_message(
    conversation_id: str,
    lead_id: str,
    phone: str,
    role: str,
    content: str,
    body: ChatRequest | None = None,
    *,
    message_type: str = "text",
    media_url: Optional[str] = None,
) -> None:
    collection = _resolve_collection("messages", MSG_CANDIDATES)
    if not collection:
        return

    try:
        from app.database.pocketbase_client import create_record

        create_record(
            collection,
            {
                "conversation_id": conversation_id,
                "lead_id": lead_id,
                "telefono": phone,
                "role": role,
                "content": content,
                "message_type": body.message_type if body else message_type,
                "media_url": (body.media_url if body else media_url) or "",
                "created_at": _now_iso(),
            },
            quiet=True,
        )
    except Exception as exc:
        logger.debug("[Chat] Mensaje PocketBase omitido: %s", exc)


def _persist_image_extraction(
    phone: str,
    lead_id: str,
    conversation_id: str,
    media_url: str,
    extraction: dict,
) -> None:
    """Guarda JSON de Gemini en PocketBase y enriquece metadata del lead."""
    collection = _resolve_collection("extractions", EXTRACTION_CANDIDATES)
    if collection:
        try:
            from app.database.pocketbase_client import create_record

            create_record(
                collection,
                {
                    "tenant_id": TENANT_ID,
                    "telefono": phone,
                    "lead_id": lead_id,
                    "conversation_id": conversation_id,
                    "media_url": media_url,
                    "tipo_documento": extraction.get("tipo_documento") or "",
                    "datos_extraidos": extraction,
                    "modelo": extraction.get("modelo") or "gemini-2.0-flash",
                    "created_at": _now_iso(),
                },
                quiet=True,
            )
            logger.info("[Chat] Extracción Gemini guardada en '%s'", collection)
        except Exception as exc:
            logger.debug("[Chat] Extracción PocketBase omitida: %s", exc)

    _enrich_lead_from_extraction(phone, lead_id, extraction)


def _enrich_lead_from_extraction(phone: str, lead_id: str, extraction: dict) -> None:
    """Actualiza el lead con datos del comprobante/producto si la colección existe."""
    collection = _resolve_collection("leads", LEADS_CANDIDATES)
    if not collection or lead_id.startswith("local-"):
        return

    tipo = str(extraction.get("tipo_documento") or "").lower()
    metadata_patch = {
        "ultima_extraccion_imagen": _now_iso(),
        "gemini_extraction": extraction,
    }

    update_fields: dict = {
        "updated_at": _now_iso(),
        "metadata": metadata_patch,
    }

    # Comprobante de pago → elevar prioridad del lead
    if tipo in ("comprobante", "pago", "transferencia") or extraction.get("monto"):
        update_fields["estado"] = "calificado"
        update_fields["lead_score"] = 8
        nota = (
            f"Comprobante detectado — monto: {extraction.get('monto')} "
            f"{extraction.get('moneda') or 'COP'}"
        )
        if extraction.get("numero_transaccion"):
            nota += f" | ref: {extraction.get('numero_transaccion')}"
        update_fields["notas"] = nota
    elif tipo in ("producto", "catalogo", "catalogo_producto"):
        update_fields["lead_score"] = max(6, 5)
        if extraction.get("producto"):
            update_fields["notas"] = f"Interés en producto: {extraction.get('producto')}"

    try:
        from app.database.pocketbase_client import get_one_record, update_record

        existing = get_one_record(collection, lead_id)
        if existing:
            prev_meta = existing.get("metadata") or {}
            if isinstance(prev_meta, dict):
                merged = {**prev_meta, **metadata_patch}
                update_fields["metadata"] = merged
            update_record(collection, lead_id, update_fields, quiet=True)
    except Exception as exc:
        logger.debug("[Chat] Enriquecimiento lead omitido: %s", exc)
