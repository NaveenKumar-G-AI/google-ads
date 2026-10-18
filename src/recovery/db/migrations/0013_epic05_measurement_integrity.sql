-- Epic 5: Measurement Integrity.
-- Provider measurement configuration is snapshotted per completed sync. Business
-- outcome mappings are append-only user decisions tied to a Business Truth version.

CREATE TABLE IF NOT EXISTS recovery.measurement_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    payload_sha256 char(64) NOT NULL,
    conversion_action_rows integer NOT NULL,
    customer_goal_rows integer NOT NULL,
    campaign_goal_rows integer NOT NULL,
    campaign_goal_config_rows integer NOT NULL,
    conversion_lag_rows integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
      REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id)
      REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (conversion_action_rows >= 0 AND customer_goal_rows >= 0 AND campaign_goal_rows >= 0
       AND campaign_goal_config_rows >= 0 AND conversion_lag_rows >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.conversion_action_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    measurement_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    resource_name text NOT NULL,
    action_id text NOT NULL,
    name text NOT NULL,
    status text NOT NULL,
    action_type text NOT NULL,
    category text NOT NULL,
    origin text NOT NULL,
    owner_customer text,
    primary_for_goal boolean NOT NULL,
    counting_type text NOT NULL,
    click_through_lookback_days integer NOT NULL,
    view_through_lookback_days integer NOT NULL,
    attribution_model text NOT NULL,
    data_driven_model_status text NOT NULL,
    default_value numeric NOT NULL,
    default_currency_code text,
    always_use_default_value boolean NOT NULL,
    all_conversions numeric NOT NULL,
    all_conversions_value numeric NOT NULL,
    last_conversion_date date,
    last_received_request_at text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
      REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id)
      REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, measurement_snapshot_id)
      REFERENCES recovery.measurement_snapshots(tenant_id, id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(resource_name) <> '' AND btrim(action_id) <> '' AND btrim(name) <> ''),
    CHECK (click_through_lookback_days >= 0 AND view_through_lookback_days >= 0),
    CHECK (all_conversions >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.customer_conversion_goal_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    measurement_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    resource_name text NOT NULL,
    category text NOT NULL,
    origin text NOT NULL,
    biddable boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, measurement_snapshot_id) REFERENCES recovery.measurement_snapshots(tenant_id,id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.campaign_conversion_goal_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    measurement_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    campaign_name text NOT NULL,
    campaign_status text NOT NULL,
    resource_name text NOT NULL,
    category text NOT NULL,
    origin text NOT NULL,
    biddable boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, measurement_snapshot_id) REFERENCES recovery.measurement_snapshots(tenant_id,id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.campaign_goal_config_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    measurement_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    campaign_name text NOT NULL,
    campaign_status text NOT NULL,
    resource_name text NOT NULL,
    goal_config_level text NOT NULL,
    custom_conversion_goal text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, measurement_snapshot_id) REFERENCES recovery.measurement_snapshots(tenant_id,id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS recovery.conversion_lag_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    measurement_snapshot_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    conversion_action_resource text NOT NULL,
    conversion_action_name text NOT NULL,
    category text NOT NULL,
    lag_bucket text NOT NULL,
    conversions numeric NOT NULL,
    all_conversions numeric NOT NULL,
    conversions_value numeric NOT NULL,
    all_conversions_value numeric NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id) REFERENCES recovery.sync_runs(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, measurement_snapshot_id) REFERENCES recovery.measurement_snapshots(tenant_id,id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (conversions >= 0 AND all_conversions >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.conversion_action_mapping_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    conversion_action_resource text NOT NULL,
    truth_snapshot_id uuid NOT NULL,
    outcome_id text,
    mapping_status text NOT NULL CHECK (mapping_status IN ('mapped','cleared')),
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, truth_snapshot_id) REFERENCES recovery.business_truth_snapshots(tenant_id,id) ON DELETE RESTRICT,
    CHECK (btrim(conversion_action_resource) <> ''),
    CHECK ((mapping_status='mapped' AND outcome_id IS NOT NULL AND btrim(outcome_id)<>'') OR
           (mapping_status='cleared' AND outcome_id IS NULL))
);

CREATE INDEX IF NOT EXISTS measurement_snapshots_account_idx
  ON recovery.measurement_snapshots(tenant_id,account_id,created_at DESC);
CREATE INDEX IF NOT EXISTS conversion_action_observations_account_idx
  ON recovery.conversion_action_observations(tenant_id,account_id,sync_run_id,status,primary_for_goal);
CREATE INDEX IF NOT EXISTS conversion_lag_observations_account_idx
  ON recovery.conversion_lag_observations(tenant_id,account_id,sync_run_id,conversion_action_resource,lag_bucket);
CREATE INDEX IF NOT EXISTS conversion_action_mapping_events_latest_idx
  ON recovery.conversion_action_mapping_events(tenant_id,account_id,conversion_action_resource,created_at DESC,id DESC);

-- Provider evidence is immutable. Mapping events are append-only decisions.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'measurement_snapshots','conversion_action_observations','customer_conversion_goal_observations',
    'campaign_conversion_goal_observations','campaign_goal_config_observations','conversion_lag_observations',
    'conversion_action_mapping_events'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I', t);
    EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()', t);
    EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())', t);
  END LOOP;
END $$;
