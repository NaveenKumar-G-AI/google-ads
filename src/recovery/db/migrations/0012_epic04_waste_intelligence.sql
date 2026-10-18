-- Epic 4: Waste Intelligence evidence streams.
-- Device/daypart and actual user-location performance are persisted independently
-- from search-term observations so financial query evidence is never reconstructed
-- from incompatible segmented totals.

CREATE TABLE IF NOT EXISTS recovery.waste_dimension_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    sync_run_id uuid NOT NULL,
    chunk_start date NOT NULL,
    chunk_end date NOT NULL,
    payload_sha256 char(64) NOT NULL,
    campaign_segment_rows integer NOT NULL,
    user_location_rows integer NOT NULL,
    committed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, chunk_start, chunk_end),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, sync_run_id)
      REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    CHECK (chunk_start <= chunk_end),
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (campaign_segment_rows >= 0 AND user_location_rows >= 0)
);

CREATE TABLE IF NOT EXISTS recovery.campaign_performance_segments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    dimension_chunk_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    campaign_name text NOT NULL,
    observation_date date NOT NULL,
    network text NOT NULL,
    device text NOT NULL,
    day_of_week text NOT NULL,
    hour smallint NOT NULL,
    impressions bigint NOT NULL,
    clicks bigint NOT NULL,
    cost_micros bigint NOT NULL,
    conversions numeric NOT NULL,
    conversions_value numeric NOT NULL,
    all_conversions numeric NOT NULL,
    all_conversions_value numeric NOT NULL,
    currency_code char(3) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
      REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id)
      REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, dimension_chunk_id)
      REFERENCES recovery.waste_dimension_chunks(tenant_id, id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (hour BETWEEN 0 AND 23),
    CHECK (impressions >= 0 AND clicks >= 0 AND clicks <= impressions),
    CHECK (cost_micros >= 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS recovery.user_location_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    sync_run_id uuid NOT NULL,
    dimension_chunk_id uuid NOT NULL,
    identity_sha256 char(64) NOT NULL,
    customer_id text NOT NULL,
    campaign_id text NOT NULL,
    campaign_name text NOT NULL,
    observation_date date NOT NULL,
    network text NOT NULL,
    targeting_location boolean NOT NULL,
    country_criterion_id text NOT NULL,
    location_resource text NOT NULL,
    location_name text,
    canonical_name text,
    country_code char(2),
    target_type text,
    impressions bigint NOT NULL,
    clicks bigint NOT NULL,
    cost_micros bigint NOT NULL,
    conversions numeric NOT NULL,
    conversions_value numeric NOT NULL,
    all_conversions numeric NOT NULL,
    all_conversions_value numeric NOT NULL,
    currency_code char(3) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, sync_run_id, identity_sha256),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
      REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, sync_run_id)
      REFERENCES recovery.sync_runs(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, dimension_chunk_id)
      REFERENCES recovery.waste_dimension_chunks(tenant_id, id) ON DELETE RESTRICT,
    CHECK (identity_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(location_resource) <> ''),
    CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    CHECK (impressions >= 0 AND clicks >= 0 AND clicks <= impressions),
    CHECK (cost_micros >= 0),
    CHECK (currency_code ~ '^[A-Z]{3}$')
);

CREATE INDEX IF NOT EXISTS campaign_performance_segments_scope_idx
  ON recovery.campaign_performance_segments(tenant_id,account_id,observation_date,network,device,day_of_week,hour);
CREATE INDEX IF NOT EXISTS user_location_observations_scope_idx
  ON recovery.user_location_observations(tenant_id,account_id,observation_date,country_code,location_resource);
CREATE INDEX IF NOT EXISTS waste_dimension_chunks_run_idx
  ON recovery.waste_dimension_chunks(tenant_id,sync_run_id,chunk_start,chunk_end);

-- Evidence streams are immutable after commit.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['waste_dimension_chunks','campaign_performance_segments','user_location_observations'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I', t);
    EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()', t);
    EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id=recovery_private.current_tenant_id()) WITH CHECK (tenant_id=recovery_private.current_tenant_id())', t);
  END LOOP;
END $$;
