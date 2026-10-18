-- Phase 10: durable worker leases, attempts, and non-idempotent external-effect fencing.
-- A cross-tenant worker must use a dedicated backend DB role/DSN with the minimum
-- privileges necessary to claim jobs. Browser/API credentials must never use it.

ALTER TABLE recovery.api_jobs
    DROP CONSTRAINT IF EXISTS api_jobs_status_check;
ALTER TABLE recovery.api_jobs
    ADD CONSTRAINT api_jobs_status_check CHECK (status IN (
        'queued','running','succeeded','failed','cancelled','needs_reconciliation'
    ));

ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS run_token uuid;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS last_attempt_at timestamptz;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS last_error_at timestamptz;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS failure_class text;
ALTER TABLE recovery.api_jobs ADD COLUMN IF NOT EXISTS worker_version text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='api_jobs_failure_class_check'
                   AND conrelid='recovery.api_jobs'::regclass) THEN
        ALTER TABLE recovery.api_jobs
            ADD CONSTRAINT api_jobs_failure_class_check
            CHECK (failure_class IS NULL OR failure_class IN ('transient','permanent','reconciliation','lease_lost'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='api_jobs_running_lease_check'
                   AND conrelid='recovery.api_jobs'::regclass) THEN
        ALTER TABLE recovery.api_jobs
            ADD CONSTRAINT api_jobs_running_lease_check
            CHECK (
                status <> 'running'
                OR (run_token IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL)
            );
    END IF;
END $$;
ALTER TABLE recovery.api_jobs
    DROP CONSTRAINT IF EXISTS api_jobs_terminal_completed_check;
-- The Phase-9 inline constraint normally has this generated name.
DO $$
DECLARE c record;
BEGIN
    FOR c IN
        SELECT conname, pg_get_constraintdef(oid) AS def
        FROM pg_constraint
        WHERE conrelid='recovery.api_jobs'::regclass AND contype='c'
    LOOP
        IF c.def ILIKE '%completed_at%' AND c.def ILIKE '%succeeded%' AND c.def ILIKE '%cancelled%' THEN
            EXECUTE format('ALTER TABLE recovery.api_jobs DROP CONSTRAINT %I', c.conname);
        END IF;
    END LOOP;
END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='api_jobs_terminal_completed_check'
                   AND conrelid='recovery.api_jobs'::regclass) THEN
        ALTER TABLE recovery.api_jobs
            ADD CONSTRAINT api_jobs_terminal_completed_check CHECK (
                (status IN ('succeeded','failed','cancelled','needs_reconciliation') AND completed_at IS NOT NULL)
                OR status NOT IN ('succeeded','failed','cancelled','needs_reconciliation')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS api_jobs_reclaim_idx
    ON recovery.api_jobs (status, lease_expires_at, available_at, created_at)
    WHERE status IN ('queued','running');

CREATE TABLE IF NOT EXISTS recovery.job_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number >= 1),
    run_token uuid NOT NULL,
    worker_id text NOT NULL,
    claimed_at timestamptz NOT NULL,
    heartbeat_at timestamptz,
    lease_expires_at timestamptz NOT NULL,
    finished_at timestamptz,
    outcome text NOT NULL CHECK (outcome IN (
        'running','succeeded','retry_scheduled','failed','needs_reconciliation','lease_lost'
    )),
    error_code text,
    error_detail text,
    UNIQUE (tenant_id, job_id, attempt_number),
    UNIQUE (tenant_id, run_token),
    FOREIGN KEY (tenant_id, job_id) REFERENCES recovery.api_jobs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (btrim(worker_id) <> '')
);
CREATE INDEX IF NOT EXISTS job_attempts_job_idx
    ON recovery.job_attempts (tenant_id, job_id, attempt_number DESC);

CREATE TABLE IF NOT EXISTS recovery.external_effects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL,
    effect_key text NOT NULL,
    effect_kind text NOT NULL CHECK (effect_kind IN ('apply_negative','rollback_negative')),
    state text NOT NULL CHECK (state IN ('prepared','in_flight','committed','reconciled','ambiguous')),
    plan_fingerprint char(64) NOT NULL CHECK (plan_fingerprint ~ '^[0-9a-f]{64}$'),
    proposal_artifact_id uuid,
    run_token uuid,
    prepared_payload jsonb NOT NULL,
    result_payload jsonb,
    prepared_at timestamptz NOT NULL DEFAULT now(),
    in_flight_at timestamptz,
    committed_at timestamptz,
    reconciled_at timestamptz,
    resource_name text,
    google_request_id text,
    reconciliation_detail text,
    UNIQUE (tenant_id, effect_key),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, job_id) REFERENCES recovery.api_jobs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, proposal_artifact_id) REFERENCES recovery.analysis_artifacts(tenant_id, id) ON DELETE RESTRICT,
    CHECK (btrim(effect_key) <> '' AND length(effect_key) <= 240),
    CHECK (state <> 'in_flight' OR (run_token IS NOT NULL AND in_flight_at IS NOT NULL)),
    CHECK (state <> 'committed' OR committed_at IS NOT NULL),
    CHECK (state NOT IN ('reconciled','ambiguous') OR reconciled_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS external_effects_job_idx
    ON recovery.external_effects (tenant_id, job_id, state);

-- Worker tables are backend-only. RLS remains enabled for defense in depth; the worker
-- DSN must use a dedicated restricted role explicitly granted/bypassing RLS as designed.
ALTER TABLE recovery.job_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.job_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON recovery.job_attempts;
CREATE POLICY tenant_isolation ON recovery.job_attempts
    USING (tenant_id = recovery_private.current_tenant_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id());

ALTER TABLE recovery.external_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.external_effects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON recovery.external_effects;
CREATE POLICY tenant_isolation ON recovery.external_effects
    USING (tenant_id = recovery_private.current_tenant_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id());
