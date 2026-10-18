-- Phase 17: Razorpay-backed billing, entitlement projection, and controlled onboarding.

CREATE TABLE IF NOT EXISTS recovery.billing_checkout_intents (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    requested_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    plan_key text NOT NULL CHECK (length(plan_key) BETWEEN 1 AND 64),
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    provider text NOT NULL DEFAULT 'razorpay' CHECK (provider='razorpay'),
    provider_subscription_id text UNIQUE,
    provider_plan_id text,
    state text NOT NULL CHECK (state IN ('prepared','in_flight','provider_created','ambiguous','failed')),
    checkout_url text,
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, requested_by, idempotency_key)
);

CREATE TABLE IF NOT EXISTS recovery.billing_webhook_events (
    id uuid PRIMARY KEY,
    provider text NOT NULL DEFAULT 'razorpay' CHECK (provider='razorpay'),
    provider_event_id text NOT NULL,
    raw_body_sha256 char(64) NOT NULL CHECK (raw_body_sha256 ~ '^[0-9a-f]{64}$'),
    signature_verified boolean NOT NULL CHECK (signature_verified = true),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(provider, provider_event_id)
);

CREATE TABLE IF NOT EXISTS recovery.billing_webhook_results (
    id uuid PRIMARY KEY,
    webhook_event_id uuid NOT NULL UNIQUE REFERENCES recovery.billing_webhook_events(id) ON DELETE RESTRICT,
    tenant_id uuid REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    provider_subscription_id text,
    event_type text,
    reconcile_status text NOT NULL CHECK (reconcile_status IN ('ignored','reconciled','unknown_subscription','failed')),
    error_code text,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery.billing_subscription_snapshots (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    provider text NOT NULL DEFAULT 'razorpay' CHECK (provider='razorpay'),
    provider_subscription_id text NOT NULL,
    provider_plan_id text NOT NULL,
    plan_key text NOT NULL,
    provider_status text NOT NULL,
    entitlement_state text NOT NULL CHECK (entitlement_state IN ('full','billing_pending','read_only','unsubscribed','blocked')),
    current_start timestamptz,
    current_end timestamptz,
    quantity integer NOT NULL CHECK (quantity > 0),
    provider_payload jsonb NOT NULL,
    provider_payload_sha256 char(64) NOT NULL CHECK (provider_payload_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, provider_subscription_id, provider_payload_sha256)
);

CREATE TABLE IF NOT EXISTS recovery.billing_tenant_current (
    tenant_id uuid PRIMARY KEY REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    provider text NOT NULL DEFAULT 'razorpay' CHECK (provider='razorpay'),
    provider_subscription_id text NOT NULL UNIQUE,
    provider_plan_id text NOT NULL,
    plan_key text NOT NULL,
    provider_status text NOT NULL,
    entitlement_state text NOT NULL CHECK (entitlement_state IN ('full','billing_pending','read_only','unsubscribed','blocked')),
    current_start timestamptz,
    current_end timestamptz,
    reconciled_snapshot_id uuid NOT NULL REFERENCES recovery.billing_subscription_snapshots(id) ON DELETE RESTRICT,
    reconciled_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery.billing_account_slots (
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL REFERENCES recovery.google_ads_accounts(id) ON DELETE RESTRICT,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id, account_id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_billing_checkout_provider_subscription
ON recovery.billing_checkout_intents(provider_subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_snapshots_tenant_observed
ON recovery.billing_subscription_snapshots(tenant_id, observed_at DESC);

-- Evidence/history tables are append-only.
DO $$ BEGIN
    CREATE TRIGGER billing_webhook_events_append_only
    BEFORE UPDATE OR DELETE ON recovery.billing_webhook_events
    FOR EACH ROW EXECUTE FUNCTION recovery.reject_update_delete();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TRIGGER billing_webhook_results_append_only
    BEFORE UPDATE OR DELETE ON recovery.billing_webhook_results
    FOR EACH ROW EXECUTE FUNCTION recovery.reject_update_delete();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TRIGGER billing_subscription_snapshots_append_only
    BEFORE UPDATE OR DELETE ON recovery.billing_subscription_snapshots
    FOR EACH ROW EXECUTE FUNCTION recovery.reject_update_delete();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TRIGGER billing_account_slots_no_delete
    BEFORE DELETE ON recovery.billing_account_slots
    FOR EACH ROW EXECUTE FUNCTION recovery.reject_update_delete();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE recovery.billing_checkout_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_checkout_intents FORCE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_subscription_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_subscription_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_tenant_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_tenant_current FORCE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_account_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.billing_account_slots FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY billing_checkout_tenant_policy ON recovery.billing_checkout_intents
      USING (tenant_id = recovery.current_tenant_id())
      WITH CHECK (tenant_id = recovery.current_tenant_id());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE POLICY billing_snapshots_tenant_policy ON recovery.billing_subscription_snapshots
      USING (tenant_id = recovery.current_tenant_id())
      WITH CHECK (tenant_id = recovery.current_tenant_id());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE POLICY billing_current_tenant_policy ON recovery.billing_tenant_current
      USING (tenant_id = recovery.current_tenant_id())
      WITH CHECK (tenant_id = recovery.current_tenant_id());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE POLICY billing_slots_tenant_policy ON recovery.billing_account_slots
      USING (tenant_id = recovery.current_tenant_id())
      WITH CHECK (tenant_id = recovery.current_tenant_id());
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
