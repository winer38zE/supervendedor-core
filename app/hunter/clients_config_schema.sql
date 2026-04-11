-- ============================================================
-- CLIENTS CONFIG — Tabla de configuración de prompts por cliente
-- Ejecutar en: Supabase → SQL Editor
-- ============================================================

-- Si ya existe la tabla, solo agrega las columnas nuevas
ALTER TABLE IF EXISTS public.clients_config
    ADD COLUMN IF NOT EXISTS link_de_pago       TEXT,
    ADD COLUMN IF NOT EXISTS descuento_activo   TEXT,
    ADD COLUMN IF NOT EXISTS oferta_expira      TEXT,
    -- Inteligencia acumulada de llamadas reales (actualizada por business_evolver.py)
    ADD COLUMN IF NOT EXISTS dynamic_knowledge  JSONB NOT NULL DEFAULT '{}';

-- Actualizar el CHECK constraint para incluir los 4 modos
-- (DROP + ADD porque Postgres no soporta ALTER CONSTRAINT)
ALTER TABLE IF EXISTS public.clients_config
    DROP CONSTRAINT IF EXISTS clients_config_modo_operacion_check;

ALTER TABLE IF EXISTS public.clients_config
    ADD CONSTRAINT clients_config_modo_operacion_check
    CHECK (modo_operacion IN ('venta', 'b2b', 'venta_directa', 'prospeccion_b2b'));

-- ── Creación completa (primera vez) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.clients_config (
    client_id           TEXT        PRIMARY KEY,

    -- Modo de operación del agente de voz
    -- 'venta'           → B2C: agenda cita, tono cálido
    -- 'b2b'             → B2B consultivo: BANT+ + cierre de demo
    -- 'venta_directa'   → Cierre agresivo + link de pago en la llamada
    -- 'prospeccion_b2b' → SDR puro: descubrir dolores + agendar demo con AE
    modo_operacion      TEXT        NOT NULL DEFAULT 'venta'
                                    CHECK (modo_operacion IN (
                                        'venta', 'b2b', 'venta_directa', 'prospeccion_b2b'
                                    )),

    -- Identidad del agente
    nombre_agente       TEXT        NOT NULL DEFAULT 'Sofía',

    -- Contexto del negocio (rellenan las plantillas maestras)
    negocio_nombre      TEXT        NOT NULL DEFAULT '',
    negocio_tipo        TEXT        NOT NULL DEFAULT '',
    ciudad              TEXT        NOT NULL DEFAULT 'Colombia',
    productos_servicios TEXT        NOT NULL DEFAULT '',
    horario             TEXT        NOT NULL DEFAULT 'lunes a viernes 8:00 a.m. - 6:00 p.m.',
    precio_desde        TEXT        NOT NULL DEFAULT '',
    accion              TEXT        NOT NULL DEFAULT 'cita',

    -- Exclusivos del modo 'venta_directa'
    link_de_pago        TEXT,                               -- URL del checkout / pasarela
    descuento_activo    TEXT,                               -- Ej: "20% de descuento"
    oferta_expira       TEXT,                               -- Ej: "hoy a medianoche"

    -- Prompt libre: si se especifica, reemplaza la plantilla maestra completamente
    custom_prompt       TEXT,

    activo              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índice para búsquedas frecuentes por client_id + activo
CREATE INDEX IF NOT EXISTS idx_clients_config_activo
    ON public.clients_config (client_id, activo);

-- Auto-update updated_at
DROP TRIGGER IF EXISTS trg_clients_config_updated_at ON public.clients_config;
CREATE TRIGGER trg_clients_config_updated_at
    BEFORE UPDATE ON public.clients_config
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- ══════════════════════════════════════════════════════════════════════════════
-- DATOS DE EJEMPLO — Un cliente por cada modo
-- ══════════════════════════════════════════════════════════════════════════════

-- 1. MODO 'venta' — Clínica estética B2C (agenda cita, tono cálido)
INSERT INTO public.clients_config (
    client_id, modo_operacion, nombre_agente,
    negocio_nombre, negocio_tipo, ciudad,
    productos_servicios, horario, precio_desde, accion
) VALUES (
    'clinica_bella_cucuta', 'venta', 'Valentina',
    'Centro Estético Cúcuta Bella', 'clínica estética', 'Cúcuta',
    'depilación láser, hidratación facial, masajes, tratamientos corporales',
    'lunes a sábado de 8:00 a.m. a 7:00 p.m.',
    '$80.000 COP por sesión', 'cita de valoración gratuita'
) ON CONFLICT (client_id) DO UPDATE SET
    modo_operacion = EXCLUDED.modo_operacion,
    updated_at     = NOW();


-- 2. MODO 'b2b' — ED NET PRO (calificación BANT+ antes de demo)
INSERT INTO public.clients_config (
    client_id, modo_operacion, nombre_agente,
    negocio_nombre, negocio_tipo, ciudad,
    productos_servicios, horario, precio_desde, accion
) VALUES (
    'ed_net_pro', 'b2b', 'Carlos',
    'ED NET PRO', 'agencia de soluciones de IA y automatización', 'Colombia',
    'agentes de IA para ventas y soporte, automatización de citas, tarjetas NFC inteligentes, CRM con IA',
    'lunes a viernes de 8:00 a.m. a 6:00 p.m.',
    '$500.000 COP/mes', 'demo de 30 minutos'
) ON CONFLICT (client_id) DO UPDATE SET
    modo_operacion = EXCLUDED.modo_operacion,
    updated_at     = NOW();


-- 3. MODO 'venta_directa' — Producto digital con link de pago inmediato
INSERT INTO public.clients_config (
    client_id, modo_operacion, nombre_agente,
    negocio_nombre, negocio_tipo, ciudad,
    productos_servicios, precio_desde,
    link_de_pago, descuento_activo, oferta_expira
) VALUES (
    'ednetpro_curso_ia', 'venta_directa', 'Diego',
    'ED NET PRO Academy', 'plataforma de cursos online', 'Colombia',
    'curso de IA aplicada a ventas, automatización con n8n, agentes GPT para negocios',
    '$197.000 COP (precio especial)',
    'https://pay.ednetpro.co/curso-ia',
    '40% de descuento por lanzamiento',
    'este viernes a las 11:59 p.m.'
) ON CONFLICT (client_id) DO UPDATE SET
    modo_operacion   = EXCLUDED.modo_operacion,
    link_de_pago     = EXCLUDED.link_de_pago,
    descuento_activo = EXCLUDED.descuento_activo,
    oferta_expira    = EXCLUDED.oferta_expira,
    updated_at       = NOW();


-- 4. MODO 'prospeccion_b2b' — SDR que descubre dolores y agenda demo con AE
INSERT INTO public.clients_config (
    client_id, modo_operacion, nombre_agente,
    negocio_nombre, negocio_tipo, ciudad,
    productos_servicios, precio_desde, accion
) VALUES (
    'ednetpro_sdr', 'prospeccion_b2b', 'Laura',
    'ED NET PRO', 'agencia de automatización con IA', 'Colombia',
    'automatización de procesos, agentes de IA para ventas y soporte, integraciones CRM',
    '$500.000 COP/mes', 'demo de descubrimiento de 30 minutos'
) ON CONFLICT (client_id) DO UPDATE SET
    modo_operacion = EXCLUDED.modo_operacion,
    updated_at     = NOW();


-- ── Barbería (B2C clásico) ────────────────────────────────────────────────────
INSERT INTO public.clients_config (
    client_id, modo_operacion, nombre_agente,
    negocio_nombre, negocio_tipo, ciudad,
    productos_servicios, horario, precio_desde, accion
) VALUES (
    'barberia_default', 'venta', 'Andrés',
    'Barbería Clásica', 'barbería y peluquería', 'Medellín',
    'corte clásico, arreglo de barba, afeitado con navaja, tratamientos capilares',
    'martes a domingo de 9:00 a.m. a 8:00 p.m.',
    '$25.000 COP', 'turno de barbería'
) ON CONFLICT (client_id) DO NOTHING;
