-- ══════════════════════════════════════════════════════════════════════════════
-- MIGRACIÓN 001 — Módulo Centinela de Recuperación de Cartera
-- Ejecutar en: Supabase Dashboard → SQL Editor
-- Proyecto: https://zuvscvatsugwdesxnfpe.supabase.co
-- ══════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- Tabla 1: clientes_recuperacion
-- Registra cada deudor con su deuda, mora e intereses
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.clientes_recuperacion (
    id                     UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id              TEXT          NOT NULL,
    nombre                 TEXT          NOT NULL,
    telefono               TEXT          NOT NULL,
    cedula                 TEXT          DEFAULT '',
    deuda_original         NUMERIC(14,2) NOT NULL CHECK (deuda_original >= 0),
    deuda_actual           NUMERIC(14,2) NOT NULL CHECK (deuda_actual >= 0),
    dias_mora              INTEGER       NOT NULL DEFAULT 0 CHECK (dias_mora >= 0),
    tasa_interes_diaria    NUMERIC(8,6)  NOT NULL DEFAULT 0.001,     -- 0.1% diario por defecto
    intereses_acumulados   NUMERIC(14,2) NOT NULL DEFAULT 0,
    quita_porcentaje       NUMERIC(5,2)  NOT NULL DEFAULT 0,         -- % de descuento aplicado
    quita_monto            NUMERIC(14,2) NOT NULL DEFAULT 0,         -- monto en $ del descuento
    monto_a_pagar          NUMERIC(14,2) GENERATED ALWAYS AS
                               (deuda_actual + intereses_acumulados - quita_monto) STORED,
    estado                 TEXT          NOT NULL DEFAULT 'activo'
                               CHECK (estado IN ('activo','negociando','acuerdo','pagado','incobrable')),
    canal_contacto         TEXT          NOT NULL DEFAULT 'whatsapp'
                               CHECK (canal_contacto IN ('whatsapp','voz','email','presencial')),
    fecha_vencimiento      DATE,
    notas                  TEXT          DEFAULT '',
    metadata               JSONB         DEFAULT '{}'::jsonb,
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Índices para búsquedas frecuentes
CREATE INDEX IF NOT EXISTS idx_clientes_rec_tenant   ON public.clientes_recuperacion (tenant_id);
CREATE INDEX IF NOT EXISTS idx_clientes_rec_telefono ON public.clientes_recuperacion (tenant_id, telefono);
CREATE INDEX IF NOT EXISTS idx_clientes_rec_estado   ON public.clientes_recuperacion (tenant_id, estado);
CREATE INDEX IF NOT EXISTS idx_clientes_rec_mora     ON public.clientes_recuperacion (dias_mora DESC);

-- Trigger para updated_at automático
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clientes_rec_updated_at ON public.clientes_recuperacion;
CREATE TRIGGER trg_clientes_rec_updated_at
    BEFORE UPDATE ON public.clientes_recuperacion
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- Tabla 2: bitacora_centinela
-- Registra CADA acción de cobro ejecutada por la IA (inmutable)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bitacora_centinela (
    id                UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id         TEXT          NOT NULL,
    cliente_id        UUID          REFERENCES public.clientes_recuperacion(id) ON DELETE SET NULL,
    telefono          TEXT          NOT NULL DEFAULT '',
    accion            TEXT          NOT NULL
                          CHECK (accion IN (
                              'llamada_iniciada','llamada_completada','whatsapp_enviado',
                              'propuesta_quita','acuerdo_pago','pago_parcial',
                              'pago_total','no_contesto','promesa_pago','incobrable_marcado'
                          )),
    agente_ia         TEXT          NOT NULL DEFAULT 'centinela',
    descripcion       TEXT          DEFAULT '',
    monto_propuesto   NUMERIC(14,2) DEFAULT 0,
    monto_acordado    NUMERIC(14,2) DEFAULT 0,
    quita_ofrecida    NUMERIC(5,2)  DEFAULT 0,   -- % ofrecido en esta acción
    resultado         TEXT          NOT NULL DEFAULT 'pendiente'
                          CHECK (resultado IN ('exitoso','fallido','pendiente','sin_respuesta')),
    transcripcion     TEXT          DEFAULT '',
    resumen_ia        TEXT          DEFAULT '',
    duracion_seg      INTEGER       DEFAULT 0,
    metadata          JSONB         DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    -- NO updated_at: la bitácora es inmutable
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_bitacora_tenant     ON public.bitacora_centinela (tenant_id);
CREATE INDEX IF NOT EXISTS idx_bitacora_cliente    ON public.bitacora_centinela (cliente_id);
CREATE INDEX IF NOT EXISTS idx_bitacora_accion     ON public.bitacora_centinela (tenant_id, accion);
CREATE INDEX IF NOT EXISTS idx_bitacora_created    ON public.bitacora_centinela (created_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- RLS (Row Level Security) — opcional, habilitar si se usa autenticación
-- ─────────────────────────────────────────────────────────────────────────────
-- ALTER TABLE public.clientes_recuperacion ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.bitacora_centinela    ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────────────────────
-- Vista de resumen por tenant (útil para dashboard)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.v_resumen_cartera AS
SELECT
    tenant_id,
    COUNT(*)                                      AS total_deudores,
    SUM(deuda_actual)                             AS cartera_total,
    SUM(intereses_acumulados)                     AS intereses_totales,
    SUM(monto_a_pagar)                            AS total_por_cobrar,
    AVG(dias_mora)                                AS promedio_dias_mora,
    COUNT(*) FILTER (WHERE estado = 'activo')     AS activos,
    COUNT(*) FILTER (WHERE estado = 'negociando') AS en_negociacion,
    COUNT(*) FILTER (WHERE estado = 'acuerdo')    AS con_acuerdo,
    COUNT(*) FILTER (WHERE estado = 'pagado')     AS pagados,
    COUNT(*) FILTER (WHERE estado = 'incobrable') AS incobrables
FROM public.clientes_recuperacion
GROUP BY tenant_id;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verificación final
-- ─────────────────────────────────────────────────────────────────────────────
SELECT 'clientes_recuperacion' AS tabla, COUNT(*) AS filas FROM public.clientes_recuperacion
UNION ALL
SELECT 'bitacora_centinela',            COUNT(*) FROM public.bitacora_centinela;
