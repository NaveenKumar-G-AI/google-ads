-- Epic 6: Recovery Cases + Action Center collaboration events.
-- The immutable negative-keyword proposal artifact is the stable Recovery Case identity.
-- We add only append-only human/operational case events; decisions, mutations and
-- recovery economics remain in their existing authoritative event/ledger tables.

CREATE TABLE IF NOT EXISTS recovery.recovery_case_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    proposal_artifact_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'assigned','unassigned','commented','review_requested','closed','reopened'
    )),
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    event_fingerprint char(64) NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tenant_id, event_fingerprint),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, proposal_artifact_id)
        REFERENCES recovery.analysis_artifacts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (btrim(actor) <> ''),
    CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(payload)='object')
);

CREATE INDEX IF NOT EXISTS recovery_case_events_case_idx
    ON recovery.recovery_case_events (tenant_id, proposal_artifact_id, occurred_at DESC, id DESC);

DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.recovery_case_events;
CREATE TRIGGER prevent_immutable_mutation
BEFORE UPDATE OR DELETE ON recovery.recovery_case_events
FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();

ALTER TABLE recovery.recovery_case_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.recovery_case_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON recovery.recovery_case_events;
CREATE POLICY tenant_isolation ON recovery.recovery_case_events
    USING (tenant_id = recovery_private.current_tenant_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id());
