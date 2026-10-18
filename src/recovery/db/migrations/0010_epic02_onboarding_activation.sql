-- Epic 2: onboarding and account activation.
-- Implements resumable organization setup, secure Google OAuth metadata, discovered
-- account selection, guided Business Truth draft state, and initial measurement policy.

CREATE OR REPLACE FUNCTION recovery_private.create_organization_for_current_user(
    p_display_name text,
    p_slug text
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = recovery, recovery_private, public
AS $$
DECLARE
    uid uuid := recovery_private.current_user_id();
    tid uuid;
BEGIN
    -- This function is intended for the backend database role, never Supabase's direct
    -- browser roles. The schema itself is private; keep an explicit defense-in-depth
    -- guard so accidental schema exposure cannot turn this into a self-service RPC.
    IF current_user IN ('anon','authenticated') THEN
        RAISE EXCEPTION 'organization creation is backend-only' USING ERRCODE='42501';
    END IF;
    IF uid IS NULL THEN
        RAISE EXCEPTION 'authenticated user context is required' USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM recovery.app_users WHERE id=uid AND disabled=FALSE) THEN
        RAISE EXCEPTION 'active application user is required' USING ERRCODE='42501';
    END IF;
    IF p_display_name IS NULL OR btrim(p_display_name)='' OR length(p_display_name)>160 THEN
        RAISE EXCEPTION 'invalid organization display name' USING ERRCODE='22023';
    END IF;
    IF p_slug IS NULL OR p_slug !~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$' THEN
        RAISE EXCEPTION 'invalid organization slug' USING ERRCODE='22023';
    END IF;

    INSERT INTO recovery.tenants(slug,display_name)
    VALUES (p_slug,btrim(p_display_name))
    RETURNING id INTO tid;

    INSERT INTO recovery.tenant_memberships(tenant_id,user_id,role,status)
    VALUES (tid,uid,'owner','active');

    RETURN tid;
END;
$$;
-- The database is backend-only; function itself requires a valid current-user GUC and active app user.

CREATE TABLE IF NOT EXISTS recovery.onboarding_organization_requests (
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL,
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id,idempotency_key),
    CHECK (btrim(idempotency_key)<>'' AND length(idempotency_key)<=128),
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.onboarding_progress (
    tenant_id uuid PRIMARY KEY REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    owner_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    current_step text NOT NULL DEFAULT 'billing' CHECK (current_step IN (
        'organization','billing','google_ads','account_selection','business_truth',
        'measurement','first_sync','first_analysis','first_value','complete'
    )),
    completed_steps jsonb NOT NULL DEFAULT '[]'::jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (jsonb_typeof(completed_steps)='array'),
    CHECK ((current_step='complete' AND completed_at IS NOT NULL) OR current_step <> 'complete')
);

CREATE TABLE IF NOT EXISTS recovery.google_oauth_authorization_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE CASCADE,
    state_sha256 char(64) NOT NULL UNIQUE,
    return_path text NOT NULL DEFAULT '/onboarding',
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    CHECK (state_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at),
    CHECK (return_path LIKE '/%' AND length(return_path)<=1000)
);
CREATE INDEX IF NOT EXISTS google_oauth_state_lookup_idx
    ON recovery.google_oauth_authorization_states(state_sha256,expires_at)
    WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS recovery.google_oauth_connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    connected_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    status text NOT NULL CHECK (status IN ('connected','reauthorization_required','revoked','error')),
    refresh_token_secret_ref text NOT NULL,
    refresh_token_sha256 char(64) NOT NULL,
    granted_scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    connected_at timestamptz NOT NULL DEFAULT now(),
    last_verified_at timestamptz,
    revoked_at timestamptz,
    error_code text,
    UNIQUE (tenant_id,id),
    CHECK (btrim(refresh_token_secret_ref)<>''),
    CHECK (refresh_token_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK ('https://www.googleapis.com/auth/adwords'=ANY(granted_scopes))
);
CREATE INDEX IF NOT EXISTS google_oauth_connections_active_idx
    ON recovery.google_oauth_connections(tenant_id,status,connected_at DESC);

CREATE TABLE IF NOT EXISTS recovery.google_ads_discovered_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    connection_id uuid NOT NULL,
    customer_id text NOT NULL,
    descriptive_name text NOT NULL DEFAULT '',
    currency_code char(3) NOT NULL,
    time_zone text NOT NULL,
    manager boolean NOT NULL DEFAULT false,
    account_status text NOT NULL,
    test_account boolean NOT NULL DEFAULT false,
    direct_access boolean NOT NULL DEFAULT false,
    login_customer_id text,
    hierarchy_level integer NOT NULL DEFAULT 0,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    selected_at timestamptz,
    UNIQUE (tenant_id,connection_id,customer_id),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,connection_id) REFERENCES recovery.google_oauth_connections(tenant_id,id) ON DELETE CASCADE,
    CHECK (customer_id ~ '^[0-9]{10}$'),
    CHECK (login_customer_id IS NULL OR login_customer_id ~ '^[0-9]{10}$'),
    CHECK (currency_code ~ '^[A-Z]{3}$'),
    CHECK (btrim(time_zone)<>''),
    CHECK (hierarchy_level>=0)
);
CREATE INDEX IF NOT EXISTS google_ads_discovered_accounts_selection_idx
    ON recovery.google_ads_discovered_accounts(tenant_id,connection_id,manager,descriptive_name,customer_id);

CREATE TABLE IF NOT EXISTS recovery.google_ads_account_connections (
    tenant_id uuid NOT NULL,
    account_id uuid NOT NULL,
    oauth_connection_id uuid NOT NULL,
    login_customer_id text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','reauthorization_required','revoked')),
    connected_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,account_id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,oauth_connection_id) REFERENCES recovery.google_oauth_connections(tenant_id,id) ON DELETE RESTRICT,
    CHECK (login_customer_id IS NULL OR login_customer_id ~ '^[0-9]{10}$')
);

CREATE TABLE IF NOT EXISTS recovery.onboarding_business_truth_drafts (
    tenant_id uuid NOT NULL,
    account_id uuid NOT NULL,
    draft jsonb NOT NULL,
    updated_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,account_id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(draft)='object')
);

CREATE TABLE IF NOT EXISTS recovery.account_measurement_profiles (
    tenant_id uuid NOT NULL,
    account_id uuid NOT NULL,
    conversion_lag_days integer NOT NULL,
    configured_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    configured_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,account_id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    CHECK (conversion_lag_days BETWEEN 0 AND 365)
);

-- Allow the durable worker to discover Ads accounts after an OAuth callback.
DO $$
BEGIN
    ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
    ALTER TABLE recovery.api_jobs ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
        'google_ads_sync','analysis_run','apply_negative','rollback_negative','semantic_shadow',
        'deployment_probe','google_ads_account_discovery'
    ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- RLS. OAuth state/connection objects are tenant-isolated. State additionally belongs
-- to the user who initiated the authorization request.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'onboarding_progress','google_oauth_connections','google_ads_discovered_accounts',
        'google_ads_account_connections','onboarding_business_truth_drafts','account_measurement_profiles'
    ] LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I',t);
        EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())',t);
    END LOOP;
END $$;

ALTER TABLE recovery.google_oauth_authorization_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.google_oauth_authorization_states FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS google_oauth_state_owner ON recovery.google_oauth_authorization_states;
CREATE POLICY google_oauth_state_owner ON recovery.google_oauth_authorization_states
    USING (tenant_id=recovery_private.current_tenant_id() AND user_id=recovery_private.current_user_id())
    WITH CHECK (tenant_id=recovery_private.current_tenant_id() AND user_id=recovery_private.current_user_id());


ALTER TABLE recovery.onboarding_organization_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.onboarding_organization_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS onboarding_org_request_owner ON recovery.onboarding_organization_requests;
CREATE POLICY onboarding_org_request_owner ON recovery.onboarding_organization_requests
    USING (user_id=recovery_private.current_user_id())
    WITH CHECK (user_id=recovery_private.current_user_id());
