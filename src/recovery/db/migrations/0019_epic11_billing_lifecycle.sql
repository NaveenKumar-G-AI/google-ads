-- Epic 11: complete billing lifecycle on top of the Phase-17 Razorpay authority model.
-- Consequential provider operations are fenced by immutable operation/event history.

-- Grace is an explicit Recovery OS business policy state, never a provider status.
ALTER TABLE recovery.billing_subscription_snapshots
    DROP CONSTRAINT IF EXISTS billing_subscription_snapshots_entitlement_state_check;
ALTER TABLE recovery.billing_subscription_snapshots
    ADD CONSTRAINT billing_subscription_snapshots_entitlement_state_check
    CHECK (entitlement_state IN ('full','grace','billing_pending','read_only','unsubscribed','blocked'));

ALTER TABLE recovery.billing_tenant_current
    DROP CONSTRAINT IF EXISTS billing_tenant_current_entitlement_state_check;
ALTER TABLE recovery.billing_tenant_current
    ADD CONSTRAINT billing_tenant_current_entitlement_state_check
    CHECK (entitlement_state IN ('full','grace','billing_pending','read_only','unsubscribed','blocked'));

ALTER TABLE recovery.billing_subscription_snapshots
    ADD COLUMN IF NOT EXISTS provider_customer_id text,
    ADD COLUMN IF NOT EXISTS payment_method text,
    ADD COLUMN IF NOT EXISTS total_count integer,
    ADD COLUMN IF NOT EXISTS paid_count integer,
    ADD COLUMN IF NOT EXISTS remaining_count integer,
    ADD COLUMN IF NOT EXISTS has_scheduled_changes boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS change_scheduled_at timestamptz,
    ADD COLUMN IF NOT EXISTS charge_at timestamptz,
    ADD COLUMN IF NOT EXISTS ended_at timestamptz,
    ADD COLUMN IF NOT EXISTS grace_until timestamptz;

ALTER TABLE recovery.billing_tenant_current
    ADD COLUMN IF NOT EXISTS provider_customer_id text,
    ADD COLUMN IF NOT EXISTS payment_method text,
    ADD COLUMN IF NOT EXISTS total_count integer,
    ADD COLUMN IF NOT EXISTS paid_count integer,
    ADD COLUMN IF NOT EXISTS remaining_count integer,
    ADD COLUMN IF NOT EXISTS has_scheduled_changes boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS change_scheduled_at timestamptz,
    ADD COLUMN IF NOT EXISTS charge_at timestamptz,
    ADD COLUMN IF NOT EXISTS ended_at timestamptz,
    ADD COLUMN IF NOT EXISTS grace_until timestamptz;

ALTER TABLE recovery.billing_subscription_snapshots
    DROP CONSTRAINT IF EXISTS billing_subscription_snapshots_counts_nonnegative,
    ADD CONSTRAINT billing_subscription_snapshots_counts_nonnegative
    CHECK ((total_count IS NULL OR total_count>=0) AND (paid_count IS NULL OR paid_count>=0) AND (remaining_count IS NULL OR remaining_count>=0));

ALTER TABLE recovery.billing_tenant_current
    DROP CONSTRAINT IF EXISTS billing_tenant_current_counts_nonnegative,
    ADD CONSTRAINT billing_tenant_current_counts_nonnegative
    CHECK ((total_count IS NULL OR total_count>=0) AND (paid_count IS NULL OR paid_count>=0) AND (remaining_count IS NULL OR remaining_count>=0));

CREATE TABLE IF NOT EXISTS recovery.billing_lifecycle_operations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    requested_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    operation_type text NOT NULL CHECK (operation_type IN (
        'plan_change_cycle_end','cancel_plan_change','cancel_cycle_end'
    )),
    provider_subscription_id text NOT NULL,
    target_plan_key text,
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    effective_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,requested_by,idempotency_key),
    CHECK (provider_subscription_id ~ '^sub_[A-Za-z0-9]+$'),
    CHECK (target_plan_key IS NULL OR length(target_plan_key) BETWEEN 1 AND 64)
);
CREATE INDEX IF NOT EXISTS billing_lifecycle_operations_subscription_idx
    ON recovery.billing_lifecycle_operations(tenant_id,provider_subscription_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.billing_lifecycle_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    operation_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'prepared','in_flight','provider_observed','ambiguous','failed','reconciled'
    )),
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,operation_id) REFERENCES recovery.billing_lifecycle_operations(tenant_id,id) ON DELETE RESTRICT,
    CHECK (btrim(actor)<>'' AND length(actor)<=320),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS billing_lifecycle_events_projection_idx
    ON recovery.billing_lifecycle_events(tenant_id,operation_id,occurred_at,id);

CREATE TABLE IF NOT EXISTS recovery.billing_pending_change_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    provider_subscription_id text NOT NULL,
    provider_plan_id text NOT NULL,
    target_plan_key text NOT NULL,
    provider_payload jsonb NOT NULL,
    provider_payload_sha256 char(64) NOT NULL CHECK (provider_payload_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,provider_subscription_id,provider_payload_sha256),
    CHECK (jsonb_typeof(provider_payload)='object')
);
CREATE INDEX IF NOT EXISTS billing_pending_change_latest_idx
    ON recovery.billing_pending_change_snapshots(tenant_id,provider_subscription_id,observed_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.billing_invoice_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    provider_subscription_id text NOT NULL,
    provider_invoice_id text NOT NULL,
    provider_payment_id text,
    status text NOT NULL,
    currency text NOT NULL,
    amount integer NOT NULL CHECK (amount>=0),
    amount_paid integer NOT NULL CHECK (amount_paid>=0),
    amount_due integer NOT NULL CHECK (amount_due>=0),
    issued_at timestamptz,
    paid_at timestamptz,
    provider_payload jsonb NOT NULL,
    provider_payload_sha256 char(64) NOT NULL CHECK (provider_payload_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,provider_invoice_id,provider_payload_sha256),
    CHECK (provider_invoice_id ~ '^inv_[A-Za-z0-9]+$'),
    CHECK (currency ~ '^[A-Z]{3}$'),
    CHECK (jsonb_typeof(provider_payload)='object')
);
CREATE INDEX IF NOT EXISTS billing_invoice_latest_idx
    ON recovery.billing_invoice_snapshots(tenant_id,provider_subscription_id,issued_at DESC NULLS LAST,observed_at DESC);

CREATE TABLE IF NOT EXISTS recovery.billing_profile_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    legal_name text NOT NULL,
    billing_email text NOT NULL,
    tax_country text NOT NULL,
    tax_region text,
    gstin text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(legal_name)<>'' AND length(legal_name)<=200),
    CHECK (billing_email=lower(btrim(billing_email)) AND position('@' IN billing_email)>1 AND length(billing_email)<=320),
    CHECK (tax_country ~ '^[A-Z]{2}$'),
    CHECK (tax_region IS NULL OR length(tax_region)<=120),
    CHECK (gstin IS NULL OR gstin ~ '^[0-9A-Z]{15}$')
);
CREATE INDEX IF NOT EXISTS billing_profile_events_latest_idx
    ON recovery.billing_profile_events(tenant_id,occurred_at DESC,id DESC);

-- Phase-17 slots were permanent rows. Epic 11 introduces explicit assign/release events
-- so customers can rotate the accounts consuming plan capacity without deleting history.
CREATE TABLE IF NOT EXISTS recovery.billing_account_slot_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('assign','release')),
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (btrim(actor)<>'' AND length(actor)<=320),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS billing_account_slot_events_latest_idx
    ON recovery.billing_account_slot_events(tenant_id,account_id,occurred_at DESC,id DESC);

INSERT INTO recovery.billing_account_slot_events(tenant_id,account_id,event_type,actor,occurred_at,payload)
SELECT s.tenant_id,s.account_id,'assign','migration:phase17-slot',s.assigned_at,'{"source":"billing_account_slots"}'::jsonb
FROM recovery.billing_account_slots s
WHERE NOT EXISTS (
    SELECT 1 FROM recovery.billing_account_slot_events e
    WHERE e.tenant_id=s.tenant_id AND e.account_id=s.account_id
);

-- Every Epic-11 history/evidence table is immutable. Current billing_tenant_current remains
-- a mutable server projection derived only from provider reconciliation.
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY[
      'billing_lifecycle_operations','billing_lifecycle_events','billing_pending_change_snapshots',
      'billing_invoice_snapshots','billing_profile_events','billing_account_slot_events'
    ] LOOP
      EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
      EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
      EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
      EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
      EXECUTE format('DROP POLICY IF EXISTS billing_backend_only ON recovery.%I',t);
      EXECUTE format('CREATE POLICY billing_backend_only ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())',t);
    END LOOP;
END $$;
