-- ============================================================
-- SEGUIMIENTO LEADS — Registro de mensajes WhatsApp enviados
-- Ejecutar en: Supabase → SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS public.seguimiento_leads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL,
    lead_id         UUID,                           -- FK a leads_crm.id (nullable: lead puede no existir aún)

    -- Datos del lead al momento del envío (snapshot — no FK estricta)
    nombre_lead     TEXT        NOT NULL DEFAULT '',
    telefono        TEXT        NOT NULL DEFAULT '',

    -- Detalles del mensaje
    canal           TEXT        NOT NULL DEFAULT 'whatsapp'
                                CHECK (canal IN ('whatsapp', 'email', 'sms', 'llamada')),
    tipo_mensaje    TEXT        NOT NULL DEFAULT 'cierre'
                                CHECK (tipo_mensaje IN ('link_pago', 'reserva', 'demo', 'follow_up', 'cierre')),
    mensaje_enviado TEXT        NOT NULL DEFAULT '',

    -- Resultado del envío
    estado_envio    TEXT        NOT NULL DEFAULT 'pendiente'
                                CHECK (estado_envio IN ('enviado', 'fallido', 'pendiente', 'mock')),
    proveedor       TEXT        NOT NULL DEFAULT 'desconocido'
                                CHECK (proveedor IN ('evolution', 'meta', 'mock', 'desconocido')),
    respuesta_api   JSONB       NOT NULL DEFAULT '{}',

    -- Contexto del lead en el momento del envío
    lead_score      SMALLINT    CHECK (lead_score BETWEEN 1 AND 10),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Índices ────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_seguimiento_tenant
    ON public.seguimiento_leads (tenant_id);

CREATE INDEX IF NOT EXISTS idx_seguimiento_lead_id
    ON public.seguimiento_leads (lead_id)
    WHERE lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_seguimiento_telefono
    ON public.seguimiento_leads (tenant_id, telefono);

CREATE INDEX IF NOT EXISTS idx_seguimiento_estado
    ON public.seguimiento_leads (tenant_id, estado_envio);

CREATE INDEX IF NOT EXISTS idx_seguimiento_created_at
    ON public.seguimiento_leads (created_at DESC);

-- ── Vista: resumen de envíos recientes ───────────────────────────────────────
CREATE OR REPLACE VIEW public.seguimiento_resumen AS
    SELECT
        s.tenant_id,
        s.nombre_lead,
        s.telefono,
        s.tipo_mensaje,
        s.estado_envio,
        s.proveedor,
        s.lead_score,
        s.created_at,
        l.empresa,
        l.estado   AS estado_lead,
        l.fuente
    FROM public.seguimiento_leads s
    LEFT JOIN public.leads_crm l
        ON l.id = s.lead_id
    ORDER BY s.created_at DESC;

-- ── RLS: cada tenant solo ve sus registros ────────────────────────────────────
ALTER TABLE public.seguimiento_leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "tenant_isolation_seguimiento"
    ON public.seguimiento_leads
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY IF NOT EXISTS "service_role_full_access_seguimiento"
    ON public.seguimiento_leads
    FOR ALL
    TO service_role
    USING (TRUE);
