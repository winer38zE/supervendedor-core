# PocketBase — Colecciones para Super Vendedor (VPS)

Backend por defecto: **PocketBase** (`DB_BACKEND=pocketbase`).

Crea estas colecciones en el admin de PocketBase (`http://TU_VPS:8090/_/`):

## Variables `.env`

```env
DB_BACKEND=pocketbase
POCKETBASE_URL=http://178.105.48.103:8090
POCKETBASE_EMAIL=tu_correo@ejemplo.com
POCKETBASE_PASSWORD=tu_contraseña
```

---

## 1. `leads_crm` (Hunter + WhatsApp + Followup)

| Campo | Tipo | Notas |
|-------|------|-------|
| tenant_id | Text | Required |
| telefono | Text | Required |
| nombre | Text | |
| empresa | Text | |
| estado | Text | prospecto, negociando, agenda_pendiente, cerrado, nuevo |
| lead_score | Number | 1-10 |
| fuente | Text | hunter, whatsapp, vapi |
| notas | Text | |
| metadata | JSON | probability_score, shaka, etc. |
| updated_at | Date | |

**Índice único recomendado:** `tenant_id` + `telefono`

---

## 2. `prospectos_hunter` (Campañas Google Maps)

| Campo | Tipo | Notas |
|-------|------|-------|
| tenant_id | Text | Required |
| lugar_id | Text | place_id Google |
| nombre_negocio | Text | |
| direccion | Text | |
| telefono | Text | |
| sitio_web | Text | |
| rating | Number | |
| total_reviews | Number | |
| categoria | Text | |
| latitud | Number | |
| longitud | Number | |
| ciudad | Text | |
| procesado | Bool | default false |
| metadata | JSON | Shaka: probability_score, channel, opening_line |

**Índice único recomendado:** `tenant_id` + `lugar_id`

---

## 3. `clients_config` (Prompts + Business Evolver)

| Campo | Tipo | Notas |
|-------|------|-------|
| client_id | Text | Required, unique |
| negocio_nombre | Text | |
| modo_operacion | Text | venta, b2b, etc. |
| custom_prompt | Text | |
| dynamic_knowledge | JSON | Business Evolver |
| updated_at | Date | |

---

## 4. `historial_llamadas` (Vapi — opcional)

| Campo | Tipo |
|-------|------|
| tenant_id | Text |
| telefono | Text |
| resultado | Text |
| transcripcion | Text |
| resumen_ia | Text |
| duracion_seg | Number |
| puntuacion | Number |
| vapi_call_id | Text |
| metadata | JSON |

---

## 5. `processed_events` (idempotencia webhooks)

| Campo | Tipo |
|-------|------|
| source | Text | whatsapp \| vapi |
| event_id | Text | ID único del evento |

---

## 6. `compliance_log` (Meta Ads — Capa 3)

| Campo | Tipo | Notas |
|-------|------|-------|
| producto_id | Text | |
| producto_nombre | Text | |
| aprobado | Bool | |
| severidad | Text | ok \| advertencia \| bloqueo |
| motivo | Text | |
| copy_snapshot | JSON | titulo, texto, CTA |
| targeting_snapshot | JSON | |
| modelo | Text | gpt-4.1, etc. |
| created_at | Date | |

---

## 7. `ads_actions_log` (Meta Ads — Capa 4)

| Campo | Tipo | Notas |
|-------|------|-------|
| campaign_id | Text | Required |
| campaign_name | Text | |
| accion | Text | pausar \| escalar \| sin_accion \| skip \| error |
| motivo | Text | |
| metricas | JSON | spend, cpa, roas, etc. |
| presupuesto_anterior | Number | COP |
| presupuesto_nuevo | Number | COP |
| created_at | Date | |

Fallback local: `app/marketing/logs/ads_actions_log.jsonl`

---

## 8. `chat_conversations` (Orquestación n8n / Chat API)

| Campo | Tipo | Notas |
|-------|------|-------|
| tenant_id | Text | Required |
| telefono | Text | Required |
| lead_id | Text | FK lógico a leads_crm |
| status | Text | active \| closed |
| bot_active | Bool | default true — false = handoff humano |
| updated_at | Date | |

**Índice recomendado:** `tenant_id` + `telefono` + `status`

---

## 9. `chat_messages` (Historial chat n8n)

| Campo | Tipo | Notas |
|-------|------|-------|
| conversation_id | Text | Required |
| lead_id | Text | |
| telefono | Text | |
| role | Text | user \| assistant |
| content | Text | |
| message_type | Text | text \| audio \| image |
| media_url | Text | |
| created_at | Date | |

---

## Variables adicionales `.env`

```env
ENV=development
INTERNAL_API_KEY=tu_clave_secreta_interna
MIN_HOURS_BETWEEN_FOLLOWUPS=24
VAPI_WEBHOOK_SECRET=
```

## Probar conexión

```bash
curl http://localhost:8000/health
```

Respuesta esperada:

```json
{
  "status": "healthy",
  "database": {
    "backend": "pocketbase",
    "url": "http://178.105.48.103:8090",
    "authenticated": true,
    "email_configured": true
  }
}
```

## Volver a Supabase (legacy)

```env
DB_BACKEND=supabase
SUPABASE_URL=...
SUPABASE_KEY=...
```
