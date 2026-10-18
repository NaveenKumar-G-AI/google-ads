-- Epic 8: Monitoring & Alerts.
-- Provider observations, policy changes, alert generations, and alert transitions are append-only.
-- Current alert/policy state is projected from immutable events; no mutable alert status table is authoritative.

CREATE TABLE IF NOT EXISTS recovery.monitoring_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    payload_sha256 char(64) NOT NULL,
    campaign_health_rows integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,sync_run_id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE CASCADE,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (campaign_health_rows >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.campaign_health_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    monitoring_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    campaign_name text NOT NULL,
    advertising_channel_type text NOT NULL,
    status text NOT NULL,
    primary_status text NOT NULL,
    primary_status_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,sync_run_id,identity_sha256),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,monitoring_snapshot_id) REFERENCES recovery.monitoring_snapshots(tenant_id,id) ON DELETE CASCADE,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (customer_id ~ '^[0-9]+$' AND campaign_id ~ '^[0-9]+$'),
    CHECK (btrim(campaign_name) <> ''),
    CHECK (jsonb_typeof(primary_status_reasons)='array')
);
CREATE INDEX IF NOT EXISTS campaign_health_latest_idx
    ON recovery.campaign_health_observations(tenant_id,account_id,created_at DESC,campaign_id);

CREATE TABLE IF NOT EXISTS recovery.monitor_policy_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid,
    monitor_type text NOT NULL CHECK (monitor_type IN (
        'data_freshness','measurement_integrity','job_health','campaign_serving',
        'spend_anomaly','conversion_drop','reconciliation','query_recurrence'
    )),
    enabled boolean NOT NULL,
    severity_override text CHECK (severity_override IS NULL OR severity_override IN ('info','warning','critical')),
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(config)='object'),
    CHECK (btrim(actor) <> '' AND length(actor) <= 300)
);
CREATE INDEX IF NOT EXISTS monitor_policy_events_latest_idx
    ON recovery.monitor_policy_events(tenant_id,account_id,monitor_type,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.monitor_alert_instances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    monitor_type text NOT NULL,
    source_key text NOT NULL,
    alert_fingerprint char(64) NOT NULL,
    generation integer NOT NULL,
    initial_severity text NOT NULL CHECK (initial_severity IN ('info','warning','critical')),
    title text NOT NULL,
    first_evidence jsonb NOT NULL,
    opened_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,account_id,alert_fingerprint,generation),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    CHECK (alert_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (generation >= 1),
    CHECK (btrim(source_key) <> '' AND length(source_key) <= 300),
    CHECK (btrim(title) <> '' AND length(title) <= 300),
    CHECK (jsonb_typeof(first_evidence)='object')
);
CREATE INDEX IF NOT EXISTS monitor_alert_instances_scope_idx
    ON recovery.monitor_alert_instances(tenant_id,account_id,monitor_type,opened_at DESC);

CREATE TABLE IF NOT EXISTS recovery.monitor_alert_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    alert_instance_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'opened','observed','acknowledged','assigned','unassigned','resolved',
        'auto_resolved','dismissed','reopened','commented'
    )),
    severity text CHECK (severity IS NULL OR severity IN ('info','warning','critical')),
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,alert_instance_id) REFERENCES recovery.monitor_alert_instances(tenant_id,id) ON DELETE CASCADE,
    CHECK (btrim(actor) <> '' AND length(actor) <= 300),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS monitor_alert_events_projection_idx
    ON recovery.monitor_alert_events(tenant_id,alert_instance_id,occurred_at,id);

-- Optional supplementary audit evidence. ChangeEvent may be delayed and is never immediate mutation truth.
CREATE TABLE IF NOT EXISTS recovery.google_change_event_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    event_fingerprint char(64) NOT NULL,
    change_date_time timestamptz NOT NULL,
    change_resource_type text NOT NULL,
    change_resource_name text NOT NULL,
    client_type text NOT NULL,
    user_email text,
    changed_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    UNIQUE (tenant_id,account_id,event_fingerprint),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(changed_fields)='array')
);
CREATE INDEX IF NOT EXISTS google_change_events_recent_idx
    ON recovery.google_change_event_observations(tenant_id,account_id,change_date_time DESC);

-- Durable monitor evaluation runs after a successful sync or an authorized manual evaluation.
ALTER TABLE recovery.api_jobs DROP CONSTRAINT IF EXISTS api_jobs_job_type_check;
ALTER TABLE recovery.api_jobs ADD CONSTRAINT api_jobs_job_type_check CHECK (job_type IN (
    'google_ads_sync','analysis_run','apply_negative','rollback_negative','semantic_shadow',
    'deployment_probe','google_ads_account_discovery','monitoring_evaluation'
));

-- Every monitoring fact/change is immutable. State is a projection, never overwritten history.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'monitoring_snapshots','campaign_health_observations','monitor_policy_events',
        'monitor_alert_instances','monitor_alert_events','google_change_event_observations'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
        EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I',t);
        EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())',t);
    END LOOP;
END $$;
