-- Phase 14: production semantic routing evidence, release safety state, and drift monitoring.
-- Production AI remains fail-closed: only exact active healthy releases may supply semantics.

CREATE TABLE IF NOT EXISTS recovery.semantic_release_safety_state (
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    release_definition_id uuid NOT NULL,
    state text NOT NULL CHECK (state IN ('healthy','tripped')),
    trip_reason text,
    tripped_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, release_definition_id),
    FOREIGN KEY (tenant_id, release_definition_id)
        REFERENCES recovery.semantic_release_definitions(tenant_id, id) ON DELETE RESTRICT,
    CHECK ((state='healthy' AND trip_reason IS NULL AND tripped_at IS NULL)
        OR (state='tripped' AND trip_reason IS NOT NULL AND btrim(trip_reason)<>'' AND tripped_at IS NOT NULL))
);

CREATE OR REPLACE FUNCTION recovery_private.prevent_semantic_safety_untrip()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state='tripped' AND NEW.state<>'tripped' THEN
        RAISE EXCEPTION 'tripped semantic release is terminal; create a new release'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS prevent_semantic_safety_untrip ON recovery.semantic_release_safety_state;
CREATE TRIGGER prevent_semantic_safety_untrip
    BEFORE UPDATE ON recovery.semantic_release_safety_state
    FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_semantic_safety_untrip();

CREATE TABLE IF NOT EXISTS recovery.semantic_production_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    release_definition_id uuid,
    source_identity char(64) NOT NULL,
    raw_query text NOT NULL,
    truth_fingerprint char(64) NOT NULL,
    route_source text NOT NULL CHECK (route_source IN ('released_ai','baseline')),
    fallback_reason text,
    release_fingerprint char(64),
    declared_confidence numeric,
    provider_model_version text,
    language_code text,
    final_assessment jsonb NOT NULL,
    final_fit jsonb NOT NULL,
    baseline_assessment jsonb NOT NULL,
    baseline_fit jsonb NOT NULL,
    candidate_assessment jsonb,
    candidate_fit jsonb,
    decision_fingerprint char(64) NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (tenant_id, analysis_run_id, source_identity),
    UNIQUE (tenant_id, decision_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, analysis_run_id)
        REFERENCES recovery.analysis_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, release_definition_id)
        REFERENCES recovery.semantic_release_definitions(tenant_id, id) ON DELETE RESTRICT,
    CHECK (source_identity ~ '^[0-9a-f]{64}$'),
    CHECK (truth_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (decision_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (release_fingerprint IS NULL OR release_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (declared_confidence IS NULL OR (declared_confidence>=0 AND declared_confidence<=1)),
    CHECK (btrim(raw_query)<>''),
    CHECK ((route_source='released_ai' AND fallback_reason IS NULL AND release_definition_id IS NOT NULL AND release_fingerprint IS NOT NULL AND candidate_assessment IS NOT NULL AND candidate_fit IS NOT NULL)
        OR (route_source='baseline' AND fallback_reason IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS semantic_production_decisions_release_idx
    ON recovery.semantic_production_decisions (tenant_id, release_fingerprint, created_at);

CREATE TABLE IF NOT EXISTS recovery.semantic_production_review_links (
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    production_decision_id uuid NOT NULL,
    gold_case_version_id uuid NOT NULL,
    linked_by text NOT NULL,
    linked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, production_decision_id),
    FOREIGN KEY (tenant_id, production_decision_id)
        REFERENCES recovery.semantic_production_decisions(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, gold_case_version_id)
        REFERENCES recovery.semantic_gold_case_versions(tenant_id, id) ON DELETE RESTRICT,
    CHECK (btrim(linked_by)<>'')
);

CREATE TABLE IF NOT EXISTS recovery.semantic_drift_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    release_definition_id uuid NOT NULL,
    release_fingerprint char(64) NOT NULL,
    policy_fingerprint char(64) NOT NULL,
    evaluation_fingerprint char(64) NOT NULL,
    reviewed_cases integer NOT NULL CHECK (reviewed_cases>=0),
    actionable_irrelevant_cases integer NOT NULL CHECK (actionable_irrelevant_cases>=0),
    unsafe_false_exclusions integer NOT NULL CHECK (unsafe_false_exclusions>=0),
    wilson_upper_unsafe_rate numeric,
    sufficient_evidence boolean NOT NULL,
    tripped boolean NOT NULL,
    reasons jsonb NOT NULL,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, evaluation_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, release_definition_id)
        REFERENCES recovery.semantic_release_definitions(tenant_id, id) ON DELETE RESTRICT,
    CHECK (release_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (evaluation_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (wilson_upper_unsafe_rate IS NULL OR (wilson_upper_unsafe_rate>=0 AND wilson_upper_unsafe_rate<=1)),
    CHECK (jsonb_typeof(reasons)='array')
);

-- Production semantic evidence and drift evaluations are append-only.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'semantic_production_decisions','semantic_production_review_links','semantic_drift_evaluations'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I', t);
        EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()', t);
    END LOOP;
END $$;

-- Tenant isolation on all Phase-14 tables.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'semantic_release_safety_state','semantic_production_decisions',
        'semantic_production_review_links','semantic_drift_evaluations'
    ] LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())', t);
    END LOOP;
END $$;

-- Once a release is tripped it cannot be activated again. A corrected candidate must
-- become a new immutable release definition and re-earn promotion.
CREATE OR REPLACE FUNCTION recovery_private.block_activation_of_tripped_release()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE safety text;
BEGIN
    IF NEW.event_type='activate' THEN
        SELECT state INTO safety FROM recovery.semantic_release_safety_state
        WHERE tenant_id=NEW.tenant_id AND release_definition_id=NEW.release_definition_id;
        IF safety='tripped' THEN
            RAISE EXCEPTION 'tripped semantic release cannot be activated again' USING ERRCODE='55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS block_activation_of_tripped_release ON recovery.semantic_release_events;
CREATE TRIGGER block_activation_of_tripped_release
    BEFORE INSERT ON recovery.semantic_release_events
    FOR EACH ROW EXECUTE FUNCTION recovery_private.block_activation_of_tripped_release();

-- At most one release may be active per exact scope. Account scope and tenant scope may
-- coexist; production routing deliberately prefers the more-specific account release.
CREATE OR REPLACE FUNCTION recovery_private.prevent_multiple_active_semantic_releases()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_scope text;
DECLARE target_account uuid;
DECLARE conflict_exists boolean;
BEGIN
    IF NEW.event_type <> 'activate' THEN RETURN NEW; END IF;
    SELECT scope_kind, account_id INTO target_scope, target_account
    FROM recovery.semantic_release_definitions
    WHERE tenant_id=NEW.tenant_id AND id=NEW.release_definition_id;

    SELECT EXISTS(
        SELECT 1
        FROM recovery.semantic_release_definitions d
        JOIN LATERAL (
            SELECT e.event_type
            FROM recovery.semantic_release_events e
            WHERE e.tenant_id=d.tenant_id AND e.release_definition_id=d.id
            ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1
        ) last_event ON true
        WHERE d.tenant_id=NEW.tenant_id
          AND d.id<>NEW.release_definition_id
          AND d.scope_kind=target_scope
          AND d.account_id IS NOT DISTINCT FROM target_account
          AND last_event.event_type='activate'
    ) INTO conflict_exists;
    IF conflict_exists THEN
        RAISE EXCEPTION 'another semantic release is already active for this exact scope' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS prevent_multiple_active_semantic_releases ON recovery.semantic_release_events;
CREATE TRIGGER prevent_multiple_active_semantic_releases
    BEFORE INSERT ON recovery.semantic_release_events
    FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_multiple_active_semantic_releases();
