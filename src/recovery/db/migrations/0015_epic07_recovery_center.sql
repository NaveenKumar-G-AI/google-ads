-- Epic 7 — Recovery Center query hardening.
-- No new financial-truth table is introduced. The immutable Recovery Ledger remains
-- authoritative. These indexes make case-specific latest-snapshot projections safe at scale.

CREATE INDEX IF NOT EXISTS recovery_ledger_mutation_latest_idx
    ON recovery.recovery_ledger_entries (tenant_id, mutation_event_id, created_at DESC, id DESC)
    WHERE mutation_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS recovery_case_account_analysis_idx
    ON recovery.analysis_artifacts (tenant_id, analysis_run_id, created_at DESC, id DESC)
    WHERE artifact_kind='negative_keyword_proposal';

CREATE INDEX IF NOT EXISTS recovery_mutation_case_latest_idx
    ON recovery.mutation_events (tenant_id, proposal_artifact_id, occurred_at DESC, id DESC);
