"""
app/routers/__init__.py — Routers ED NET PRO 3.0

Organización por dominio (montaje en app.core.router_registry):

Canales:
  whatsapp_handler   → POST /webhook/whatsapp
  gupshup_handler    → POST /whatsapp/webhook (embudo completo)
  vapi_handler       → POST /vapi/webhook, /vapi/tools/webhook

Agentes & ventas:
  agents_router      → /agents/*
  hunter_router      → /hunter/*
  cierre_router      → /cierre/*
  centinela_router   → /centinela/*

Plataforma API v1:
  metrics_router     → /api/v1/metrics/*
  chat               → /api/v1/chat
  api_bridge         → /api/v1/agents/*
  content_router     → /api/v1/content/*
  avatares           → /api/v1/avatares/*

Marketing:
  ads_router         → /ads/*
"""
