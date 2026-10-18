-- Launch execution hardening: public workspace creation abuse evidence.
-- Turnstile tokens/secrets are never stored. Only successful server-side verification
-- metadata is retained with the exact workspace-creation request hash.

CREATE TABLE IF NOT EXISTS recovery.workspace_creation_abuse_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    tenant_id uuid NOT NULL REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    request_sha256 char(64) NOT NULL,
    provider text NOT NULL CHECK (provider IN ('cloudflare_turnstile')),
    hostname text NOT NULL,
    action text NOT NULL,
    challenge_ts timestamptz,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(hostname)<>'' AND length(hostname)<=253),
    CHECK (btrim(action)<>'' AND length(action)<=32),
    CHECK (challenge_ts IS NULL OR challenge_ts<=occurred_at+interval '1 minute')
);
CREATE INDEX IF NOT EXISTS workspace_creation_abuse_user_idx
    ON recovery.workspace_creation_abuse_events(user_id,occurred_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS workspace_creation_abuse_tenant_idx
    ON recovery.workspace_creation_abuse_events(tenant_id,occurred_at DESC,id DESC);

ALTER TABLE recovery.workspace_creation_abuse_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.workspace_creation_abuse_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS workspace_creation_abuse_self_select ON recovery.workspace_creation_abuse_events;
CREATE POLICY workspace_creation_abuse_self_select ON recovery.workspace_creation_abuse_events FOR SELECT USING (
    user_id=recovery_private.current_user_id()
    OR recovery_private.current_platform_operator_role() IN ('platform_admin','security_auditor')
);
DROP POLICY IF EXISTS workspace_creation_abuse_self_insert ON recovery.workspace_creation_abuse_events;
CREATE POLICY workspace_creation_abuse_self_insert ON recovery.workspace_creation_abuse_events FOR INSERT WITH CHECK (
    user_id=recovery_private.current_user_id()
);
DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.workspace_creation_abuse_events;
CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.workspace_creation_abuse_events
FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();
