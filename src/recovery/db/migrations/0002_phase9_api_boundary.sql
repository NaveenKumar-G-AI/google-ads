-- Phase 9: authenticated application boundary, tenant memberships, durable jobs,
-- and API idempotency. Browser clients never connect with the database service role.

CREATE OR REPLACE FUNCTION recovery_private.current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('recovery.user_id', true), '')::uuid
$$;

CREATE TABLE IF NOT EXISTS recovery.app_users (
    id uuid PRIMARY KEY,
    email text,
    disabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CHECK (email IS NULL OR btrim(email) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.tenant_memberships (
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('owner','admin','analyst','viewer')),
    status text NOT NULL CHECK (status IN ('active','disabled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);
CREATE INDEX IF NOT EXISTS tenant_memberships_user_idx
    ON recovery.tenant_memberships (user_id, status, tenant_id);

CREATE TABLE IF NOT EXISTS recovery.api_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    job_type text NOT NULL CHECK (job_type IN (
        'google_ads_sync','analysis_run','apply_negative','rollback_negative'
    )),
    status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    payload jsonb NOT NULL,
    requested_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    endpoint text NOT NULL,
    operation_key text,
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    leased_at timestamptz,
    lease_owner text,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    result jsonb,
    failure_code text,
    failure_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    UNIQUE (tenant_id, requested_by, endpoint, idempotency_key),
    UNIQUE (tenant_id, id),
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(endpoint) <> ''),
    CHECK (operation_key IS NULL OR (btrim(operation_key) <> '' AND length(operation_key) <= 200)),
    CHECK (btrim(idempotency_key) <> '' AND length(idempotency_key) <= 128),
    CHECK (attempts >= 0 AND max_attempts >= 1 AND attempts <= max_attempts),
    CHECK ((status IN ('succeeded','failed','cancelled') AND completed_at IS NOT NULL) OR status NOT IN ('succeeded','failed','cancelled'))
);
CREATE INDEX IF NOT EXISTS api_jobs_claim_idx
    ON recovery.api_jobs (status, available_at, created_at)
    WHERE status='queued';
CREATE UNIQUE INDEX IF NOT EXISTS api_jobs_operation_uq
    ON recovery.api_jobs (tenant_id, job_type, operation_key)
    WHERE operation_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS recovery.api_idempotency_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    endpoint text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL,
    response_status integer NOT NULL,
    response_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id, endpoint, idempotency_key),
    UNIQUE (tenant_id, id),
    CHECK (btrim(endpoint) <> ''),
    CHECK (btrim(idempotency_key) <> '' AND length(idempotency_key) <= 128),
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (response_status BETWEEN 100 AND 599)
);

DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.api_idempotency_keys;
CREATE TRIGGER prevent_immutable_mutation
    BEFORE UPDATE OR DELETE ON recovery.api_idempotency_keys
    FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();

-- Make Business Truth version lineage queryable/enforceable without trusting client-side
-- bookkeeping hidden inside JSON. Existing Phase-8 payloads already contain these fields.
ALTER TABLE recovery.business_truth_snapshots
    ADD COLUMN IF NOT EXISTS account_id uuid;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='business_truth_account_fk') THEN
        ALTER TABLE recovery.business_truth_snapshots
            ADD CONSTRAINT business_truth_account_fk
            FOREIGN KEY (tenant_id, account_id)
            REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT;
    END IF;
END $$;
ALTER TABLE recovery.business_truth_snapshots
    ADD COLUMN IF NOT EXISTS business_id text GENERATED ALWAYS AS (payload->>'business_id') STORED;
ALTER TABLE recovery.business_truth_snapshots
    ADD COLUMN IF NOT EXISTS business_version integer GENERATED ALWAYS AS ((payload->>'version')::integer) STORED;
ALTER TABLE recovery.business_truth_snapshots
    ADD COLUMN IF NOT EXISTS supersedes_version integer GENERATED ALWAYS AS (NULLIF(payload->>'supersedes_version','')::integer) STORED;
CREATE UNIQUE INDEX IF NOT EXISTS business_truth_version_uq
    ON recovery.business_truth_snapshots (tenant_id, account_id, business_id, business_version);
CREATE INDEX IF NOT EXISTS business_truth_lineage_idx
    ON recovery.business_truth_snapshots (tenant_id, account_id, business_id, business_version DESC);
CREATE OR REPLACE FUNCTION recovery_private.require_business_truth_account()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.account_id IS NULL THEN
        RAISE EXCEPTION 'new Business Truth snapshots must be bound to a Google Ads account'
            USING ERRCODE = '23502';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS require_business_truth_account ON recovery.business_truth_snapshots;
CREATE TRIGGER require_business_truth_account
    BEFORE INSERT ON recovery.business_truth_snapshots
    FOR EACH ROW EXECUTE FUNCTION recovery_private.require_business_truth_account();
CREATE UNIQUE INDEX IF NOT EXISTS business_truth_tenant_account_id_uq
    ON recovery.business_truth_snapshots (tenant_id, account_id, id);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='analysis_truth_same_account_fk') THEN
        ALTER TABLE recovery.analysis_runs
            ADD CONSTRAINT analysis_truth_same_account_fk
            FOREIGN KEY (tenant_id, account_id, truth_snapshot_id)
            REFERENCES recovery.business_truth_snapshots(tenant_id, account_id, id)
            ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;

-- User identity can only see itself. Membership rows exposed through the web DB role
-- are limited to the authenticated user's own memberships. Membership administration
-- is intentionally not part of the web API in Phase 9 and should use a separate admin
-- path/role rather than weakening these policies.
ALTER TABLE recovery.app_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.app_users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS app_user_self ON recovery.app_users;
CREATE POLICY app_user_self ON recovery.app_users
    USING (id = recovery_private.current_user_id())
    WITH CHECK (id = recovery_private.current_user_id());

ALTER TABLE recovery.tenant_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.tenant_memberships FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS membership_self ON recovery.tenant_memberships;
CREATE POLICY membership_self ON recovery.tenant_memberships
    FOR SELECT
    USING (user_id = recovery_private.current_user_id());

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['api_jobs','api_idempotency_keys']
    LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
        IF t = 'api_jobs' THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id() AND requested_by = recovery_private.current_user_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id() AND requested_by = recovery_private.current_user_id())',
                t
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id() AND user_id = recovery_private.current_user_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id() AND user_id = recovery_private.current_user_id())',
                t
            );
        END IF;
    END LOOP;
END $$;
