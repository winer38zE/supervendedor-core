# Diagnóstico VPS — FastAPI / Evolution / Vapi

**Fecha:** 2026-08-17  
**VPS:** Hetzner `178.105.48.103` (Coolify + Traefik)  
**Repo local:** `supervendedor-core-ednetpro` (`winer38zE/supervendedor-core`)  
**Sesiones cubiertas:** 2026-08-15 (fix métricas/merge) + 2026-08-17 (SSH diagnóstico conectividad)

---

## Resumen ejecutivo

El dashboard Streamlit y la tool Vapi `buscar_productos_inventario` marcaban **OFFLINE** porque apuntaban a `http://178.105.48.103:8000`, puerto que en realidad sirve el **panel de Coolify**, no el backend de ventas IA.

Investigación SSH confirmó que **Supervendedor Core NO está desplegado en el VPS**. El único contenedor con `uvicorn app.main:app` es **Ruteros Venezuela** (ERP multi-tenant distinto). Por eso rutas como `/vapi/tools/webhook`, `/health` y `/api/v1/metrics/overview` devuelven **404** en producción.

**Acción requerida:** desplegar `supervendedor-core` como nueva app en Coolify, obtener su dominio `*.sslip.io`, y recién entonces actualizar Streamlit, `.env` y Vapi.

---

## 1. Ubicación del código fuente (`app.main:app`)

### En el VPS (lo que corre hoy)

| Campo | Valor |
|---|---|
| **Contenedor Docker** | `kmtwbdgpl4lc18ed3w31bcb8-030204677414` |
| **Label Coolify** | `ruteros-venezuelamain` |
| **Comando** | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| **Working dir contenedor** | `/app` |
| **Imagen** | Nixpacks (commit `06508ab`), **sin bind mounts** (`Mounts: []`) |
| **Proyecto real** | **Ruteros Venezuela ERP** — NO es Supervendedor Core |
| **Evidencia** | `GET /` responde: *"El backend híbrido Multi-Tenant está funcionando correctamente."* |

El código está **embebido en la imagen**; Coolify no deja una copia persistente en el host.  
`find /data/coolify -name "main.py" -path "*/app/main.py"` → **sin resultados**.

### Carpeta `/root/mi-sistema-ventas/`

Solo contiene `docker-compose.yml`, `n8n_data`, `openclaw_data`. **No** es el FastAPI de ventas IA.

### Repo Git de origen (Supervendedor Core — lo que DEBERÍA desplegarse)

| Campo | Valor |
|---|---|
| **Repositorio** | `https://github.com/winer38zE/supervendedor-core` |
| **Rama con fixes recientes** | `cursor/metrics-overview-whatsapp-vapi` (PR #6 draft) |
| **Entrypoint** | `app/main.py` → `app = FastAPI(...)` |
| **Comando Nixpacks** (`railway.json`) | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Ruta local** | `c:\Users\Edwuar\Desktop\supervendedor-core-ednetpro\app\main.py` |

---

## 2. Rutas / Endpoints

### 2.1 Hallazgo crítico sobre `/buscar_productos_inventario`

**NO existe como ruta HTTP directa** (`GET /buscar_productos_inventario` → 404).

Es una **función/tool interna** definida en:

| Archivo | Rol |
|---|---|
| `app/services/platform_tools_service.py` | Implementación async principal |
| `app/services/vapi_tools_service.py` | Dispatcher para Vapi (formatea respuesta de voz) |
| `servidor_ventas.py` | Exposición MCP stdio (legacy) |

#### Firma de la función

```python
async def buscar_productos_inventario(
    query: str,
    *,
    categoria: str = "",
    limit: int = 5,
) -> dict[str, Any]
```

**Parámetros:**

| Parámetro | Tipo | Requerido | Default | Descripción |
|---|---|---|---|---|
| `query` | `str` | Sí | — | Palabra clave o nombre de producto |
| `categoria` | `str` | No | `""` | Filtro opcional de categoría |
| `limit` | `int` | No | `5` | Máximo de productos (1–10 en Vapi) |

**Respuesta JSON típica:**

```json
{
  "ok": true,
  "fuente": "fastapi",
  "productos": [{ "titulo": "...", "precio_reventa_cop": 75000, "stock_estimado": "disponible" }],
  "total_encontrados": 1
}
```

#### Cómo invocarla vía HTTP (Supervendedor Core)

| Uso | Método | Ruta | Auth | Payload |
|---|---|---|---|---|
| **Vapi tool server (recomendado)** | `POST` | `/vapi/tools/webhook` | Header `x-vapi-secret` | JSON Vapi con `message.type = "tool-calls"` |
| **Atajo métricas** | `GET` | `/api/v1/metrics/inventario?q=enterizo&limit=5` | Header `X-API-Key` | Query params |
| **Catálogo directo** | `GET` | `/agents/catalog/zopa?q=enterizo` | Header `X-API-Key` | Query param `q` |
| **Health check** | `GET` | `/health` | — | — |

#### Payload Vapi para `buscar_productos_inventario`

```json
{
  "message": {
    "type": "tool-calls",
    "call": { "id": "call-tool-001", "metadata": { "client_id": "default" } },
    "toolCallList": [
      {
        "id": "toolu_test_001",
        "name": "buscar_productos_inventario",
        "parameters": { "query": "enterizo", "categoria": "", "limit": 5 }
      }
    ]
  }
}
```

**Respuesta esperada:**

```json
{
  "results": [
    {
      "toolCallId": "toolu_test_001",
      "result": "Encontré 1 producto(s) en inventario. Opción 1: Enterizo..."
    }
  ]
}
```

> **En el VPS actual (Ruteros):** `/vapi/tools/webhook`, `/health`, `/api/v1/metrics/overview` y `/buscar_productos_inventario` → **404**.

---

### 2.2 Rutas completas — `app/main.py` + routers registrados

Registro central: `app/core/router_registry.py`.

#### Core (`app/main.py`)

| Método | Ruta | Payload / params | Auth |
|---|---|---|---|
| `GET` | `/` | — | — |
| `GET` | `/health` | — | — |
| `GET` | `/sentry-debug` | — | Solo dev (404 en prod) |

#### Canales — Vapi (`app/routers/vapi_handler.py`, prefix `/vapi`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/vapi/webhook` | JSON Vapi (`assistant-request`, `tool-calls`, etc.) | `x-vapi-secret` |
| `POST` | `/vapi/tools/webhook` | JSON Vapi tool-calls | `x-vapi-secret` |

#### Canales — WhatsApp Evolution (`app/routers/whatsapp_handler.py`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/webhook/whatsapp` | Evento Evolution `messages.upsert` | Webhook secret Evolution |

#### Canales — WhatsApp Legacy Gupshup (`app/routers/gupshup_handler.py`, prefix `/whatsapp`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/whatsapp/webhook` | Payload Gupshup | — |

#### Agentes & catálogo (`app/routers/agents_router.py`, prefix `/agents`)

| Método | Ruta | Payload / params | Auth |
|---|---|---|---|
| `GET` | `/agents/catalog/snapshot` | — | `X-API-Key` |
| `POST` | `/agents/catalog/refresh` | — | `X-API-Key` |
| `GET` | `/agents/catalog/zopa` | `?q=` | `X-API-Key` |
| `POST` | `/agents/catalog/zopa` | `{ "q": "..." }` | `X-API-Key` |
| `POST` | `/agents/followup/run` | — | `X-API-Key` |
| `POST` | `/agents/shein/scrape` | `{ "save_excel": true }` | `X-API-Key` |
| `GET` | `/agents/health` | — | `X-API-Key` |

#### Hermes Bridge (`app/api_bridge.py`, prefix `/api/v1/agents`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `GET` | `/api/v1/agents` | — | `X-API-Key` |
| `POST` | `/api/v1/agents/{agent_name}` | `{ "message": "...", "context": {...} }` | `X-API-Key` |

Agentes: `negotiator`, `objection_killer`, `closing`, `catalog_bridge`, `prospecto`.

#### Métricas (`app/routers/metrics_router.py`, prefix `/api/v1/metrics`)

| Método | Ruta | Payload / params | Auth |
|---|---|---|---|
| `GET` | `/api/v1/metrics/architecture` | — | `X-API-Key` |
| `GET` | `/api/v1/metrics/overview` | `?ventas_limit=10&catalog_query=` | `X-API-Key` |
| `GET` | `/api/v1/metrics/ventas` | `?limit=&estado=&producto=` | `X-API-Key` |
| `GET` | `/api/v1/metrics/inventario` | `?q=enterizo&limit=5` | `X-API-Key` |

#### Chat / n8n (`app/routers/chat.py`, prefix `/api/v1`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/api/v1/chat` | `{ "phone": "...", "message": "...", "message_type": "text" }` | `X-API-Key` |

#### Marketing — Meta Ads (`app/routers/ads_router.py`, prefix `/ads`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/ads/run-cycle` | Config ads | `X-API-Key` |
| `GET` | `/ads/status` | — | `X-API-Key` |

#### Marketing — Content (`app/routers/content_router.py`, prefix `/api/v1/content`)

| Método | Ruta | Descripción | Auth |
|---|---|---|---|
| `GET` | `/api/v1/content/tenants/active` | Tenants activos n8n | `X-API-Key` |
| `GET` | `/api/v1/content/tenants/{tenant_id}/config` | Config tenant | `X-API-Key` |
| `POST` | `/api/v1/content/pipeline/run-batch` | Pipeline batch | `X-API-Key` |
| `POST` | `/api/v1/content/profiles` | Registrar perfil | `X-API-Key` |
| `POST` | `/api/v1/content/outliers/analyze` | Análisis outlier | `X-API-Key` |
| `POST` | `/api/v1/content/scripts/generate` | Generar guion | `X-API-Key` |
| `POST` | `/api/v1/content/pipeline/run` | Pipeline individual | `X-API-Key` |

#### Avatares (`app/routers/avatares.py`, prefix `/api/v1/avatares`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/api/v1/avatares/generar` | `{ "texto": "...", "webhook_url": "..." }` | `X-API-Key` |
| `GET` | `/api/v1/avatares/generar/{job_id}` | — | `X-API-Key` |

#### Ventas — Hunter (`app/routers/hunter_router.py`, prefix `/hunter`)

| Método | Ruta | Auth |
|---|---|---|
| `POST` | `/hunter/campana` | `X-API-Key` |
| `GET` | `/hunter/leads-calientes` | `X-API-Key` |
| `GET` | `/hunter/prospectos` | `X-API-Key` |
| `POST` | `/hunter/shaka/score` | `X-API-Key` |
| `PATCH` | `/hunter/prospectos/{prospecto_id}/procesado` | `X-API-Key` |

#### Ventas — Cierre (`app/routers/cierre_router.py`, prefix `/cierre/v1/cierre`)

| Método | Ruta | Payload | Auth |
|---|---|---|---|
| `POST` | `/cierre/v1/cierre/analizar` | `{ "remoteJid", "mensaje_cliente", "historial" }` | `X-API-Key` |

#### Ventas — Centinela (`app/routers/centinela_router.py`, prefix `/centinela`)

| Método | Ruta | Auth |
|---|---|---|
| `POST` | `/centinela/deudores/cargar` | `X-API-Key` |
| `POST` | `/centinela/deudores` | `X-API-Key` |
| `GET` | `/centinela/deudores` | `X-API-Key` |
| `POST` | `/centinela/quita/calcular` | `X-API-Key` |
| `GET` | `/centinela/quita/tabla` | `X-API-Key` |
| `POST` | `/centinela/bitacora` | `X-API-Key` |
| `GET` | `/centinela/bitacora/{cliente_id}` | `X-API-Key` |
| `PUT` | `/centinela/deudores/{cliente_id}/estado` | `X-API-Key` |
| `GET` | `/centinela/resumen` | `X-API-Key` |

#### SAAS Admin (`app/routers/saas_router.py`, prefix `/saas`)

| Método | Ruta | Auth |
|---|---|---|
| `POST` | `/saas/tenants/register` | `X-API-Key` |
| `GET` | `/saas/tenants/{tenant_id}/dashboard` | — |
| `GET` | `/saas/tenants/{tenant_id}/wallet` | `X-API-Key` |
| `GET` | `/saas/admin/tenants` | Admin |
| `POST` | `/saas/admin/tenants/{tenant_id}/credit` | Admin |
| `POST` | `/saas/admin/trials/expire` | Admin |
| `PATCH` | `/saas/admin/tenants/{tenant_id}/estado` | Admin |

---

## 3. Causa del proceso "zombie"

### Síntoma reportado

Proceso `uvicorn app.main:app --port 8000` llevaba ~5 días sin responder aunque aparecía en `ps aux`. Se mató con `kill -9` y Coolify lo revivió automáticamente.

### Hallazgos SSH (contenedor `kmtw…` — Ruteros)

| Métrica | Valor |
|---|---|
| `RestartCount` | 1 (reinicio reciente tras `kill -9`) |
| `OOMKilled` | `false` |
| Memoria | ~104 MiB / 3.7 GiB (~2.7%) |
| PIDs | 5 (normal para uvicorn) |
| Logs | Startup limpio; probes a `/health` → **404**; sin traceback ni OOM |

### Diagnóstico

1. **El `kill -9` manual** disparó el self-healing de Coolify → restart normal, no evidencia de crash espontáneo.
2. **Healthcheck mal configurado:** Coolify probablemente hace probe a `GET /health`, pero **Ruteros no tiene `/health`** → probes fallan → restarts periódicos posibles que parecen "zombie".
3. **No hay evidencia de memory leak** en logs actuales (104 MiB estables).
4. El problema de **Streamlit/Vapi OFFLINE** es de **URL incorrecta** (`IP:8000` = Coolify UI), no necesariamente del proceso colgado.

### Fixes aplicados / recomendados

| Fix | Estado | Detalle |
|---|---|---|
| Endpoint `GET /health` en Ruteros | **Recomendado** (proyecto distinto) | Agregar en el repo Ruteros |
| Healthcheck Coolify → `GET /health` cada 30s | **Recomendado** | Para Supervendedor Core al desplegarlo |
| Supervendedor Core ya tiene `/health` | **En repo local** | `app/main.py` líneas 62–66 |
| Timeouts en métricas (12s) | **Aplicado en repo** | `metrics_router.py` — evita cuelgues en overview |
| Manejo de excepciones en tools Vapi | **Aplicado en repo** | `vapi_tools_service.py` — try/except por tool |
| Resolución conflictos merge | **Aplicado en repo** | Impedían arrancar FastAPI localmente |

---

## 4. Mapa de puertos y dominios

| Servicio | Contenedor / notas | Puerto interno | Acceso público | Estado (2026-08-17) |
|---|---|---|---|---|
| **Coolify UI** | Panel de gestión | 8000 | `http://178.105.48.103:8000` | ✅ Corriendo (NO es FastAPI ventas) |
| **Ruteros ERP** | `kmtwbdgpl4lc18ed3w31bcb8-…` | 8000 | `https://kmtwbdgpl4lc18ed3w31bcb8.178.105.48.103.sslip.io` | ✅ Online (ERP distinto) |
| **Red Neuronal Obsidian** | `j5t5rh1gjh8gjweq5gerx2k2-…` | 8000 | `http://j5t5rh1gjh8gjweq5gerx2k2.178.105.48.103.sslip.io` | ⚠️ Degradado (probe `/health` timeout externo) |
| **Supervendedor Core** | — | 8000 (esperado) | **NO DESPLEGADO** | ❌ No existe |
| **PocketBase** | CRM | 8090 | `https://pocketbase.edwuarcardenas.online` + `178.105.48.103:8090` | ✅ Corriendo |
| **Evolution API** | WhatsApp | 8081 | `http://178.105.48.103:8081` (sin Traefik) | ✅ Corriendo (sin verificar instancia) |
| **Hermes Agent** | Orquestador A2A | 8085 | `http://178.105.48.103:8085` (sin Traefik) | ✅ Corriendo |
| **n8n** | Automatización | 5678 | `https://n8n-cip4lsfh8e0uifwpcxtlps5r.178.105.48.103.sslip.io` | ✅ Corriendo (HTTPS) |
| **Traefik** | Proxy Coolify | 80/443 | Enruta `*.sslip.io` | ✅ Corriendo |

### Verificaciones externas realizadas

```text
GET https://kmtwbdgpl4lc18ed3w31bcb8.178.105.48.103.sslip.io/
→ 200 {"estado":"Online","mensaje":"El backend híbrido Multi-Tenant..."}

GET https://kmtwbdgpl4lc18ed3w31bcb8.178.105.48.103.sslip.io/health
→ 404 (Ruteros no tiene /health)

POST https://kmtwbdgpl4lc18ed3w31bcb8.178.105.48.103.sslip.io/vapi/tools/webhook
→ 404 (Ruteros no tiene Vapi)

GET http://178.105.48.103:8000/
→ Coolify dashboard (NO FastAPI ventas)
```

---

## 5. Cambios aplicados

### 5.1 Cambios en el repo (sesión 2026-08-15)

Commit `af69a85` en rama `cursor/metrics-overview-whatsapp-vapi` (PR draft #6):

| Archivo | Cambio |
|---|---|
| `app/routers/metrics_router.py` | Endpoint `/overview` reforzado: JSON estable, probe Evolution, timeouts 12s |
| `app/services/vapi_tools_service.py` | Resolución conflictos merge; dispatcher unificado de tools |
| `app/routers/whatsapp_handler.py` | Resolución conflictos merge; webhook Evolution limpio |
| `app/routers/vapi_handler.py` | Resolución conflictos merge en docstring |
| `admin_panel/api_store.py` | Lee `INTERNAL_API_KEY` desde `st.secrets` además de `.env` |
| `tests/test_smoke.py` | Test `test_metrics_overview_returns_channels` |

#### Diff relevante — `admin_panel/api_store.py`

**Antes:**
```python
def _api_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = os.getenv("INTERNAL_API_KEY", "").strip()
```

**Después:**
```python
def _api_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = (
        st.secrets.get("INTERNAL_API_KEY", "")
        or os.getenv("INTERNAL_API_KEY", "")
    ).strip()
```

> **Nota:** El fallback `API_URL = "http://178.105.48.103:8000"` **NO se cambió** (sigue incorrecto hasta desplegar Supervendedor).

### 5.2 Cambios en el VPS (sesión 2026-08-17)

| Acción | Resultado |
|---|---|
| SSH diagnóstico read-only | ✅ Completado |
| Reinicio de servicios producción | ❌ **No realizado** (Evolution, n8n, Hermes intactos) |
| Actualización URLs en repo | ❌ **No realizado** (no hay dominio válido para Supervendedor) |
| Deploy Supervendedor Core | ❌ **Pendiente** (requiere aprobación) |

### 5.3 Archivos con URL incorrecta pendientes de actualizar

| Archivo | Valor actual | Valor correcto (post-deploy) |
|---|---|---|
| `admin_panel/api_store.py` L22 | `http://178.105.48.103:8000` | `https://<DOMINIO-SUPERVENDEDOR>` |
| `. env` L11–12 | `BASE_URL` / `PUBLIC_URL` → `:8000` | `https://<DOMINIO-SUPERVENDEDOR>` |
| `app/cloud_vault.py` L16 | fallback `:8000` | dominio sslip.io |
| `app/api_bridge.py` L92 | fallback `:8000` | dominio sslip.io |
| `hermes_tools.json` | todas las URLs `:8000` | dominio sslip.io |
| `orchestrator_prompt.md` L9 | `:8000/api/v1/agents/...` | dominio sslip.io |

---

## 6. URL final para Vapi — tool `buscar_productos_inventario`

### ⚠️ Estado actual: NO verificable en producción

Supervendedor Core **no está desplegado** en el VPS. No fue posible confirmar un `curl` exitoso contra producción para esta tool.

Pruebas **locales** (pytest) sí pasan:

```bash
pytest tests/test_smoke.py::test_vapi_tools_webhook_inventario -v
# POST /vapi/tools/webhook → 200, results con inventario formateado
```

### URL correcta (plantilla — pegar en Vapi Dashboard tras deploy)

```
https://<DOMINIO-SUPERVENDEDOR-COOLIFY>/vapi/tools/webhook
```

Ejemplo con el patrón Coolify:

```
https://<uuid>.178.105.48.103.sslip.io/vapi/tools/webhook
```

### Configuración completa en Vapi Dashboard

| Campo | Valor |
|---|---|
| **Server URL** (tool server) | `https://<DOMINIO>/vapi/tools/webhook` |
| **Header** | `x-vapi-secret: <VAPI_WEBHOOK_SECRET>` |
| **Assistant webhook** (opcional) | `https://<DOMINIO>/vapi/webhook` |
| **Tool name** | `buscar_productos_inventario` (Vapi lo envía en el body, no en la URL) |

### Curl de prueba (ejecutar DESPUÉS del deploy)

```bash
curl -X POST "https://<DOMINIO>/vapi/tools/webhook" \
  -H "Content-Type: application/json" \
  -H "x-vapi-secret: TU_VAPI_WEBHOOK_SECRET" \
  -d '{
    "message": {
      "type": "tool-calls",
      "call": { "id": "test-001", "metadata": { "client_id": "default" } },
      "toolCallList": [{
        "id": "toolu_test_001",
        "name": "buscar_productos_inventario",
        "parameters": { "query": "enterizo", "limit": 3 }
      }]
    }
  }'
```

**Respuesta esperada:** HTTP 200 con `"results"` conteniendo texto de inventario.

### Variables de entorno mínimas en Coolify (post-deploy)

```env
PUBLIC_URL=https://<DOMINIO>
POCKETBASE_URL=https://pocketbase.edwuarcardenas.online
INTERNAL_API_KEY=<clave>
VAPI_WEBHOOK_SECRET=<secreto>
EVOLUTION_API_URL=http://178.105.48.103:8081
EVOLUTION_API_KEY=<key>
EVOLUTION_INSTANCE=super_vendedor
ENV=production
```

Healthcheck Coolify: `GET /health` → debe responder `{"status":"healthy",...}`.

---

## 7. Pendientes (requieren tu confirmación)

### Críticos

- [ ] **Desplegar `supervendedor-core` en Coolify** como nueva Application
  - Repo: `winer38zE/supervendedor-core`
  - Rama sugerida: `cursor/metrics-overview-whatsapp-vapi` (incluye fix métricas + merge)
  - Healthcheck: `GET /health`
- [ ] **Obtener dominio sslip.io** asignado por Coolify al nuevo servicio
- [ ] **Actualizar URLs** en `api_store.py`, `.env`, `hermes_tools.json`, `PUBLIC_URL` en Coolify
- [ ] **Configurar Vapi Dashboard** con la URL `/vapi/tools/webhook` y header `x-vapi-secret`
- [ ] **Ejecutar curl de prueba** contra el dominio real y validar inventario

### Recomendados (no bloqueantes)

- [ ] Renombrar servicios confusos en Coolify:
  - `red-neuronal-ventasmain` → `red-neuronal-obsidian`
  - Clarificar que `ruteros-venezuelamain` es ERP Ruteros, no ventas IA
- [ ] Agregar `GET /health` al proyecto Ruteros (fix healthcheck independiente)
- [ ] Mergear PR #6 (`cursor/metrics-overview-whatsapp-vapi`) a `main` antes del deploy
- [ ] Configurar `API_URL` en Streamlit Cloud secrets apuntando al nuevo dominio
- [ ] Verificar instancia Evolution (`super_vendedor`) conectada vía probe en `/api/v1/metrics/overview`

### Lo que NO se tocó (por diseño)

- Evolution API (`:8081`)
- n8n
- Hermes Agent (`:8085`)
- PocketBase
- Contenedor Ruteros (solo lectura)

---

## Apéndice — Timeline de sesiones

| Fecha | Acción |
|---|---|
| 2026-08-15 | Fix conflictos merge; refuerzo `/api/v1/metrics/overview`; commit `af69a85`; PR #6 draft |
| 2026-08-17 | SSH diagnóstico VPS; identificación Ruteros vs Supervendedor; mapa Traefik; sin cambios destructivos |
| 2026-08-17 | Generación de este documento `DIAGNOSTICO_VPS_2026-08-17.md` |

---

*Documento generado a partir de investigación SSH read-only + análisis del repo `supervendedor-core-ednetpro`.*
