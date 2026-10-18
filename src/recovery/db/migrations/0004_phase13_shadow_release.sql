-- Phase 13: candidate semantic shadow mode, blinded human review, gold labels,
-- evaluation evidence, and append-only semantic release registry.
-- Shadow predictions are never financial/action artifacts and are structurally barred
-- from becoming production effects.

-- Extend the durable queue for real-account shadow semantic execution.
ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
ALTER TABLE recovery.api_jobs
    ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
        'google_ads_sync','analysis_run','apply_negative','rollback_negative','semantic_shadow'
    ));

CREATE TABLE IF NOT EXISTS recovery.semantic_shadow_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    truth_snapshot_id uuid NOT NULL,
    request_id text NOT NULL,
    candidate_contract_fingerprint char(64) NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    provider_model_version text,
    thinking_level text NOT NULL,
    prompt_version text NOT NULL,
    semantic_schema_version integer NOT NULL,
    status text NOT NULL CHECK (status IN ('running','completed','failed')),
    prediction_count integer NOT NULL DEFAULT 0 CHECK (prediction_count >= 0),
    disagreement_count integer NOT NULL DEFAULT 0 CHECK (disagreement_count >= 0),
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
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
    FOREIGN KEY (tenant_id, account_id, truth_snapshot_id)
        REFERENCES recovery.business_truth_snapshots(tenant_id, account_id, id) ON DELETE RESTRICT,
    CHECK (candidate_contract_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(request_id) <> '' AND btrim(provider) <> '' AND btrim(model) <> ''),
    CHECK (btrim(thinking_level) <> '' AND btrim(prompt_version) <> ''),
    CHECK (semantic_schema_version >= 1),
    CHECK ((status='completed' AND completed_at IS NOT NULL) OR status <> 'completed')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_shadow_predictions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    shadow_run_id uuid NOT NULL,
    source_identity char(64) NOT NULL,
    raw_query text NOT NULL,
    normalized_query text NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    ad_group_id text NOT NULL,
    network text NOT NULL,
    observation_ids jsonb NOT NULL,
    truth_fingerprint char(64) NOT NULL,
    candidate_contract_fingerprint char(64) NOT NULL,
    request_prompt_fingerprint char(64) NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    provider_model_version text,
    request_id text,
    declared_confidence numeric,
    candidate_assessment jsonb NOT NULL,
    candidate_fit jsonb NOT NULL,
    baseline_assessment jsonb NOT NULL,
    baseline_fit jsonb NOT NULL,
    prediction_fingerprint char(64) NOT NULL,
    production_effect_allowed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, shadow_run_id, source_identity),
    UNIQUE (tenant_id, prediction_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, shadow_run_id)
        REFERENCES recovery.semantic_shadow_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (source_identity ~ '^[0-9a-f]{64}$'),
    CHECK (truth_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (candidate_contract_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (request_prompt_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (prediction_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (declared_confidence IS NULL OR (declared_confidence >= 0 AND declared_confidence <= 1)),
    CHECK (production_effect_allowed = false),
    CHECK (btrim(raw_query) <> '' AND btrim(normalized_query) <> ''),
    CHECK (jsonb_typeof(observation_ids)='array' AND jsonb_array_length(observation_ids) >= 1)
);
CREATE INDEX IF NOT EXISTS semantic_shadow_predictions_query_idx
    ON recovery.semantic_shadow_predictions (tenant_id, truth_fingerprint, normalized_query);

-- Reviews are intentionally NOT FK-linked to a candidate prediction. A blinded review
-- workflow can fetch raw query + Business Truth directly without exposing model output.
CREATE TABLE IF NOT EXISTS recovery.semantic_human_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    truth_snapshot_id uuid NOT NULL,
    case_key char(64) NOT NULL,
    raw_query text NOT NULL,
    truth_fingerprint char(64) NOT NULL,
    reviewer_actor text NOT NULL,
    review_version integer NOT NULL DEFAULT 1 CHECK (review_version >= 1),
    supersedes_id uuid,
    expected_disposition text NOT NULL CHECK (expected_disposition IN ('relevant','irrelevant','conditional','unknown')),
    expected_status text NOT NULL CHECK (expected_status IN ('resolved','ambiguous','insufficient')),
    language_code text NOT NULL,
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes text NOT NULL DEFAULT '',
    blinded_to_candidate boolean NOT NULL,
    adjudicator boolean NOT NULL DEFAULT false,
    review_fingerprint char(64) NOT NULL,
    submitted_at timestamptz NOT NULL,
    UNIQUE (tenant_id, review_fingerprint),
    UNIQUE (tenant_id, case_key, reviewer_actor, review_version),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, supersedes_id)
        REFERENCES recovery.semantic_human_reviews(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, account_id, truth_snapshot_id)
        REFERENCES recovery.business_truth_snapshots(tenant_id, account_id, id) ON DELETE RESTRICT,
    CHECK (case_key ~ '^[0-9a-f]{64}$'),
    CHECK (truth_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (review_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(raw_query) <> '' AND btrim(reviewer_actor) <> '' AND btrim(language_code) <> ''),
    CHECK (jsonb_typeof(tags)='array')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_gold_case_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    truth_snapshot_id uuid NOT NULL,
    case_key char(64) NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    supersedes_id uuid,
    case_id text NOT NULL,
    identity_fingerprint char(64) NOT NULL,
    case_fingerprint char(64) NOT NULL,
    split text NOT NULL CHECK (split IN ('calibration','test')),
    label_source text NOT NULL CHECK (label_source IN ('double_review','adjudicated','single_review')),
    reviewer_count integer NOT NULL CHECK (reviewer_count >= 1),
    blinded_release_eligible boolean NOT NULL,
    payload jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, case_key, version),
    UNIQUE (tenant_id, case_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, account_id, truth_snapshot_id)
        REFERENCES recovery.business_truth_snapshots(tenant_id, account_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, supersedes_id)
        REFERENCES recovery.semantic_gold_case_versions(tenant_id, id) ON DELETE RESTRICT,
    CHECK (case_key ~ '^[0-9a-f]{64}$'),
    CHECK (identity_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (case_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(case_id) <> '' AND btrim(created_by) <> ''),
    CHECK (NOT blinded_release_eligible OR (reviewer_count >= 2 AND label_source IN ('double_review','adjudicated')))
);

CREATE TABLE IF NOT EXISTS recovery.semantic_dataset_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    dataset_fingerprint char(64) NOT NULL,
    split_salt_fingerprint char(64) NOT NULL,
    case_version_ids jsonb NOT NULL,
    case_count integer NOT NULL CHECK (case_count >= 1),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, dataset_fingerprint),
    UNIQUE (tenant_id, id),
    CHECK (dataset_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (split_salt_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(case_version_ids)='array' AND jsonb_array_length(case_version_ids)=case_count),
    CHECK (btrim(created_by) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_evaluation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    dataset_snapshot_id uuid NOT NULL,
    candidate_fingerprint char(64) NOT NULL,
    candidate_contract_fingerprint char(64) NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    provider_model_version text,
    thinking_level text NOT NULL,
    prompt_version text NOT NULL,
    semantic_schema_version integer NOT NULL,
    release_policy_fingerprint char(64) NOT NULL,
    selected_confidence_threshold numeric,
    gate_passed boolean NOT NULL,
    evaluation_report_fingerprint char(64) NOT NULL,
    payload jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, evaluation_report_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, dataset_snapshot_id)
        REFERENCES recovery.semantic_dataset_snapshots(tenant_id, id) ON DELETE RESTRICT,
    CHECK (candidate_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (candidate_contract_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (release_policy_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (evaluation_report_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (selected_confidence_threshold IS NULL OR (selected_confidence_threshold >= 0 AND selected_confidence_threshold <= 1)),
    CHECK (NOT gate_passed OR (provider_model_version IS NOT NULL AND selected_confidence_threshold IS NOT NULL)),
    CHECK (btrim(provider) <> '' AND btrim(model) <> '' AND btrim(created_by) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_release_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid,
    scope_kind text NOT NULL CHECK (scope_kind IN ('tenant','account')),
    evaluation_run_id uuid NOT NULL,
    release_fingerprint char(64) NOT NULL,
    candidate_identity_fingerprint char(64) NOT NULL,
    selected_confidence_threshold numeric NOT NULL CHECK (selected_confidence_threshold >= 0 AND selected_confidence_threshold <= 1),
    approved_languages text[] NOT NULL,
    payload jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, release_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, evaluation_run_id)
        REFERENCES recovery.semantic_evaluation_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (release_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (candidate_identity_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (cardinality(approved_languages) >= 1),
    CHECK ((scope_kind='account' AND account_id IS NOT NULL) OR (scope_kind='tenant' AND account_id IS NULL)),
    CHECK (btrim(created_by) <> '')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_release_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    release_definition_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('activate','deactivate','revoke')),
    actor text NOT NULL,
    reason text,
    event_fingerprint char(64) NOT NULL,
    occurred_at timestamptz NOT NULL,
    UNIQUE (tenant_id, event_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, release_definition_id)
        REFERENCES recovery.semantic_release_definitions(tenant_id, id) ON DELETE RESTRICT,
    CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(actor) <> ''),
    CHECK (event_type <> 'revoke' OR (reason IS NOT NULL AND btrim(reason) <> ''))
);

-- Evidence/release registry is append-only. Shadow run operational status is the only
-- mutable Phase-13 table.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'semantic_shadow_predictions','semantic_human_reviews','semantic_gold_case_versions',
        'semantic_dataset_snapshots','semantic_evaluation_runs','semantic_release_definitions',
        'semantic_release_events'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I', t);
        EXECUTE format(
            'CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',
            t
        );
    END LOOP;
END $$;

-- Phase-13 tenant isolation. Review data remains tenant-private; release registry is
-- accessed by backend roles and cannot be written from a browser DB connection.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'semantic_shadow_runs','semantic_shadow_predictions','semantic_human_reviews',
        'semantic_gold_case_versions','semantic_dataset_snapshots','semantic_evaluation_runs',
        'semantic_release_definitions','semantic_release_events'
    ]
    LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())',
            t
        );
    END LOOP;
END $$;

-- Exact dataset membership gets relational foreign keys; the JSON list above remains a
-- canonical manifest but cannot be the only referential integrity mechanism.
CREATE TABLE IF NOT EXISTS recovery.semantic_dataset_case_members (
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    dataset_snapshot_id uuid NOT NULL,
    gold_case_version_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (tenant_id, dataset_snapshot_id, gold_case_version_id),
    UNIQUE (tenant_id, dataset_snapshot_id, ordinal),
    FOREIGN KEY (tenant_id, dataset_snapshot_id)
        REFERENCES recovery.semantic_dataset_snapshots(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, gold_case_version_id)
        REFERENCES recovery.semantic_gold_case_versions(tenant_id, id) ON DELETE RESTRICT
);
DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.semantic_dataset_case_members;
CREATE TRIGGER prevent_immutable_mutation
    BEFORE UPDATE OR DELETE ON recovery.semantic_dataset_case_members
    FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();
ALTER TABLE recovery.semantic_dataset_case_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.semantic_dataset_case_members FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON recovery.semantic_dataset_case_members;
CREATE POLICY tenant_isolation ON recovery.semantic_dataset_case_members
    USING (tenant_id = recovery_private.current_tenant_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id());

-- Release definitions can only reference evaluations that actually passed.
CREATE OR REPLACE FUNCTION recovery_private.require_passing_semantic_evaluation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE ok boolean;
DECLARE threshold numeric;
BEGIN
    SELECT gate_passed, selected_confidence_threshold INTO ok, threshold
    FROM recovery.semantic_evaluation_runs
    WHERE tenant_id=NEW.tenant_id AND id=NEW.evaluation_run_id;
    IF ok IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'semantic release requires a passing evaluation'
            USING ERRCODE='23514';
    END IF;
    IF threshold IS DISTINCT FROM NEW.selected_confidence_threshold THEN
        RAISE EXCEPTION 'release confidence threshold must equal evaluated threshold'
            USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS require_passing_semantic_evaluation ON recovery.semantic_release_definitions;
CREATE TRIGGER require_passing_semantic_evaluation
    BEFORE INSERT ON recovery.semantic_release_definitions
    FOR EACH ROW EXECUTE FUNCTION recovery_private.require_passing_semantic_evaluation();

ALTER TABLE recovery.semantic_release_events
    ADD COLUMN IF NOT EXISTS recorded_at timestamptz NOT NULL DEFAULT now();

-- Enforce release state transitions in PostgreSQL too. Application checks are not the
-- only line of defense against accidental reactivation after revocation.
CREATE OR REPLACE FUNCTION recovery_private.validate_semantic_release_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE prior text;
DECLARE was_revoked boolean;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('semantic-release:' || NEW.tenant_id::text || ':' || NEW.release_definition_id::text, 0));
    SELECT EXISTS(
        SELECT 1 FROM recovery.semantic_release_events
        WHERE tenant_id=NEW.tenant_id AND release_definition_id=NEW.release_definition_id AND event_type='revoke'
    ) INTO was_revoked;
    IF was_revoked THEN
        RAISE EXCEPTION 'revoked semantic release cannot transition again' USING ERRCODE='55000';
    END IF;
    SELECT event_type INTO prior
    FROM recovery.semantic_release_events
    WHERE tenant_id=NEW.tenant_id AND release_definition_id=NEW.release_definition_id
    ORDER BY recorded_at DESC, id DESC LIMIT 1;
    IF NEW.event_type='activate' AND prior='activate' THEN
        RAISE EXCEPTION 'semantic release already active' USING ERRCODE='55000';
    END IF;
    IF NEW.event_type='deactivate' AND prior IS DISTINCT FROM 'activate' THEN
        RAISE EXCEPTION 'semantic release is not active' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS validate_semantic_release_transition ON recovery.semantic_release_events;
CREATE TRIGGER validate_semantic_release_transition
    BEFORE INSERT ON recovery.semantic_release_events
    FOR EACH ROW EXECUTE FUNCTION recovery_private.validate_semantic_release_transition();
