-- Epic 9: immutable report generations, artifacts, secure share links and event-sourced schedules.
-- A report is a snapshot of server-authoritative evidence. Generated artifacts never recompute financial truth.

CREATE TABLE IF NOT EXISTS recovery.report_generations (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    report_type text NOT NULL CHECK (report_type IN (
        'executive_recovery','waste','measurement_integrity','search_demand',
        'account_health','change_impact','monthly_client','agency_portfolio'
    )),
    template_version text NOT NULL,
    schema_version text NOT NULL,
    scope_kind text NOT NULL CHECK (scope_kind IN ('organization','portfolio','account')),
    scope_id text NOT NULL,
    period_start date,
    period_end date,
    generated_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    source_job_id uuid,
    schedule_id uuid,
    snapshot_sha256 char(64) NOT NULL,
    snapshot jsonb NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,source_job_id) REFERENCES recovery.api_jobs(tenant_id,id) ON DELETE SET NULL,
    CHECK (btrim(template_version) <> '' AND btrim(schema_version) <> ''),
    CHECK (btrim(scope_id) <> '' AND length(scope_id) <= 300),
    CHECK ((period_start IS NULL AND period_end IS NULL) OR (period_start IS NOT NULL AND period_end IS NOT NULL AND period_start <= period_end)),
    CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(snapshot)='object')
);
CREATE INDEX IF NOT EXISTS report_generations_scope_idx
    ON recovery.report_generations(tenant_id,scope_kind,scope_id,generated_at DESC);
CREATE INDEX IF NOT EXISTS report_generations_type_idx
    ON recovery.report_generations(tenant_id,report_type,generated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS report_generations_source_job_uq
    ON recovery.report_generations(tenant_id,source_job_id) WHERE source_job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS recovery.report_artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    generation_id uuid NOT NULL,
    artifact_format text NOT NULL CHECK (artifact_format IN ('pdf','csv')),
    content_type text NOT NULL,
    byte_size integer NOT NULL,
    artifact_sha256 char(64) NOT NULL,
    content bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,generation_id,artifact_format),
    FOREIGN KEY (tenant_id,generation_id) REFERENCES recovery.report_generations(tenant_id,id) ON DELETE CASCADE,
    CHECK (byte_size > 0 AND byte_size <= 10485760),
    CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.report_share_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    generation_id uuid NOT NULL,
    token_sha256 char(64) NOT NULL,
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (token_sha256),
    FOREIGN KEY (tenant_id,generation_id) REFERENCES recovery.report_generations(tenant_id,id) ON DELETE CASCADE,
    CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS report_share_generation_idx
    ON recovery.report_share_links(tenant_id,generation_id,created_at DESC);

CREATE TABLE IF NOT EXISTS recovery.report_share_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    share_link_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('created','revoked','accessed')),
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,share_link_id) REFERENCES recovery.report_share_links(tenant_id,id) ON DELETE CASCADE,
    CHECK (btrim(actor) <> '' AND length(actor) <= 300),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS report_share_events_projection_idx
    ON recovery.report_share_events(tenant_id,share_link_id,occurred_at,id);

CREATE TABLE IF NOT EXISTS recovery.report_schedule_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    schedule_id uuid NOT NULL,
    report_type text NOT NULL CHECK (report_type IN (
        'executive_recovery','waste','measurement_integrity','search_demand',
        'account_health','change_impact','monthly_client','agency_portfolio'
    )),
    scope_kind text NOT NULL CHECK (scope_kind IN ('organization','portfolio','account')),
    scope_id text NOT NULL,
    frequency text NOT NULL CHECK (frequency IN ('daily','weekly','monthly')),
    timezone_name text NOT NULL,
    hour integer NOT NULL CHECK (hour BETWEEN 0 AND 23),
    minute integer NOT NULL CHECK (minute BETWEEN 0 AND 59),
    weekday integer CHECK (weekday IS NULL OR weekday BETWEEN 0 AND 6),
    day_of_month integer CHECK (day_of_month IS NULL OR day_of_month BETWEEN 1 AND 28),
    recipients jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled boolean NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(scope_id) <> '' AND length(scope_id) <= 300),
    CHECK (btrim(timezone_name) <> '' AND length(timezone_name) <= 100),
    CHECK (jsonb_typeof(recipients)='array')
);
CREATE INDEX IF NOT EXISTS report_schedule_events_latest_idx
    ON recovery.report_schedule_events(tenant_id,schedule_id,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.report_schedule_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    schedule_id uuid NOT NULL,
    scheduled_for timestamptz NOT NULL,
    job_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,schedule_id,scheduled_for),
    FOREIGN KEY (tenant_id,job_id) REFERENCES recovery.api_jobs(tenant_id,id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recovery.report_delivery_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    generation_id uuid NOT NULL,
    schedule_id uuid,
    recipient text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('prepared','sent','failed','ambiguous','skipped_not_configured')),
    detail text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,generation_id) REFERENCES recovery.report_generations(tenant_id,id) ON DELETE CASCADE,
    CHECK (btrim(recipient) <> '' AND length(recipient) <= 320),
    CHECK (detail IS NULL OR length(detail) <= 4000)
);

ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
ALTER TABLE recovery.api_jobs ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
    'google_ads_sync','analysis_run','apply_negative','rollback_negative','semantic_shadow',
    'deployment_probe','google_ads_account_discovery','monitoring_evaluation','report_generation'
));

-- Generated versions/artifacts and all reporting events are immutable. Share expiry is fixed at creation;
-- revocation is an event, never an UPDATE that destroys history.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'report_generations','report_artifacts','report_share_links','report_share_events',
        'report_schedule_events','report_schedule_runs','report_delivery_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
        EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I',t);
        EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())',t);
    END LOOP;
END $$;
