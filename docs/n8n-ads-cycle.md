# n8n — Ciclo autónomo Meta Ads (Capa 5)

Ejecuta `POST /ads/run-cycle` cada **4–6 horas** para:

1. Detectar productos en tendencia (Google Trends + Ad Library)
2. Crear campaña **PAUSED** si hay oportunidad alta + match en catálogo
3. Pausar / escalar campañas activas según reglas de rentabilidad
4. Enviar resumen por WhatsApp a `ADS_NOTIFY_WHATSAPP`

## Requisitos

| Variable | Uso |
|----------|-----|
| `INTERNAL_API_KEY` | Header `X-API-Key` en n8n |
| `META_ACCESS_TOKEN` | Meta Marketing API |
| `META_AD_ACCOUNT_ID` | Cuenta publicitaria |
| `META_PAGE_ID` | Creativos (obligatorio para lanzar) |
| `ADS_NOTIFY_WHATSAPP` | Número destino resumen (573XXXXXXXX) |
| `ADS_AUTO_LAUNCH_ENABLED` | `true` para lanzar desde trends |

URL base del backend (ejemplo Coolify/VPS):

```
https://tu-dominio.com
```

Local:

```
http://localhost:8000
```

## Workflow n8n (manual)

Importa `scripts/n8n_ads_cycle_workflow.json` o crea:

### Nodo 1 — Schedule Trigger

- **Mode:** Every X hours
- **Hours:** 4 (o 6)

### Nodo 2 — HTTP Request

| Campo | Valor |
|-------|--------|
| Method | POST |
| URL | `{{ $env.SUPERVENDEDOR_URL }}/ads/run-cycle` |
| Authentication | Header Auth |
| Header Name | `X-API-Key` |
| Header Value | `{{ $env.INTERNAL_API_KEY }}` |
| Body Content Type | JSON |
| Body | `{}` o ver opciones abajo |

**Body opcional** (sobreescribe `.env` solo en esa ejecución):

```json
{
  "launch_new_campaign": true,
  "min_priority_score": 70,
  "incluir_trends": true,
  "evaluar_reglas": true,
  "notificar_whatsapp": true
}
```

### Nodo 3 — (Opcional) IF error

Condición: `{{ $json.ok }}` equals `false` → notificar Slack/email.

El backend ya envía WhatsApp si `notificar_whatsapp` es true y `ADS_NOTIFY_WHATSAPP` está configurado.

## Probar manualmente

PowerShell:

```powershell
$headers = @{ "X-API-Key" = $env:INTERNAL_API_KEY }
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/ads/run-cycle" `
  -Headers $headers -ContentType "application/json" -Body '{"evaluar_reglas": false}'
```

curl:

```bash
curl -X POST "http://localhost:8000/ads/run-cycle" \
  -H "X-API-Key: TU_CLAVE" \
  -H "Content-Type: application/json" \
  -d '{"launch_new_campaign": false}'
```

Estado sin ejecutar ciclo:

```bash
curl -H "X-API-Key: TU_CLAVE" http://localhost:8000/ads/status
```

## Formato WhatsApp (ejemplo)

```
🤖 *Ciclo Meta Ads — 2026-07-29 15:30:00*

📈 *Tendencia top:* enterizo deportivo (score 78, alta)

🆕 *Nueva campaña PAUSED:* EDNET — Trend enterizo deportivo
ID: `120210012345678`

🟢 *Escaladas:*
• EDNET — Conjunto verano (+20%) — $36,000 COP

✅ Sin cambios en campañas activas.
```

## Variables Capa 5 (.env)

```env
ADS_AUTO_LAUNCH_ENABLED=true
ADS_MIN_PRIORITY_SCORE=70
ADS_MIN_PRIORIDAD=alta
ADS_HORAS_COOLDOWN_LANZAMIENTO=72
ADS_CYCLE_NOTIFY=true
ADS_TRENDS_LIMITE=10
```

Cooldown de keywords evita duplicar campañas sobre el mismo producto en cada cron.
