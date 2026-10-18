-- V1 build completion: customer Security & Data controls and Help/Support workflows.
-- Customer requests/cases use immutable anchors + append-only events. No browser path
-- can directly delete a tenant, revoke provider credentials, or rewrite support history.

CREATE TABLE IF NOT EXISTS recovery.customer_support_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid,
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    category text NOT NULL CHECK (category IN ('product','data','google_ads','billing','access','security','reporting','other')),
    subject text NOT NULL,
    initial_body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (btrim(subject)<>'' AND length(subject)<=240),
    CHECK (btrim(initial_body)<>'' AND length(initial_body)<=10000)
);
CREATE INDEX IF NOT EXISTS customer_support_cases_scope_idx ON recovery.customer_support_cases(tenant_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.customer_support_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    case_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('opened','commented','closed','reopened')),
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,case_id) REFERENCES recovery.customer_support_cases(tenant_id,id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS customer_support_events_case_idx ON recovery.customer_support_events(tenant_id,case_id,occurred_at,id);

CREATE TABLE IF NOT EXISTS recovery.customer_data_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid,
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    request_type text NOT NULL CHECK (request_type IN ('full_data_export','organization_deletion','google_ads_disconnect')),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (btrim(reason)<>'' AND length(reason)<=5000),
    CHECK ((request_type='google_ads_disconnect' AND account_id IS NOT NULL) OR request_type<>'google_ads_disconnect')
);
CREATE INDEX IF NOT EXISTS customer_data_requests_scope_idx ON recovery.customer_data_requests(tenant_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.customer_data_request_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    request_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('requested','cancelled','acknowledged','in_progress','completed','rejected')),
    actor_user_id uuid REFERENCES recovery.app_users(id) ON DELETE SET NULL,
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,request_id) REFERENCES recovery.customer_data_requests(tenant_id,id) ON DELETE CASCADE,
    CHECK (btrim(actor)<>'' AND length(actor)<=300),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS customer_data_request_events_projection_idx ON recovery.customer_data_request_events(tenant_id,request_id,occurred_at,id);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['customer_support_cases','customer_support_events','customer_data_requests','customer_data_request_events'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
    EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
    EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())',t);
  END LOOP;
END $$;
