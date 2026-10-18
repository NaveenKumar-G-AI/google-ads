-- Phase 16: immutable backend-authoritative summaries for the customer dashboard.
-- The web UI must not recompute financial truth from arbitrary client-visible rows.

CREATE TABLE IF NOT EXISTS recovery.analysis_summaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    analysis_run_id uuid NOT NULL,
    currency_code char(3) NOT NULL,
    potentially_avoidable_observed_micros bigint NOT NULL,
    visible_search_term_micros bigint NOT NULL,
    unobserved_search_micros bigint NOT NULL,
    coverage_band text NOT NULL CHECK (coverage_band IN ('high','medium','low','unknown')),
    query_count integer NOT NULL,
    irrelevant_count integer NOT NULL,
    review_required_count integer NOT NULL,
    proposal_count integer NOT NULL,
    ai_routed_count integer NOT NULL,
    baseline_fallback_count integer NOT NULL,
    semantic_interpreter text NOT NULL,
    summary_fingerprint char(64) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, analysis_run_id),
    UNIQUE (tenant_id, summary_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, analysis_run_id)
        REFERENCES recovery.analysis_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (currency_code ~ '^[A-Z]{3}$'),
    CHECK (summary_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (
        potentially_avoidable_observed_micros >= 0 AND
        visible_search_term_micros >= 0 AND
        unobserved_search_micros >= 0 AND
        query_count >= 0 AND irrelevant_count >= 0 AND review_required_count >= 0 AND
        proposal_count >= 0 AND ai_routed_count >= 0 AND baseline_fallback_count >= 0
    ),
    CHECK (potentially_avoidable_observed_micros <= visible_search_term_micros)
);

CREATE INDEX IF NOT EXISTS analysis_summaries_account_idx
    ON recovery.analysis_summaries (tenant_id, account_id, created_at DESC);

DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.analysis_summaries;
CREATE TRIGGER prevent_immutable_mutation
    BEFORE UPDATE OR DELETE ON recovery.analysis_summaries
    FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();

ALTER TABLE recovery.analysis_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.analysis_summaries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON recovery.analysis_summaries;
CREATE POLICY tenant_isolation ON recovery.analysis_summaries
    USING (tenant_id = recovery_private.current_tenant_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id());
