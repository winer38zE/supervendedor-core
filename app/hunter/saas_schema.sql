-- ============================================================
-- PLATAFORMA SAAS MULTI-TENANT — ED NET PRO
-- Tablas: tenants · wallets · wallet_transactions
-- Ejecutar en: Supabase → SQL Editor
-- ============================================================

-- ── Función set_updated_at (si no existe ya) ───────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;


-- ══════════════════════════════════════════════════════════════════════════════
-- 1. TENANTS — Registro de cada cliente de la plataforma
-- ══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.tenants (
    id              TEXT        PRIMARY KEY,  -- = client_id en Vapi / clients_config

    -- Datos del negocio
    nombre          TEXT        NOT NULL,
    email           TEXT        NOT NULL UNIQUE,
    telefono        TEXT        NOT NULL DEFAULT '',

    -- Plan y estado
    plan            TEXT        NOT NULL DEFAULT 'trial'
                                CHECK (plan IN ('trial', 'prepago', 'suspendido', 'cancelado')),
    estado          TEXT        NOT NULL DEFAULT 'trial'
                                CHECK (estado IN ('trial', 'activo', 'suspendido', 'cancelado')),

    -- Trial de 3 días
    trial_inicia_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trial_expira_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '3 days',

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_estado
    ON public.tenants (estado);

CREATE INDEX IF NOT EXISTS idx_tenants_trial_expira
    ON public.tenants (trial_expira_at)
    WHERE estado = 'trial';

DROP TRIGGER IF EXISTS trg_tenants_updated_at ON public.tenants;
CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON public.tenants
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "tenant_ve_su_propio_registro"
    ON public.tenants FOR SELECT
    USING (id = current_setting('app.tenant_id', TRUE));

CREATE POLICY IF NOT EXISTS "service_role_full_tenants"
    ON public.tenants FOR ALL TO service_role USING (TRUE);


-- ══════════════════════════════════════════════════════════════════════════════
-- 2. WALLETS — Saldo prepago por tenant
-- ══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.wallets (
    tenant_id       TEXT        PRIMARY KEY
                                REFERENCES public.tenants(id) ON DELETE CASCADE,
    balance_usd     NUMERIC(12,4) NOT NULL DEFAULT 0.0000
                                CHECK (balance_usd >= 0),
    total_recargado NUMERIC(12,4) NOT NULL DEFAULT 0.0000,
    total_gastado   NUMERIC(12,4) NOT NULL DEFAULT 0.0000,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_wallets_updated_at ON public.wallets;
CREATE TRIGGER trg_wallets_updated_at
    BEFORE UPDATE ON public.wallets
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- RLS
ALTER TABLE public.wallets ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "tenant_ve_su_wallet"
    ON public.wallets FOR SELECT
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY IF NOT EXISTS "service_role_full_wallets"
    ON public.wallets FOR ALL TO service_role USING (TRUE);


-- ══════════════════════════════════════════════════════════════════════════════
-- 3. WALLET_TRANSACTIONS — Libro contable inmutable
-- ══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.wallet_transactions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL REFERENCES public.tenants(id),

    tipo            TEXT        NOT NULL
                                CHECK (tipo IN ('credito', 'debito', 'bono_trial', 'reembolso')),
    monto_usd       NUMERIC(12,4) NOT NULL,         -- positivo siempre; tipo indica dirección
    descripcion     TEXT        NOT NULL DEFAULT '',
    referencia_id   TEXT        NOT NULL DEFAULT '', -- vapi_call_id, payment_id, etc.
    balance_despues NUMERIC(12,4) NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_tx_ref
    ON public.wallet_transactions (tenant_id, referencia_id)
    WHERE referencia_id <> '';                      -- idempotencia por referencia

CREATE INDEX IF NOT EXISTS idx_wallet_tx_tenant
    ON public.wallet_transactions (tenant_id, created_at DESC);

-- RLS
ALTER TABLE public.wallet_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS "tenant_ve_sus_transacciones"
    ON public.wallet_transactions FOR SELECT
    USING (tenant_id = current_setting('app.tenant_id', TRUE));

CREATE POLICY IF NOT EXISTS "service_role_full_transactions"
    ON public.wallet_transactions FOR ALL TO service_role USING (TRUE);


-- ══════════════════════════════════════════════════════════════════════════════
-- 4. FUNCIÓN ATÓMICA: deducir_saldo
--    Descuenta el monto del wallet en una sola transacción PostgreSQL.
--    Retorna JSON: {ok, balance_anterior, balance_nuevo} o {ok: false, error}
-- ══════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.deducir_saldo(
    p_tenant_id     TEXT,
    p_monto_usd     NUMERIC,
    p_descripcion   TEXT    DEFAULT 'cargo automático',
    p_referencia_id TEXT    DEFAULT ''
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_balance       NUMERIC(12,4);
    v_nuevo_bal     NUMERIC(12,4);
BEGIN
    -- Verificar idempotencia: si ya existe la referencia, no cobrar dos veces
    IF p_referencia_id <> '' AND EXISTS (
        SELECT 1 FROM public.wallet_transactions
        WHERE tenant_id = p_tenant_id AND referencia_id = p_referencia_id
    ) THEN
        SELECT balance_despues INTO v_nuevo_bal
        FROM public.wallet_transactions
        WHERE tenant_id = p_tenant_id AND referencia_id = p_referencia_id
        LIMIT 1;
        RETURN jsonb_build_object('ok', true, 'idempotente', true, 'balance_nuevo', v_nuevo_bal);
    END IF;

    -- Bloqueo pesimista para concurrencia segura
    SELECT balance_usd INTO v_balance
    FROM public.wallets
    WHERE tenant_id = p_tenant_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'error', 'wallet_not_found');
    END IF;

    IF v_balance < p_monto_usd THEN
        RETURN jsonb_build_object(
            'ok', false,
            'error', 'saldo_insuficiente',
            'balance_actual', v_balance,
            'requerido', p_monto_usd
        );
    END IF;

    v_nuevo_bal := v_balance - p_monto_usd;

    UPDATE public.wallets
    SET balance_usd   = v_nuevo_bal,
        total_gastado = total_gastado + p_monto_usd
    WHERE tenant_id = p_tenant_id;

    INSERT INTO public.wallet_transactions
        (tenant_id, tipo, monto_usd, descripcion, referencia_id, balance_despues)
    VALUES
        (p_tenant_id, 'debito', p_monto_usd, p_descripcion, p_referencia_id, v_nuevo_bal);

    RETURN jsonb_build_object(
        'ok', true,
        'balance_anterior', v_balance,
        'balance_nuevo', v_nuevo_bal,
        'cobrado', p_monto_usd
    );
END;
$$;


-- ══════════════════════════════════════════════════════════════════════════════
-- 5. FUNCIÓN ATÓMICA: agregar_saldo
-- ══════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.agregar_saldo(
    p_tenant_id     TEXT,
    p_monto_usd     NUMERIC,
    p_tipo          TEXT    DEFAULT 'credito',   -- 'credito' | 'bono_trial' | 'reembolso'
    p_descripcion   TEXT    DEFAULT 'recarga',
    p_referencia_id TEXT    DEFAULT ''
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_balance   NUMERIC(12,4);
    v_nuevo_bal NUMERIC(12,4);
BEGIN
    SELECT balance_usd INTO v_balance
    FROM public.wallets
    WHERE tenant_id = p_tenant_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'error', 'wallet_not_found');
    END IF;

    v_nuevo_bal := v_balance + p_monto_usd;

    UPDATE public.wallets
    SET balance_usd      = v_nuevo_bal,
        total_recargado  = total_recargado + p_monto_usd
    WHERE tenant_id = p_tenant_id;

    INSERT INTO public.wallet_transactions
        (tenant_id, tipo, monto_usd, descripcion, referencia_id, balance_despues)
    VALUES
        (p_tenant_id, p_tipo, p_monto_usd, p_descripcion, p_referencia_id, v_nuevo_bal);

    -- Si el tenant estaba suspendido por falta de saldo, activarlo
    UPDATE public.tenants
    SET estado = 'activo', plan = 'prepago'
    WHERE id = p_tenant_id AND estado = 'suspendido';

    RETURN jsonb_build_object(
        'ok', true,
        'balance_anterior', v_balance,
        'balance_nuevo', v_nuevo_bal,
        'acreditado', p_monto_usd
    );
END;
$$;


-- ══════════════════════════════════════════════════════════════════════════════
-- 6. VISTA: resumen_saas — vista de negocio para el dashboard admin
-- ══════════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW public.resumen_saas AS
    SELECT
        t.id                                        AS tenant_id,
        t.nombre,
        t.email,
        t.telefono,
        t.estado,
        t.plan,
        t.trial_expira_at,
        GREATEST(0, EXTRACT(EPOCH FROM (t.trial_expira_at - NOW())) / 3600)::INT
                                                    AS horas_trial_restantes,
        COALESCE(w.balance_usd, 0)                  AS balance_usd,
        COALESCE(w.total_recargado, 0)              AS total_recargado,
        COALESCE(w.total_gastado, 0)                AS total_gastado,
        t.created_at
    FROM public.tenants t
    LEFT JOIN public.wallets w ON w.tenant_id = t.id
    ORDER BY t.created_at DESC;
