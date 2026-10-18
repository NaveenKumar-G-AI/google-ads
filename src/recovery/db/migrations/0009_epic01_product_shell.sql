-- Epic 1: mature product shell operational entities.
-- Portfolios, tasks, notifications and user preferences are first-class backend objects;
-- they are not reconstructed from browser state.

CREATE TABLE IF NOT EXISTS recovery.portfolios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    name text NOT NULL,
    description text,
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    CHECK (btrim(name) <> ''),
    CHECK (length(name) <= 120),
    CHECK (description IS NULL OR length(description) <= 2000)
);
CREATE UNIQUE INDEX IF NOT EXISTS portfolios_name_uq
    ON recovery.portfolios (tenant_id, lower(name));

CREATE TABLE IF NOT EXISTS recovery.portfolio_accounts (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    account_id uuid NOT NULL,
    added_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, portfolio_id, account_id),
    FOREIGN KEY (tenant_id, portfolio_id)
        REFERENCES recovery.portfolios(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS portfolio_accounts_account_idx
    ON recovery.portfolio_accounts (tenant_id, account_id, portfolio_id);

CREATE TABLE IF NOT EXISTS recovery.shell_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    account_id uuid,
    portfolio_id uuid,
    title text NOT NULL,
    description text,
    source_type text NOT NULL DEFAULT 'manual' CHECK (source_type IN ('manual','alert','recovery_case','onboarding','system')),
    source_id text,
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','blocked','done','cancelled')),
    assigned_to uuid REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    due_at timestamptz,
    created_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES recovery.google_ads_accounts(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, portfolio_id)
        REFERENCES recovery.portfolios(tenant_id, id) ON DELETE RESTRICT,
    CHECK (btrim(title) <> '' AND length(title) <= 240),
    CHECK (description IS NULL OR length(description) <= 5000),
    CHECK (source_id IS NULL OR length(source_id) <= 240),
    CHECK (account_id IS NOT NULL OR portfolio_id IS NOT NULL OR source_type IN ('manual','system','onboarding')),
    CHECK ((status='done' AND completed_at IS NOT NULL) OR (status <> 'done'))
);
CREATE INDEX IF NOT EXISTS shell_tasks_queue_idx
    ON recovery.shell_tasks (tenant_id, status, priority, due_at, created_at);
CREATE INDEX IF NOT EXISTS shell_tasks_assignee_idx
    ON recovery.shell_tasks (tenant_id, assigned_to, status, due_at);

CREATE TABLE IF NOT EXISTS recovery.user_notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('alert','approval','action','report','sync','integration','billing','assignment','system')),
    severity text NOT NULL DEFAULT 'info' CHECK (severity IN ('info','success','warning','critical')),
    title text NOT NULL,
    body text,
    href text,
    source_type text,
    source_id text,
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    CHECK (btrim(title) <> '' AND length(title) <= 240),
    CHECK (body IS NULL OR length(body) <= 5000),
    CHECK (href IS NULL OR (length(href) <= 1000 AND href LIKE '/%')),
    CHECK (source_type IS NULL OR length(source_type) <= 120),
    CHECK (source_id IS NULL OR length(source_id) <= 240)
);
CREATE INDEX IF NOT EXISTS user_notifications_inbox_idx
    ON recovery.user_notifications (tenant_id, user_id, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS recovery.user_shell_preferences (
    user_id uuid PRIMARY KEY REFERENCES recovery.app_users(id) ON DELETE CASCADE,
    density text NOT NULL DEFAULT 'standard' CHECK (density IN ('comfortable','standard','compact')),
    default_tenant_id uuid REFERENCES recovery.tenants(id) ON DELETE SET NULL,
    default_account_id uuid,
    notification_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(notification_preferences)='object')
);

-- RLS: product shell entities remain tenant isolated. Notifications/preferences are additionally user scoped.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['portfolios','portfolio_accounts','shell_tasks'] LOOP
        EXECUTE format('ALTER TABLE recovery.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE recovery.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON recovery.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON recovery.%I USING (tenant_id = recovery_private.current_tenant_id()) WITH CHECK (tenant_id = recovery_private.current_tenant_id())',
            t
        );
    END LOOP;
END $$;

ALTER TABLE recovery.user_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.user_notifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS notification_self ON recovery.user_notifications;
CREATE POLICY notification_self ON recovery.user_notifications
    USING (tenant_id = recovery_private.current_tenant_id() AND user_id = recovery_private.current_user_id())
    WITH CHECK (tenant_id = recovery_private.current_tenant_id() AND user_id = recovery_private.current_user_id());

ALTER TABLE recovery.user_shell_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.user_shell_preferences FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS shell_preferences_self ON recovery.user_shell_preferences;
CREATE POLICY shell_preferences_self ON recovery.user_shell_preferences
    USING (user_id = recovery_private.current_user_id())
    WITH CHECK (user_id = recovery_private.current_user_id());
