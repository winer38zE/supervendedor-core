"""
app/routers/saas_router.py
────────────────────────────────────────────────────────────────────────────────
API SaaS Multi-tenant — Registro, Dashboard, Wallet y Administración.

Endpoints públicos (tenant):
  POST /saas/tenants/register           → registrar nuevo tenant + arrancar trial
  GET  /saas/tenants/{id}/dashboard     → HTML dashboard ROI
  GET  /saas/tenants/{id}/wallet        → saldo + últimas transacciones (JSON)

Endpoints de administración (requieren x-master-key: ednetpro_2026):
  GET  /saas/admin/tenants              → lista todos los tenants
  POST /saas/admin/tenants/{id}/credit  → agrega crédito manualmente
  POST /saas/admin/trials/expire        → procesa expiración manual de trials
  PATCH /saas/admin/tenants/{id}/estado → cambia estado del tenant
"""

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from ..database import get_client
from ..services.billing import (
    COSTO_LLAMADA_USD,
    add_credit,
    get_wallet_status,
)
from ..services.trial_manager import check_and_expire_trials, register_tenant
from ..middleware.auth_master import require_master_key

router = APIRouter(prefix="/saas", tags=["SaaS Platform"])

# Tasa de conversión USD → COP para mostrar ROI en pesos
USD_TO_COP: float = float(os.environ.get("USD_TO_COP", "4200"))
AVG_DEAL_COP: float = float(os.environ.get("AVG_DEAL_COP", "150000"))


# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class RegisterTenantBody(BaseModel):
    tenant_id:  str
    nombre:     str
    email:      str
    telefono:   str = ""


class AddCreditBody(BaseModel):
    monto_usd:      float
    referencia_pago: str = ""
    descripcion:    str  = "recarga manual"


class UpdateEstadoBody(BaseModel):
    estado: str  # trial | activo | suspendido | cancelado


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRO
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/tenants/register", summary="Registrar nuevo tenant + trial 3 días")
async def register(body: RegisterTenantBody):
    """
    Registra un nuevo cliente en la plataforma SaaS.
    Inicia automáticamente el trial de 3 días y envía WhatsApp de bienvenida.
    """
    result = register_tenant(
        tenant_id=body.tenant_id,
        nombre=body.nombre,
        email=body.email,
        telefono=body.telefono,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Error al registrar"))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD (HTML)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tenants/{tenant_id}/dashboard", response_class=HTMLResponse,
            summary="Dashboard ROI del tenant")
async def dashboard(tenant_id: str):
    """
    Dashboard minimalista con métricas de ROI, saldo y actividad de llamadas.
    Devuelve HTML renderizable directamente en el navegador.
    """
    db = get_client()
    tenant, wallet, llamadas = None, None, []

    if db:
        try:
            t = db.table("tenants").select("*").eq("id", tenant_id).single().execute()
            tenant = t.data
        except Exception:
            pass

        try:
            w = db.table("wallets").select("*").eq("tenant_id", tenant_id).single().execute()
            wallet = w.data
        except Exception:
            pass

        try:
            l = (
                db.table("historial_llamadas")
                .select("resultado, duracion_seg, puntuacion, created_at")
                .eq("tenant_id", tenant_id)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            llamadas = l.data or []
        except Exception:
            pass

    # Métricas
    total_llamadas   = len(llamadas)
    ventas_cerradas  = sum(1 for c in llamadas if c.get("resultado") == "cerrado")
    tasa_conversion  = round(ventas_cerradas / total_llamadas * 100, 1) if total_llamadas else 0
    balance_usd      = float(wallet.get("balance_usd", 0)) if wallet else 0.0
    total_gastado    = float(wallet.get("total_gastado", 0)) if wallet else 0.0
    total_recargado  = float(wallet.get("total_recargado", 0)) if wallet else 0.0

    # ROI
    inversion_cop    = round(total_gastado * USD_TO_COP)
    ganancia_est_cop = ventas_cerradas * AVG_DEAL_COP
    roi_pct          = round((ganancia_est_cop - inversion_cop) / inversion_cop * 100, 1) if inversion_cop > 0 else 0
    roi_color        = "#00ff88" if roi_pct >= 0 else "#ff4444"
    roi_signo        = "+" if roi_pct >= 0 else ""

    # Estado del tenant
    estado       = tenant.get("estado", "desconocido") if tenant else "desconocido"
    nombre       = tenant.get("nombre", tenant_id) if tenant else tenant_id
    trial_expira = tenant.get("trial_expira_at", "") if tenant else ""

    horas_restantes = 0
    if trial_expira and estado == "trial":
        try:
            exp = datetime.fromisoformat(trial_expira.replace("Z", "+00:00"))
            diff = exp - datetime.now(timezone.utc)
            horas_restantes = max(0, int(diff.total_seconds() / 3600))
        except Exception:
            pass

    estado_badge_color = {
        "trial":      "#f59e0b",
        "activo":     "#00ff88",
        "suspendido": "#ff4444",
        "cancelado":  "#888",
    }.get(estado, "#888")

    estado_label = {
        "trial":      f"TRIAL — {horas_restantes}h restantes",
        "activo":     "ACTIVO",
        "suspendido": "SUSPENDIDO",
        "cancelado":  "CANCELADO",
    }.get(estado, estado.upper())

    recharge_link = os.environ.get("RECHARGE_LINK", "https://pay.ednetpro.co/recargar")

    # Llamadas recientes (últimas 5)
    recientes_html = ""
    for c in llamadas[:5]:
        r = c.get("resultado", "")
        color = {"cerrado": "#00ff88", "perdido": "#ff6b35", "no_contesto": "#888"}.get(r, "#aaa")
        fecha = c.get("created_at", "")[:10]
        dur   = c.get("duracion_seg", 0)
        recientes_html += f"""
        <tr>
          <td style="padding:8px 12px;color:{color};font-weight:600;">{r.upper()}</td>
          <td style="padding:8px 12px;color:#aaa;">{dur}s</td>
          <td style="padding:8px 12px;color:#666;">{fecha}</td>
        </tr>"""

    alert_html = ""
    if estado == "suspendido":
        alert_html = f"""
        <div style="background:#ff44441a;border:1px solid #ff4444;border-radius:12px;
                    padding:20px;margin-bottom:24px;text-align:center;">
          <p style="color:#ff4444;font-size:16px;margin:0 0 12px;">
            Tu cuenta está suspendida. Recarga para continuar vendiendo.
          </p>
          <a href="{recharge_link}" target="_blank"
             style="background:#ff4444;color:#fff;padding:12px 28px;border-radius:8px;
                    text-decoration:none;font-weight:700;font-size:15px;">
            RECARGAR AHORA
          </a>
        </div>"""
    elif estado == "trial" and horas_restantes < 24:
        alert_html = f"""
        <div style="background:#f59e0b1a;border:1px solid #f59e0b;border-radius:12px;
                    padding:20px;margin-bottom:24px;text-align:center;">
          <p style="color:#f59e0b;font-size:16px;margin:0 0 12px;">
            Tu trial vence en {horas_restantes} horas. Asegura tu acceso ahora.
          </p>
          <a href="{recharge_link}" target="_blank"
             style="background:#f59e0b;color:#000;padding:12px 28px;border-radius:8px;
                    text-decoration:none;font-weight:700;font-size:15px;">
            ACTIVAR CUENTA — $0.10 / cierre
          </a>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard — {nombre}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #080808;
      color: #e0e0e0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      min-height: 100vh;
      padding: 24px 16px;
    }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    /* Header */
    .header {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 28px; flex-wrap: wrap; gap: 12px;
    }}
    .logo {{ color: #00ff88; font-size: 20px; font-weight: 800; letter-spacing: 1px; }}
    .logo span {{ color: #fff; }}
    .badge {{
      background: {estado_badge_color}22;
      border: 1px solid {estado_badge_color};
      color: {estado_badge_color};
      padding: 4px 14px; border-radius: 20px; font-size: 12px; font-weight: 700;
    }}
    .tenant-name {{ color: #888; font-size: 14px; margin-top: 4px; }}
    /* Cards grid */
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{
      background: #141414; border: 1px solid #222; border-radius: 14px;
      padding: 20px 22px;
    }}
    .card-label {{ color: #555; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
    .card-value {{ font-size: 28px; font-weight: 800; color: #fff; }}
    .card-sub {{ color: #555; font-size: 12px; margin-top: 4px; }}
    .card-green .card-value {{ color: #00ff88; }}
    .card-yellow .card-value {{ color: #f59e0b; }}
    /* ROI block */
    .roi-block {{
      background: #141414; border: 1px solid #222; border-radius: 14px;
      padding: 24px; margin-bottom: 24px;
    }}
    .roi-title {{ color: #555; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }}
    .roi-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }}
    .roi-label {{ color: #888; font-size: 14px; }}
    .roi-val {{ font-size: 18px; font-weight: 700; color: #fff; }}
    .roi-divider {{ border: none; border-top: 1px solid #222; margin: 12px 0; }}
    .roi-big {{ font-size: 36px; font-weight: 900; color: {roi_color}; }}
    /* Table */
    .table-block {{
      background: #141414; border: 1px solid #222; border-radius: 14px;
      padding: 20px; margin-bottom: 24px; overflow-x: auto;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ color: #555; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
          padding: 8px 12px; text-align: left; }}
    /* Footer */
    .footer {{ color: #333; font-size: 12px; text-align: center; margin-top: 32px; }}
    .btn {{
      display: inline-block; background: #00ff88; color: #000;
      padding: 10px 24px; border-radius: 8px; font-weight: 700;
      text-decoration: none; font-size: 14px; margin-top: 12px;
    }}
  </style>
</head>
<body>
  <div class="container">

    <!-- Header -->
    <div class="header">
      <div>
        <div class="logo">ED NET<span> PRO</span></div>
        <div class="tenant-name">{nombre}</div>
      </div>
      <div class="badge">{estado_label}</div>
    </div>

    <!-- Alerta de estado -->
    {alert_html}

    <!-- Métricas principales -->
    <div class="grid">
      <div class="card card-green">
        <div class="card-label">Saldo disponible</div>
        <div class="card-value">${balance_usd:.2f}</div>
        <div class="card-sub">USD · {COSTO_LLAMADA_USD} por cierre</div>
      </div>
      <div class="card">
        <div class="card-label">Llamadas totales</div>
        <div class="card-value">{total_llamadas}</div>
        <div class="card-sub">en toda la cuenta</div>
      </div>
      <div class="card card-green">
        <div class="card-label">Ventas cerradas</div>
        <div class="card-value">{ventas_cerradas}</div>
        <div class="card-sub">leads convertidos</div>
      </div>
      <div class="card card-yellow">
        <div class="card-label">Tasa de conversión</div>
        <div class="card-value">{tasa_conversion}%</div>
        <div class="card-sub">industria promedio 15%</div>
      </div>
    </div>

    <!-- ROI Block -->
    <div class="roi-block">
      <div class="roi-title">Retorno de Inversión (ROI)</div>
      <div class="roi-row">
        <span class="roi-label">Inversion total</span>
        <span class="roi-val">${total_gastado:.2f} USD</span>
      </div>
      <div class="roi-row">
        <span class="roi-label">Equivalente en pesos</span>
        <span class="roi-val">${inversion_cop:,} COP</span>
      </div>
      <div class="roi-row">
        <span class="roi-label">Ganancia estimada ({ventas_cerradas} cierres × ${int(AVG_DEAL_COP):,})</span>
        <span class="roi-val">${ganancia_est_cop:,} COP</span>
      </div>
      <hr class="roi-divider">
      <div class="roi-row">
        <span class="roi-label" style="font-size:16px;font-weight:700;color:#fff;">ROI</span>
        <span class="roi-big">{roi_signo}{roi_pct}%</span>
      </div>
      <p style="color:#444;font-size:11px;margin-top:8px;">
        Ganancia estimada basada en ${int(AVG_DEAL_COP):,} COP promedio por venta.
        Ajusta en tu configuración.
      </p>
    </div>

    <!-- Llamadas recientes -->
    {"" if not recientes_html else f'''
    <div class="table-block">
      <div class="roi-title">Últimas llamadas</div>
      <table>
        <thead><tr>
          <th>Resultado</th><th>Duración</th><th>Fecha</th>
        </tr></thead>
        <tbody>{recientes_html}</tbody>
      </table>
    </div>'''}

    <!-- CTA si tiene saldo bajo -->
    <div style="text-align:center;padding:24px 0;">
      <p style="color:#555;font-size:14px;">¿Listo para escalar? Recarga y activa más llamadas.</p>
      <a href="{recharge_link}" target="_blank" class="btn">Recargar saldo</a>
    </div>

    <div class="footer">
      ED NET PRO · Plataforma SaaS de Ventas con IA · {datetime.now().strftime("%Y")}
    </div>
  </div>
</body>
</html>"""

    return HTMLResponse(content=html)


# ══════════════════════════════════════════════════════════════════════════════
# WALLET (JSON)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tenants/{tenant_id}/wallet", summary="Estado del wallet y transacciones")
async def wallet_status(tenant_id: str):
    return get_wallet_status(tenant_id)


# ══════════════════════════════════════════════════════════════════════════════
# ADMINISTRACIÓN (requieren x-master-key)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/tenants", summary="[Admin] Listar todos los tenants")
async def admin_list_tenants(auth=Depends(require_master_key)):
    db = get_client()
    if not db:
        raise HTTPException(status_code=503, detail="DB no disponible")
    try:
        res = db.table("resumen_saas").select("*").execute()
        return {"tenants": res.data or [], "total": len(res.data or [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/tenants/{tenant_id}/credit",
             summary="[Admin] Agregar crédito al wallet")
async def admin_add_credit(
    tenant_id: str,
    body: AddCreditBody,
    auth=Depends(require_master_key),
):
    result = add_credit(
        tenant_id=tenant_id,
        monto_usd=body.monto_usd,
        referencia_id=body.referencia_pago,
        descripcion=body.descripcion,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("razon", "Error"))
    return result


@router.post("/admin/trials/expire", summary="[Admin] Procesar expiración de trials")
async def admin_expire_trials(auth=Depends(require_master_key)):
    procesados = check_and_expire_trials()
    return {"procesados": procesados, "total": len(procesados)}


@router.patch("/admin/tenants/{tenant_id}/estado",
              summary="[Admin] Cambiar estado del tenant")
async def admin_update_estado(
    tenant_id: str,
    body: UpdateEstadoBody,
    auth=Depends(require_master_key),
):
    estados_validos = {"trial", "activo", "suspendido", "cancelado"}
    if body.estado not in estados_validos:
        raise HTTPException(status_code=422, detail=f"Estado inválido. Opciones: {estados_validos}")

    db = get_client()
    if not db:
        raise HTTPException(status_code=503, detail="DB no disponible")
    try:
        db.table("tenants").update({"estado": body.estado}).eq("id", tenant_id).execute()
        return {"ok": True, "tenant_id": tenant_id, "nuevo_estado": body.estado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
