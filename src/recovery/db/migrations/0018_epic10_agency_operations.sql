-- Epic 10: organization / agency operations.
-- Existing tenant_memberships remains the authorization projection, while every
-- administrative change is recorded in immutable event history.

ALTER TABLE recovery.tenant_memberships
    ADD COLUMN IF NOT EXISTS account_access_mode text NOT NULL DEFAULT 'all_accounts'
        CHECK (account_access_mode IN ('all_accounts','selected_accounts')),
    ADD COLUMN IF NOT EXISTS client_portal boolean NOT NULL DEFAULT false;

-- Owners/admins are organization operators and must never accidentally be narrowed
-- to a client-only subset. This is also rechecked in the application layer.
CREATE OR REPLACE FUNCTION recovery_private.validate_membership_projection()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.role IN ('owner','admin') AND NEW.account_access_mode <> 'all_accounts' THEN
        RAISE EXCEPTION 'owner/admin memberships require all_accounts access' USING ERRCODE='23514';
    END IF;
    IF NEW.role IN ('owner','admin','analyst') AND NEW.client_portal THEN
        RAISE EXCEPTION 'client_portal is only valid for viewer memberships' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;
DROP TRIGGER IF EXISTS validate_membership_projection ON recovery.tenant_memberships;
CREATE TRIGGER validate_membership_projection
    BEFORE INSERT OR UPDATE ON recovery.tenant_memberships
    FOR EACH ROW EXECUTE FUNCTION recovery_private.validate_membership_projection();

CREATE TABLE IF NOT EXISTS recovery.organization_invites (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    email text NOT NULL,
    role text NOT NULL CHECK (role IN ('owner','admin','analyst','viewer')),
    account_access_mode text NOT NULL CHECK (account_access_mode IN ('all_accounts','selected_accounts')),
    client_portal boolean NOT NULL DEFAULT false,
    token_sha256 char(64) NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    invited_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (email = lower(btrim(email)) AND position('@' IN email)>1),
    CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at),
    CHECK ((role IN ('owner','admin') AND account_access_mode='all_accounts' AND client_portal=false) OR role NOT IN ('owner','admin')),
    CHECK ((client_portal=false) OR (role='viewer' AND account_access_mode='selected_accounts'))
);
CREATE INDEX IF NOT EXISTS organization_invites_tenant_email_idx ON recovery.organization_invites(tenant_id,email,created_at DESC);

CREATE TABLE IF NOT EXISTS recovery.organization_invite_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    invite_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('accepted','revoked','expired')),
    actor_user_id uuid REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,invite_id) REFERENCES recovery.organization_invites(tenant_id,id) ON DELETE RESTRICT,
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS organization_invite_events_idx ON recovery.organization_invite_events(tenant_id,invite_id,occurred_at,id);

CREATE TABLE IF NOT EXISTS recovery.membership_admin_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('joined','role_changed','access_mode_changed','client_portal_changed','disabled','reactivated')),
    role text NOT NULL CHECK (role IN ('owner','admin','analyst','viewer')),
    status text NOT NULL CHECK (status IN ('active','disabled')),
    account_access_mode text NOT NULL CHECK (account_access_mode IN ('all_accounts','selected_accounts')),
    client_portal boolean NOT NULL,
    source_invite_id uuid REFERENCES recovery.organization_invites(id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tenant_id,id),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS membership_admin_events_member_idx ON recovery.membership_admin_events(tenant_id,user_id,occurred_at,id);

CREATE TABLE IF NOT EXISTS recovery.member_account_access_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('grant','revoke')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    reason text,
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (reason IS NULL OR length(reason)<=1000)
);
CREATE INDEX IF NOT EXISTS member_account_access_latest_idx ON recovery.member_account_access_events(tenant_id,user_id,account_id,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.client_workspace_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    workspace_id uuid NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('created','updated','archived','restored')),
    name text NOT NULL,
    external_reference text,
    notes text,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    CHECK (btrim(name)<>'' AND length(name)<=160),
    CHECK (external_reference IS NULL OR length(external_reference)<=240),
    CHECK (notes IS NULL OR length(notes)<=5000)
);
CREATE INDEX IF NOT EXISTS client_workspace_events_latest_idx ON recovery.client_workspace_events(tenant_id,workspace_id,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.client_workspace_account_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    workspace_id uuid NOT NULL,
    account_id uuid NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('link','unlink')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS client_workspace_account_latest_idx ON recovery.client_workspace_account_events(tenant_id,workspace_id,account_id,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.client_workspace_member_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type IN ('grant','revoke')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS client_workspace_member_latest_idx ON recovery.client_workspace_member_events(tenant_id,workspace_id,user_id,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.account_assignment_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    responsibility text NOT NULL CHECK (responsibility IN ('lead','analyst','approver','client_contact')),
    event_type text NOT NULL CHECK (event_type IN ('assign','unassign')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    note text,
    UNIQUE (tenant_id,id),
    FOREIGN KEY (tenant_id,account_id) REFERENCES recovery.google_ads_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (note IS NULL OR length(note)<=2000)
);
CREATE INDEX IF NOT EXISTS account_assignment_latest_idx ON recovery.account_assignment_events(tenant_id,account_id,user_id,responsibility,occurred_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS recovery.organization_activity_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    event_type text NOT NULL,
    target_type text NOT NULL,
    target_id text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (tenant_id,id),
    CHECK (btrim(event_type)<>'' AND length(event_type)<=120),
    CHECK (btrim(target_type)<>'' AND length(target_type)<=120),
    CHECK (btrim(target_id)<>'' AND length(target_id)<=240),
    CHECK (jsonb_typeof(payload)='object')
);
CREATE INDEX IF NOT EXISTS organization_activity_events_idx ON recovery.organization_activity_events(tenant_id,occurred_at DESC,id DESC);

-- All Epic-10 audit/event tables are append-only.
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY[
      'organization_invites','organization_invite_events','membership_admin_events',
      'member_account_access_events','client_workspace_events','client_workspace_account_events',
      'client_workspace_member_events','account_assignment_events','organization_activity_events'
    ] LOOP
      EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
      EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
      EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY',t);
      EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY',t);
    END LOOP;
END $$;

-- These are organization-admin surfaces. Ordinary web users do not read them
-- directly from Postgres; FastAPI authorizes and returns redacted projections.
DO $$ DECLARE t text; BEGIN
    FOREACH t IN ARRAY ARRAY[
      'organization_invites','organization_invite_events','membership_admin_events',
      'member_account_access_events','client_workspace_events','client_workspace_account_events',
      'client_workspace_member_events','account_assignment_events','organization_activity_events'
    ] LOOP
      EXECUTE format('DROP POLICY IF EXISTS agency_backend_only ON recovery.%I',t);
      EXECUTE format('CREATE POLICY agency_backend_only ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())',t);
    END LOOP;
END $$;

-- Concurrency-safe ownership continuity. Application checks remain useful for clear
-- API errors, but this database invariant prevents write-skew if two Owners are
-- demoted/disabled concurrently through separate transactions.
CREATE OR REPLACE FUNCTION recovery_private.protect_last_active_owner()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    other_owner_count integer;
    removes_owner boolean := false;
BEGIN
    -- Serialize all membership UPDATE/DELETE operations for this tenant so that the
    -- count below cannot be invalidated by another concurrent admin transition.
    PERFORM pg_advisory_xact_lock(hashtextextended('organization-membership-admin:' || OLD.tenant_id::text, 0));

    IF OLD.role='owner' AND OLD.status='active' THEN
        IF TG_OP='DELETE' THEN
            removes_owner := true;
        ELSIF TG_OP='UPDATE' AND (NEW.role<>'owner' OR NEW.status<>'active') THEN
            removes_owner := true;
        END IF;
    END IF;

    IF removes_owner THEN
        SELECT count(*)::integer INTO other_owner_count
        FROM recovery.tenant_memberships
        WHERE tenant_id=OLD.tenant_id
          AND user_id<>OLD.user_id
          AND role='owner'
          AND status='active';
        IF other_owner_count < 1 THEN
            RAISE EXCEPTION 'organization must retain at least one active owner' USING ERRCODE='23514';
        END IF;
    END IF;

    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS protect_last_active_owner ON recovery.tenant_memberships;
CREATE TRIGGER protect_last_active_owner
    BEFORE UPDATE OR DELETE ON recovery.tenant_memberships
    FOR EACH ROW EXECUTE FUNCTION recovery_private.protect_last_active_owner();
