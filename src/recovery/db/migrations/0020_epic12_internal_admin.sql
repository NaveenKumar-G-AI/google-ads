-- Epic 12: Internal Admin & Support Operations.
-- Platform operators use a separate authorization plane from customer tenant roles.
-- Customer evidence tables keep FORCE RLS; an operator selects one tenant context at a time.

CREATE TABLE IF NOT EXISTS recovery.platform_operator_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    operator_role text NOT NULL CHECK (operator_role IN ('support_viewer','support_engineer','platform_admin','security_auditor')),
    event_type text NOT NULL CHECK (event_type IN ('granted','revoked')),
    reason text NOT NULL,
    actor text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(reason)<>'' AND length(reason)<=2000),
    CHECK (btrim(actor)<>'' AND length(actor)<=300)
);
CREATE INDEX IF NOT EXISTS platform_operator_events_latest_idx
    ON recovery.platform_operator_events(user_id,occurred_at DESC,id DESC);

ALTER TABLE recovery.platform_operator_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_operator_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_operator_self_read ON recovery.platform_operator_events;
CREATE POLICY platform_operator_self_read ON recovery.platform_operator_events
    FOR SELECT USING (user_id=recovery_private.current_user_id());

CREATE OR REPLACE FUNCTION recovery_private.current_platform_operator_role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT CASE WHEN x.event_type='granted' THEN x.operator_role ELSE NULL END
    FROM (
        SELECT operator_role,event_type
        FROM recovery.platform_operator_events
        WHERE user_id=recovery_private.current_user_id()
        ORDER BY occurred_at DESC,id DESC
        LIMIT 1
    ) x
$$;

CREATE OR REPLACE FUNCTION recovery_private.is_platform_operator()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$ SELECT recovery_private.current_platform_operator_role() IS NOT NULL $$;

CREATE OR REPLACE FUNCTION recovery_private.platform_operator_can_write()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$ SELECT recovery_private.current_platform_operator_role() IN ('support_engineer','platform_admin') $$;

-- Minimal platform directory. It contains organization identity only, not customer evidence.
-- Operators use this to choose a tenant, then all customer diagnostics use that tenant's normal RLS context.
CREATE TABLE IF NOT EXISTS recovery.platform_tenant_directory (
    tenant_id uuid PRIMARY KEY REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    slug text NOT NULL,
    display_name text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(slug)<>'' AND btrim(display_name)<>'')
);
INSERT INTO recovery.platform_tenant_directory(tenant_id,slug,display_name)
SELECT id,slug,display_name FROM recovery.tenants
ON CONFLICT (tenant_id) DO NOTHING;

ALTER TABLE recovery.platform_tenant_directory ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_tenant_directory FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_tenant_operator_select ON recovery.platform_tenant_directory;
CREATE POLICY platform_tenant_operator_select ON recovery.platform_tenant_directory
    FOR SELECT USING (recovery_private.is_platform_operator());
DROP POLICY IF EXISTS platform_tenant_context_insert ON recovery.platform_tenant_directory;
CREATE POLICY platform_tenant_context_insert ON recovery.platform_tenant_directory
    FOR INSERT WITH CHECK (
        tenant_id=recovery_private.current_tenant_id() OR recovery_private.current_platform_operator_role()='platform_admin'
    );

CREATE OR REPLACE FUNCTION recovery_private.capture_platform_tenant_directory()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config('recovery.tenant_id', NEW.id::text, true);
    INSERT INTO recovery.platform_tenant_directory(tenant_id,slug,display_name)
    VALUES (NEW.id,NEW.slug,NEW.display_name)
    ON CONFLICT (tenant_id) DO NOTHING;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS capture_platform_tenant_directory ON recovery.tenants;
CREATE TRIGGER capture_platform_tenant_directory
AFTER INSERT ON recovery.tenants
FOR EACH ROW EXECUTE FUNCTION recovery_private.capture_platform_tenant_directory();

-- Support case anchors are immutable; lifecycle and notes are append-only events.
CREATE TABLE IF NOT EXISTS recovery.internal_support_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    title text NOT NULL,
    category text NOT NULL CHECK (category IN ('product','data','google_ads','billing','integration','security','access','other')),
    severity text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    opened_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(title)<>'' AND length(title)<=240)
);
CREATE TABLE IF NOT EXISTS recovery.internal_support_case_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    case_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('opened','note','assigned','unassigned','status_changed','closed','reopened')),
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,case_id) REFERENCES recovery.internal_support_cases(tenant_id,id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS internal_support_case_events_idx
    ON recovery.internal_support_case_events(tenant_id,case_id,occurred_at,id);

-- Safe internal remediation audit. The action itself is intentionally narrow in application code.
CREATE TABLE IF NOT EXISTS recovery.internal_remediation_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    target_type text NOT NULL CHECK (target_type IN ('job','billing','integration','account','reconciliation','data')),
    target_id text NOT NULL,
    action text NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(target_id)<>'' AND length(target_id)<=300),
    CHECK (btrim(action)<>'' AND length(action)<=120),
    CHECK (btrim(reason)<>'' AND length(reason)<=2000),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS internal_remediation_events_recent_idx
    ON recovery.internal_remediation_events(tenant_id,occurred_at DESC,id DESC);

-- Operational kill switches, not A/B experimentation. Latest event is current state; default is enabled.
CREATE TABLE IF NOT EXISTS recovery.internal_feature_control_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    feature_key text NOT NULL CHECK (feature_key IN ('google_ads_mutations','billing_mutations','scheduled_report_email')),
    enabled boolean NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(reason)<>'' AND length(reason)<=2000)
);
CREATE INDEX IF NOT EXISTS internal_feature_control_latest_idx
    ON recovery.internal_feature_control_events(tenant_id,feature_key,occurred_at DESC,id DESC);

-- Platform incident history is not tenant customer data. It is visible only to platform operators.
CREATE TABLE IF NOT EXISTS recovery.platform_incident_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('opened','update','mitigated','resolved','reopened')),
    severity text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    title text NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(title)<>'' AND length(title)<=240),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS platform_incident_events_latest_idx
    ON recovery.platform_incident_events(incident_id,occurred_at DESC,id DESC);

ALTER TABLE recovery.platform_incident_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_incident_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS platform_incident_operator_select ON recovery.platform_incident_events;
CREATE POLICY platform_incident_operator_select ON recovery.platform_incident_events
    FOR SELECT USING (recovery_private.is_platform_operator());
DROP POLICY IF EXISTS platform_incident_operator_insert ON recovery.platform_incident_events;
CREATE POLICY platform_incident_operator_insert ON recovery.platform_incident_events
    FOR INSERT WITH CHECK (recovery_private.platform_operator_can_write() AND actor_user_id=recovery_private.current_user_id());

-- Tenant-bound internal tables are visible only when an operator explicitly selects the same tenant context.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['internal_support_cases','internal_support_case_events','internal_remediation_events','internal_feature_control_events'] LOOP
    EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS internal_operator_select ON recovery.%I',t);
    EXECUTE format('CREATE POLICY internal_operator_select ON recovery.%I FOR SELECT USING (tenant_id=recovery_private.current_tenant_id() AND recovery_private.is_platform_operator())',t);
    EXECUTE format('DROP POLICY IF EXISTS internal_operator_insert ON recovery.%I',t);
    EXECUTE format('CREATE POLICY internal_operator_insert ON recovery.%I FOR INSERT WITH CHECK (tenant_id=recovery_private.current_tenant_id() AND recovery_private.platform_operator_can_write())',t);
  END LOOP;
END $$;

-- Support operators can inspect tenant users/jobs only after choosing a tenant. Existing customer policies remain intact.
DROP POLICY IF EXISTS app_user_platform_select ON recovery.app_users;
CREATE POLICY app_user_platform_select ON recovery.app_users FOR SELECT
    USING (recovery_private.is_platform_operator());

DROP POLICY IF EXISTS membership_platform_select ON recovery.tenant_memberships;
CREATE POLICY membership_platform_select ON recovery.tenant_memberships FOR SELECT
    USING (tenant_id=recovery_private.current_tenant_id() AND recovery_private.is_platform_operator());

DROP POLICY IF EXISTS api_jobs_platform_select ON recovery.api_jobs;
CREATE POLICY api_jobs_platform_select ON recovery.api_jobs FOR SELECT
    USING (tenant_id=recovery_private.current_tenant_id() AND recovery_private.is_platform_operator());
DROP POLICY IF EXISTS api_jobs_platform_insert ON recovery.api_jobs;
CREATE POLICY api_jobs_platform_insert ON recovery.api_jobs FOR INSERT
    WITH CHECK (tenant_id=recovery_private.current_tenant_id() AND recovery_private.platform_operator_can_write());

-- All internal/operator evidence is append-only.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['platform_operator_events','internal_support_cases','internal_support_case_events','internal_remediation_events','internal_feature_control_events','platform_incident_events'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
    EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
  END LOOP;
END $$;

-- Operational control reads are required by normal API/worker paths. They are non-secret
-- state and remain tenant-scoped. Writes stay restricted to platform operators.
DROP POLICY IF EXISTS internal_operator_select ON recovery.internal_feature_control_events;
CREATE POLICY internal_feature_control_tenant_read ON recovery.internal_feature_control_events
    FOR SELECT USING (tenant_id=recovery_private.current_tenant_id());
