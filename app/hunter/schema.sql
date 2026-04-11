-- ============================================================
-- HUNTER SCHEMA — Multi-tenant (10,000 clientes)
-- Ejecutar en: Supabase → SQL Editor
-- ============================================================

-- ─────────────────────────────────────────────────────────
-- TABLA 1: leads_crm
-- CRM central de leads con score 1-10 por tenant
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.leads_crm (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT        NOT NULL,               -- ID del cliente (multi-tenant)
    nombre      TEXT        NOT NULL DEFAULT '',
    telefono    TEXT        NOT NULL DEFAULT '',
    email       TEXT        NOT NULL DEFAULT '',
    empresa     TEXT        NOT NULL DEFAULT '',
    fuente      TEXT        NOT NULL DEFAULT 'manual',  -- google_maps | manual | whatsapp | vapi
    lead_score  SMALLINT    NOT NULL DEFAULT 1
                            CHECK (lead_score BETWEEN 1 AND 10),
    estado      TEXT        NOT NULL DEFAULT 'nuevo'
                            CHECK (estado IN ('nuevo','contactado','calificado','propuesta','cerrado','perdido')),
    notas       TEXT        NOT NULL DEFAULT '',
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unicidad por tenant: no duplicar el mismo teléfono en el mismo tenant
    CONSTRAINT uq_leads_crm_tenant_telefono UNIQUE (tenant_id, telefono)
);

-- Índices para alta concurrencia multi-tenant
CREATE INDEX IF NOT EXISTS idx_leads_crm_tenant       ON public.leads_crm (tenant_id);
CREATE INDEX IF NOT EXISTS idx_leads_crm_tenant_score ON public.leads_crm (tenant_id, lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_crm_estado       ON public.leads_crm (tenant_id, estado);
CREATE INDEX IF NOT EXISTS idx_leads_crm_fuente       ON public.leads_crm (tenant_id, fuente);
CREATE INDEX IF NOT EXISTS idx_leads_crm_created_at   ON public.leads_crm (created_at DESC);

-- Auto-update de updated_at
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_leads_crm_updated_at ON public.leads_crm;
CREATE TRIGGER trg_leads_crm_updated_at
    BEFORE UPDATE ON public.leads_crm
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ─────────────────────────────────────────────────────────
-- TABLA 2: prospectos_hunter
-- Datos crudos de Google Maps por tenant
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.prospectos_hunter (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL,
    nombre_negocio  TEXT        NOT NULL DEFAULT '',
    direccion       TEXT        NOT NULL DEFAULT '',
    telefono        TEXT        NOT NULL DEFAULT '',
    sitio_web       TEXT        NOT NULL DEFAULT '',
    rating          NUMERIC(3,1),                       -- ej: 4.5
    total_reviews   INTEGER     NOT NULL DEFAULT 0,
    categoria       TEXT        NOT NULL DEFAULT '',
    latitud         NUMERIC(10,7),
    longitud        NUMERIC(10,7),
    lugar_id        TEXT        NOT NULL DEFAULT '',     -- Google Place ID
    ciudad          TEXT        NOT NULL DEFAULT '',
    pais            TEXT        NOT NULL DEFAULT 'CO',
    horario         JSONB,                              -- opening_hours de Google
    fotos           JSONB       NOT NULL DEFAULT '[]',  -- array de photo_references
    metadata        JSONB       NOT NULL DEFAULT '{}',
    procesado       BOOLEAN     NOT NULL DEFAULT FALSE, -- ya fue contactado/trabajado
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- No duplicar el mismo negocio de Google Maps dentro del mismo tenant
    CONSTRAINT uq_prospectos_hunter_tenant_lugar UNIQUE (tenant_id, lugar_id)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_prospectos_tenant          ON public.prospectos_hunter (tenant_id);
CREATE INDEX IF NOT EXISTS idx_prospectos_tenant_ciudad   ON public.prospectos_hunter (tenant_id, ciudad);
CREATE INDEX IF NOT EXISTS idx_prospectos_procesado       ON public.prospectos_hunter (tenant_id, procesado);
CREATE INDEX IF NOT EXISTS idx_prospectos_rating          ON public.prospectos_hunter (tenant_id, rating DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_prospectos_created_at      ON public.prospectos_hunter (created_at DESC);
-- Búsqueda full-text sobre nombre y categoría
CREATE INDEX IF NOT EXISTS idx_prospectos_nombre_fts      ON public.prospectos_hunter
    USING GIN (to_tsvector('spanish', nombre_negocio || ' ' || categoria));


-- ─────────────────────────────────────────────────────────
-- ROW LEVEL SECURITY (RLS) — Aislamiento total por tenant
-- Con RLS activo cada tenant sólo ve sus propios registros,
-- incluso si usan la misma ANON key de Supabase.
-- ─────────────────────────────────────────────────────────
ALTER TABLE public.leads_crm        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prospectos_hunter ENABLE ROW LEVEL SECURITY;

-- Política: sólo ve sus registros (autenticado + service_role bypass)
CREATE POLICY IF NOT EXISTS "tenant_isolation_leads_crm"
    ON public.leads_crm
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY IF NOT EXISTS "tenant_isolation_prospectos_hunter"
    ON public.prospectos_hunter
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

-- Permitir acceso total desde service_role (el backend usa service key)
CREATE POLICY IF NOT EXISTS "service_role_full_access_leads"
    ON public.leads_crm
    FOR ALL
    TO service_role
    USING (TRUE);

CREATE POLICY IF NOT EXISTS "service_role_full_access_prospectos"
    ON public.prospectos_hunter
    FOR ALL
    TO service_role
    USING (TRUE);


-- ─────────────────────────────────────────────────────────
-- VISTA: leads_calientes
-- Leads con score >= 7 — útil para dashboards
-- ─────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.leads_calientes AS
    SELECT
        l.id,
        l.tenant_id,
        l.nombre,
        l.telefono,
        l.empresa,
        l.lead_score,
        l.estado,
        l.fuente,
        l.created_at,
        p.rating          AS gmaps_rating,
        p.total_reviews   AS gmaps_reviews,
        p.ciudad          AS gmaps_ciudad
    FROM public.leads_crm l
    LEFT JOIN public.prospectos_hunter p
        ON p.tenant_id = l.tenant_id
        AND p.lugar_id  = (l.metadata->>'lugar_id')
    WHERE l.lead_score >= 7
    ORDER BY l.lead_score DESC, l.created_at DESC;


-- ─────────────────────────────────────────────────────────
-- NOTAS PARA ESCALAR A 10,000 TENANTS
-- ─────────────────────────────────────────────────────────
-- 1. Supabase ya usa PgBouncer (pool de conexiones) → no necesitas
--    configurar nada extra para soportar alta concurrencia.
-- 2. Los índices en tenant_id garantizan O(log n) en cada query.
-- 3. El UNIQUE constraint evita duplicados en upsert concurrente.
-- 4. Si un tenant tiene >1M de registros, considera particionado:
--    PARTITION BY HASH (tenant_id) con 16 particiones.
-- 5. Para analytics de todos los tenants (admin), usa service_role
--    que bypasea RLS.
-- ─────────────────────────────────────────────────────────
