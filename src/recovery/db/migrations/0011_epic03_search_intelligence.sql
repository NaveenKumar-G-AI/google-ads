-- Epic 3: Search Intelligence product state.
-- Query evidence itself remains in immutable Phase-8 observation/version tables.

CREATE TABLE IF NOT EXISTS recovery.search_saved_views (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    account_id uuid,
    portfolio_id uuid,
    name text NOT NULL,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id)
      REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,portfolio_id)
      REFERENCES recovery.portfolios(tenant_id,id) ON DELETE CASCADE,
    CHECK (btrim(name) <> '' AND length(name) <= 120),
    CHECK (jsonb_typeof(filters)='object'),
    CHECK (account_id IS NOT NULL OR portfolio_id IS NOT NULL),
    CHECK (NOT (account_id IS NOT NULL AND portfolio_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS search_saved_views_name_uq
    ON recovery.search_saved_views(tenant_id,user_id,COALESCE(account_id,'00000000-0000-0000-0000-000000000000'::uuid),COALESCE(portfolio_id,'00000000-0000-0000-0000-000000000000'::uuid),lower(name));
CREATE INDEX IF NOT EXISTS search_saved_views_user_idx
    ON recovery.search_saved_views(tenant_id,user_id,updated_at DESC);

ALTER TABLE recovery.search_saved_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.search_saved_views FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS search_saved_views_self ON recovery.search_saved_views;
CREATE POLICY search_saved_views_self ON recovery.search_saved_views
USING (tenant_id=recovery_private.current_tenant_id() AND user_id=recovery_private.current_user_id())
WITH CHECK (tenant_id=recovery_private.current_tenant_id() AND user_id=recovery_private.current_user_id());

-- Explorer indexes: no derived money is materialized here. These only accelerate
-- reads over immutable observation identity/version data.
CREATE INDEX IF NOT EXISTS search_term_keys_account_query_date_idx
  ON recovery.search_term_observation_keys(tenant_id,account_id,normalized_query,observation_date DESC);
CREATE INDEX IF NOT EXISTS search_term_versions_key_seen_idx
  ON recovery.search_term_observation_versions(tenant_id,observation_key_id,first_seen_at DESC);
CREATE INDEX IF NOT EXISTS search_term_occurrences_version_seen_idx
  ON recovery.search_term_version_occurrences(tenant_id,version_id,observed_at DESC);
CREATE INDEX IF NOT EXISTS analysis_runs_account_completed_idx
  ON recovery.analysis_runs(tenant_id,account_id,completed_at DESC)
  WHERE status='completed';
