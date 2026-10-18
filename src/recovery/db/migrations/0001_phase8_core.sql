CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS recovery;
CREATE SCHEMA IF NOT EXISTS recovery_private;

CREATE TABLE IF NOT EXISTS recovery.schema_migrations (
    version text PRIMARY KEY,
    sha256 char(64) NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION recovery_private.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('recovery.tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION recovery_private.prevent_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'table %.% is append-only; % is not permitted', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
        USING ERRCODE = '55000';
END;
$$;

CREATE TABLE IF NOT EXISTS recovery.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(slug) <> ''),
    CHECK (btrim(display_name) <> '')
);
CREATE TABLE IF NOT EXISTS recovery.google_ads_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    customer_id text NOT NULL,
    descriptive_name text NOT NULL DEFAULT '',
    currency_code char(3) NOT NULL,
    time_zone text NOT NULL,
    manager boolean NOT NULL DEFAULT false,
    account_status text NOT NULL,
    test_account boolean NOT NULL DEFAULT false,
    credential_ref text,
    credential_fingerprint char(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, customer_id),
    UNIQUE (tenant_id, id),
    CHECK (customer_id ~ '^[0-9]{10}$'),
    CHECK (currency_code ~ '^[A-Z]{3}$'),
    CHECK (btrim(time_zone) <> ''),
    CHECK (btrim(account_status) <> ''),
    CHECK (credential_fingerprint IS NULL OR credential_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.sync_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    request_id text NOT NULL,
    api_version text NOT NULL,
    sync_schema_version integer NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    currency_code char(3) NOT NULL,
    time_zone text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    failure_code text,
    failure_detail text,
    UNIQUE (tenant_id, request_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (window_start <= window_end),
    CHECK (currency_code ~ '^[A-Z]{3}$'),
    CHECK ((status = 'completed' AND completed_at IS NOT NULL) OR status <> 'completed')
);

CREATE TABLE IF NOT EXISTS recovery.sync_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    sync_run_id uuid NOT NULL,
    chunk_start date NOT NULL,
    chunk_end date NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','completed','failed')),
    payload_sha256 char(64),
    search_term_rows integer NOT NULL DEFAULT 0,
    campaign_spend_rows integer NOT NULL DEFAULT 0,
    visible_search_term_cost_micros bigint,
    comparable_campaign_cost_micros bigint,
    committed_at timestamptz,
    failure_code text,
    failure_detail text,
    UNIQUE (tenant_id, sync_run_id, chunk_start, chunk_end),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, sync_run_id)
        REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (chunk_start <= chunk_end),
    CHECK (payload_sha256 IS NULL OR payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (search_term_rows >= 0 AND campaign_spend_rows >= 0),
    CHECK (visible_search_term_cost_micros IS NULL OR visible_search_term_cost_micros >= 0),
    CHECK (comparable_campaign_cost_micros IS NULL OR comparable_campaign_cost_micros >= 0),
    CHECK (
        visible_search_term_cost_micros IS NULL OR
        comparable_campaign_cost_micros IS NULL OR
        visible_search_term_cost_micros <= comparable_campaign_cost_micros
    )
);

-- Stable identity excludes metrics so conversion-lag refreshes create versions, not new logical rows.
CREATE TABLE IF NOT EXISTS recovery.search_term_observation_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    ad_group_id text NOT NULL,
    normalized_query text NOT NULL,
    observation_date date NOT NULL,
    network text NOT NULL,
    match_source text NOT NULL,
    search_term_match_type text NOT NULL,
    targeting_status text NOT NULL,
    triggering_keyword text,
    triggering_keyword_match_type text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, account_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(normalized_query) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.search_term_observation_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    observation_key_id uuid NOT NULL,
    payload_sha256 char(64) NOT NULL,
    campaign_name text NOT NULL,
    ad_group_name text NOT NULL,
    raw_search_term text NOT NULL,
    impressions bigint NOT NULL,
    clicks bigint NOT NULL,
    cost_micros bigint NOT NULL,
    conversions numeric NOT NULL,
    conversions_value numeric NOT NULL,
    all_conversions numeric NOT NULL,
    all_conversions_value numeric NOT NULL,
    currency_code char(3) NOT NULL,
    payload jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, observation_key_id, payload_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, observation_key_id)
        REFERENCES recovery.search_term_observation_keys(tenant_id, id) ON DELETE RESTRICT,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (impressions >= 0 AND clicks >= 0 AND clicks <= impressions),
    CHECK (cost_micros >= 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS recovery.search_term_version_occurrences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    version_id uuid NOT NULL,
    sync_chunk_id uuid NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, version_id, sync_chunk_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, version_id)
        REFERENCES recovery.search_term_observation_versions(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_chunk_id)
        REFERENCES recovery.sync_chunks(tenant_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS recovery.campaign_spend_observation_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    observation_date date NOT NULL,
    network text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, account_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.campaign_spend_observation_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    observation_key_id uuid NOT NULL,
    payload_sha256 char(64) NOT NULL,
    campaign_name text NOT NULL,
    cost_micros bigint NOT NULL,
    currency_code char(3) NOT NULL,
    payload jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, observation_key_id, payload_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, observation_key_id)
        REFERENCES recovery.campaign_spend_observation_keys(tenant_id, id) ON DELETE RESTRICT,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (cost_micros >= 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS recovery.campaign_spend_version_occurrences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    version_id uuid NOT NULL,
    sync_chunk_id uuid NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, version_id, sync_chunk_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, version_id)
        REFERENCES recovery.campaign_spend_observation_versions(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_chunk_id)
        REFERENCES recovery.sync_chunks(tenant_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS recovery.keyword_inventory_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    sync_run_id uuid NOT NULL,
    payload_sha256 char(64) NOT NULL,
    positive_keyword_rows integer NOT NULL,
    negative_keyword_rows integer NOT NULL,
    payload jsonb NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, sync_run_id)
        REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (positive_keyword_rows >= 0 AND negative_keyword_rows >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.business_truth_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    truth_fingerprint char(64) NOT NULL,
    schema_version integer NOT NULL,
    payload_sha256 char(64) NOT NULL,
    payload jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, truth_fingerprint),
    UNIQUE (tenant_id, id),
    CHECK (truth_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(created_by) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.analysis_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    request_id text NOT NULL,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    truth_snapshot_id uuid NOT NULL,
    as_of date NOT NULL,
    engine_versions jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    failure_code text,
    failure_detail text,
    UNIQUE (tenant_id, request_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id)
        REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, truth_snapshot_id)
        REFERENCES recovery.business_truth_snapshots(tenant_id, id) ON DELETE RESTRICT,
    CHECK ((status = 'completed' AND completed_at IS NOT NULL) OR status <> 'completed')
);

-- Generic immutable artifact envelope preserves exact versioned engine output while
-- indexed columns support operational queries. Artifact payloads are never updated.
CREATE TABLE IF NOT EXISTS recovery.analysis_artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    analysis_run_id uuid NOT NULL,
    artifact_kind text NOT NULL CHECK (artifact_kind IN (
        'semantic_assessment','business_fit_decision','financial_finding',
        'negative_keyword_proposal','historical_baseline','run_rate_projection',
        'post_action_observation','causal_recovery_result'
    )),
    external_id text NOT NULL,
    artifact_fingerprint char(64) NOT NULL,
    schema_version integer NOT NULL,
    truth_fingerprint char(64),
    currency_code char(3),
    money_micros bigint,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, analysis_run_id, artifact_kind, external_id),
    UNIQUE (tenant_id, analysis_run_id, artifact_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, analysis_run_id)
        REFERENCES recovery.analysis_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (artifact_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (truth_fingerprint IS NULL OR truth_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    CHECK (money_micros IS NULL OR money_micros >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.proposal_decision_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    proposal_artifact_id uuid NOT NULL,
    proposal_fingerprint char(64) NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved','rejected')),
    decided_by text NOT NULL,
    decided_at timestamptz NOT NULL,
    note text,
    event_fingerprint char(64) NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (tenant_id, event_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, proposal_artifact_id)
        REFERENCES recovery.analysis_artifacts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (proposal_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(decided_by) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.mutation_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    proposal_artifact_id uuid NOT NULL,
    approval_event_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('validate_only_passed','applied','rolled_back','failed')),
    resource_name text,
    api_request_id text,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL,
    event_fingerprint char(64) NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (tenant_id, event_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, proposal_artifact_id)
        REFERENCES recovery.analysis_artifacts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, approval_event_id)
        REFERENCES recovery.proposal_decision_events(tenant_id, id) ON DELETE RESTRICT,
    CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(actor) <> ''),
    CHECK (event_type NOT IN ('applied','rolled_back') OR resource_name IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS recovery.recovery_ledger_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    analysis_run_id uuid NOT NULL,
    mutation_event_id uuid,
    ledger_fingerprint char(64) NOT NULL,
    currency_code char(3) NOT NULL,
    historical_candidate_micros bigint NOT NULL,
    projected_prevented_micros bigint NOT NULL,
    observed_post_action_query_spend_micros bigint NOT NULL,
    verified_recovery_micros bigint NOT NULL,
    causal_status text NOT NULL CHECK (causal_status IN ('not_evaluated','ineligible','inconclusive','verified')),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, analysis_run_id, ledger_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, analysis_run_id)
        REFERENCES recovery.analysis_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, mutation_event_id)
        REFERENCES recovery.mutation_events(tenant_id, id) ON DELETE RESTRICT,
    CHECK (ledger_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (currency_code ~ '^[A-Z]{3}$'),
    CHECK (
        historical_candidate_micros >= 0 AND
        projected_prevented_micros >= 0 AND
        observed_post_action_query_spend_micros >= 0 AND
        verified_recovery_micros >= 0
    ),
    CHECK (verified_recovery_micros = 0 OR causal_status = 'verified')
);

CREATE TABLE IF NOT EXISTS recovery.audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    event_type text NOT NULL,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL,
    previous_event_hash char(64),
    event_hash char(64) NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (tenant_id, event_hash),
    UNIQUE (tenant_id, id),
    CHECK (previous_event_hash IS NULL OR previous_event_hash ~ '^[0-9a-f]{64}$'),
    CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(aggregate_type) <> '' AND btrim(aggregate_id) <> ''),
    CHECK (btrim(event_type) <> '' AND btrim(actor) <> '')
);
CREATE INDEX IF NOT EXISTS audit_events_aggregate_idx
    ON recovery.audit_events (tenant_id, aggregate_type, aggregate_id, occurred_at, id);

-- Query indexes for the high-volume evidence path.
CREATE INDEX IF NOT EXISTS search_term_keys_scope_idx
    ON recovery.search_term_observation_keys
    (tenant_id, account_id, observation_date, campaign_id, ad_group_id, network);
CREATE INDEX IF NOT EXISTS search_term_keys_query_idx
    ON recovery.search_term_observation_keys (tenant_id, account_id, normalized_query);
CREATE INDEX IF NOT EXISTS campaign_spend_keys_scope_idx
    ON recovery.campaign_spend_observation_keys
    (tenant_id, account_id, observation_date, campaign_id, network);
CREATE INDEX IF NOT EXISTS analysis_artifacts_kind_idx
    ON recovery.analysis_artifacts (tenant_id, analysis_run_id, artifact_kind);

-- Append-only tables: operational state lives elsewhere. Keeping evidence immutable
-- prevents later jobs from silently rewriting the facts behind an older money claim.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'search_term_observation_keys',
        'search_term_observation_versions',
        'search_term_version_occurrences',
        'campaign_spend_observation_keys',
        'campaign_spend_observation_versions',
        'campaign_spend_version_occurrences',
        'keyword_inventory_snapshots',
        'business_truth_snapshots',
        'analysis_artifacts',
        'proposal_decision_events',
        'mutation_events',
        'recovery_ledger_entries',
        'audit_events'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I', t);
        EXECUTE format(
            'CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',
            t
        );
    END LOOP;
END $$;

-- Tenant isolation. Missing tenant context defaults to deny. FORCE makes table owners
-- subject to RLS too; superusers/BYPASSRLS roles must never be used by the web app.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'tenants','google_ads_accounts','sync_runs','sync_chunks',
        'search_term_observation_keys','search_term_observation_versions','search_term_version_occurrences',
        'campaign_spend_observation_keys','campaign_spend_observation_versions','campaign_spend_version_occurrences',
        'keyword_inventory_snapshots','business_truth_snapshots','analysis_runs','analysis_artifacts',
        'proposal_decision_events','mutation_events','recovery_ledger_entries','audit_events'
    ]
    LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
        IF t = 'tenants' THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON recovery.%I USING (id = recovery_private.current_tenant_id()) WITH CHECK (id = recovery_private.current_tenant_id())',
                t
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())',
                t
            );
        END IF;
    END LOOP;
END $$;
