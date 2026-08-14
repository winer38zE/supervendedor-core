# CLAUDE.md — Supervendedor Core ED NET PRO

> Briefing para Claude Code / Hermes. VPS Hetzner `178.105.48.103` · Coolify.

## Arquitectura

```
WhatsApp (Evolution API) → Hermes Agent (:8085)
                              ↓ HTTP tools
                         FastAPI (:8000)  app/api_bridge.py
                              ↓
                    app/agents/*  +  PocketBase (:8090)
                              ↓
                         n8n / Mem0 / Vapi
```

## Stack

| Capa | Tecnología |
|------|------------|
| API | FastAPI + uvicorn (:8000) |
| CRM | PocketBase `http://178.105.48.103:8090` |
| WhatsApp | Evolution API |
| Orquestador | Hermes Agent (:8085) |
| Automatización | n8n |
| LLM chat | `app/services/llm_router.py` (OpenAI + Claude) |
| Visión/PDF | `app/services/gemini_service.py` (gemini-2.0-flash) |
| Memoria | `app/services/memory_service.py` (mem0ai) |

## Agentes (`app/agents/`)

| Agente | Archivo | Rol |
|--------|---------|-----|
| Hermes | `hermes_negotiator.py` | Negociación ZOPA (target/reserve) |
| Objection Killer | `objection_killer_agent.py` | Objeciones precio/envío/competencia |
| Closing | `closing_followup_agent.py` | Cierre + reactivación CRM |
| Catalog Bridge | `catalog_bridge_agent.py` | Catálogo Shein + ZOPA dinámica |
| Shaka | `shaka_quantum_prospector.py` | Scoring Hunter B2B |
| Athena | `athena_analyst.py` | Sentimiento + momentum ventas |
| Hephaestus | `hephaestus_creator.py` | Fichas visuales / propuestas |
| Business Evolver | `business_evolver.py` | Aprendizaje post-llamada Vapi |

## Puente Hermes

- **Router:** `app/api_bridge.py`
- **Endpoint:** `POST /api/v1/agents/{agent_name}`
- **Agentes:** `negotiator` | `objection_killer` | `closing` | `catalog_bridge` | `prospecto`
- **Config tools:** `hermes_tools.json` (raíz)
- **Prompt orquestador:** `orchestrator_prompt.md`
- **Auth:** header `X-API-Key` = `INTERNAL_API_KEY`

## PocketBase — colecciones chat

| Colección | Uso |
|-----------|-----|
| `leads` | Lead por teléfono + tenant |
| `conversations` | Conversación activa + handoff |
| `messages` | Historial user/assistant |
| `media_extractions` | JSON Gemini (comprobantes/imágenes) |

Fallbacks: `leads_crm`, `chat_conversations`, `chat_messages`.

## Endpoints clave

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/v1/agents/{name}` | Puente Hermes → agentes |
| POST | `/api/v1/chat` | Orquestador n8n multimodal |
| GET | `/health` | Estado DB |
| POST | `/agents/followup/run` | Ciclo reactivación CRM |

## Comandos

```bash
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
pip install -r requirements.txt
```

## Convenciones

- Routers en `app/routers/`; servicios en `app/services/`; agentes en `app/agents/`
- Secrets solo en `.env` (ver `.env.example`)
- Cambios mínimos; no refactorizar fuera del alcance
- Responder en español
- No commitear `.env` ni `credentials.json`

## Reglas de ahorro (Claude Code)

1. No leer `.claudeignore` salvo petición explícita
2. Grep antes de leer archivos enteros
3. Docs extensas solo bajo demanda: `DOCUMENTACION_ARQUITECTURA_SUPERVENDEDOR.md`, `POCKETBASE_SETUP.md`
