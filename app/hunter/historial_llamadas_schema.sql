-- ============================================================
-- HISTORIAL DE LLAMADAS — Registro inmutable de cada llamada Vapi
-- Multi-tenant | Ejecutar en: Supabase → SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS public.historial_llamadas (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Multi-tenant: aislamiento por tenant_id
    tenant_id       TEXT        NOT NULL,

    -- Referencia al lead (nullable: puede que aún no exista en leads_crm)
    lead_id         UUID        REFERENCES public.leads_crm(id)
                                ON DELETE SET NULL,

    -- Datos del llamante
    telefono        TEXT        NOT NULL DEFAULT '',

    -- Resultado de la llamada
    resultado       TEXT        NOT NULL DEFAULT 'desconocido'
                                CHECK (resultado IN (
                                    'cerrado',       -- venta / cita agendada
                                    'perdido',       -- llamada terminó sin cierre
                                    'no_contesto',   -- nadie contestó
                                    'desconocido'    -- Vapi no pudo evaluar
                                )),

    -- Contenido de la llamada
    transcripcion   TEXT        NOT NULL DEFAULT '',   -- texto completo de la conversación
    resumen_ia      TEXT        NOT NULL DEFAULT '',   -- resumen/análisis de Vapi o Claude

    -- Métricas
    duracion_seg    INTEGER     NOT NULL DEFAULT 0
                                CHECK (duracion_seg >= 0),
    puntuacion      SMALLINT    NOT NULL DEFAULT 5
                                CHECK (puntuacion BETWEEN 1 AND 10),

    -- Contexto del agente
    modo_operacion  TEXT        NOT NULL DEFAULT 'venta'
                                CHECK (modo_operacion IN (
                                    'venta', 'b2b', 'venta_directa', 'prospeccion_b2b'
                                )),

    -- Trazabilidad Vapi
    vapi_call_id    TEXT        NOT NULL DEFAULT '',   -- ID único de la llamada en Vapi

    -- Datos extra (análisis de Vapi, metadata de la llamada, etc.)
    metadata        JSONB       NOT NULL DEFAULT '{}',

    -- Timestamp inmutable
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Sin updated_at: historial_llamadas es inmutable (cada llamada = un registro nuevo)
);

-- ── Índices para alta concurrencia multi-tenant ───────────────────────────────
CREATE INDEX IF NOT EXISTS idx_hist_tenant
    ON public.historial_llamadas (tenant_id);

CREATE INDEX IF NOT EXISTS idx_hist_tenant_resultado
    ON public.historial_llamadas (tenant_id, resultado);

CREATE INDEX IF NOT EXISTS idx_hist_tenant_telefono
    ON public.historial_llamadas (tenant_id, telefono);

CREATE INDEX IF NOT EXISTS idx_hist_lead_id
    ON public.historial_llamadas (lead_id)
    WHERE lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hist_vapi_call_id
    ON public.historial_llamadas (vapi_call_id)
    WHERE vapi_call_id <> '';

CREATE INDEX IF NOT EXISTS idx_hist_created_at
    ON public.historial_llamadas (created_at DESC);

-- Índice compuesto para dashboards: tenant + fecha + resultado
CREATE INDEX IF NOT EXISTS idx_hist_tenant_fecha_resultado
    ON public.historial_llamadas (tenant_id, created_at DESC, resultado);


-- ── Row Level Security ────────────────────────────────────────────────────────
ALTER TABLE public.historial_llamadas ENABLE ROW LEVEL SECURITY;

-- Cada tenant solo ve sus propias llamadas (cuando se autentican desde el frontend)
CREATE POLICY IF NOT EXISTS "tenant_isolation_historial"
    ON public.historial_llamadas
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

-- El backend (service_role) tiene acceso total
CREATE POLICY IF NOT EXISTS "service_role_full_access_historial"
    ON public.historial_llamadas
    FOR ALL
    TO service_role
    USING (TRUE);


-- ── Vista: resumen de rendimiento por tenant ──────────────────────────────────
CREATE OR REPLACE VIEW public.rendimiento_llamadas AS
    SELECT
        h.tenant_id,
        COUNT(*)                                            AS total_llamadas,
        COUNT(*) FILTER (WHERE h.resultado = 'cerrado')    AS ventas_cerradas,
        COUNT(*) FILTER (WHERE h.resultado = 'perdido')    AS llamadas_perdidas,
        COUNT(*) FILTER (WHERE h.resultado = 'no_contesto') AS sin_respuesta,
        ROUND(
            COUNT(*) FILTER (WHERE h.resultado = 'cerrado')::NUMERIC
            / NULLIF(COUNT(*), 0) * 100, 1
        )                                                   AS tasa_conversion_pct,
        ROUND(AVG(h.duracion_seg))                         AS duracion_promedio_seg,
        ROUND(AVG(h.puntuacion), 1)                        AS puntuacion_promedio,
        MAX(h.created_at)                                   AS ultima_llamada
    FROM public.historial_llamadas h
    GROUP BY h.tenant_id
    ORDER BY total_llamadas DESC;


-- ── Vista: detalle de llamadas con datos del lead ─────────────────────────────
CREATE OR REPLACE VIEW public.llamadas_con_lead AS
    SELECT
        h.id            AS historial_id,
        h.tenant_id,
        h.telefono,
        h.resultado,
        h.duracion_seg,
        h.puntuacion,
        h.modo_operacion,
        h.vapi_call_id,
        h.created_at,
        l.nombre        AS lead_nombre,
        l.empresa       AS lead_empresa,
        l.lead_score,
        l.estado        AS lead_estado,
        l.notas         AS lead_notas
    FROM public.historial_llamadas h
    LEFT JOIN public.leads_crm l
        ON l.id = h.lead_id
    ORDER BY h.created_at DESC;
