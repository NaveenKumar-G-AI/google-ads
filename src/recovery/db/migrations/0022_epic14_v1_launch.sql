-- Epic 14: V1 launch control plane.
-- Public launch is an append-only, platform-admin controlled state transition.
-- Customer tenant roles never inherit launch-control authority.

CREATE TABLE IF NOT EXISTS recovery.platform_launch_qualifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id text NOT NULL,
    report_sha256 char(64) NOT NULL,
    report jsonb NOT NULL,
    report_generated_at timestamptz NOT NULL,
    imported_by uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_sha256),
    CHECK (btrim(release_id)<>'' AND length(release_id)<=200),
    CHECK (report_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(report)='object')
);

CREATE TABLE IF NOT EXISTS recovery.platform_launch_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    launch_mode text NOT NULL CHECK (launch_mode IN ('closed','pilot_only','invite_only','public')),
    release_id text,
    qualification_id uuid REFERENCES recovery.platform_launch_qualifications(id) ON DELETE RESTRICT,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (release_id IS NULL OR (btrim(release_id)<>'' AND length(release_id)<=200)),
    CHECK (btrim(reason)<>'' AND length(reason)<=2000)
);
CREATE INDEX IF NOT EXISTS platform_launch_events_latest_idx
    ON recovery.platform_launch_events(occurred_at DESC,id DESC);

CREATE OR REPLACE FUNCTION recovery_private.validate_launch_qualification()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE generated timestamptz;
BEGIN
  IF NEW.report->>'schema_version' <> 'recovery-launch-gate.v1' THEN
    RAISE EXCEPTION 'launch qualification schema mismatch';
  END IF;
  IF COALESCE((NEW.report->>'qualified')::boolean,false) IS NOT TRUE THEN
    RAISE EXCEPTION 'launch qualification must be qualified';
  END IF;
  IF NEW.report->>'expected_release_id' IS DISTINCT FROM NEW.release_id THEN
    RAISE EXCEPTION 'launch qualification release does not match stored release';
  END IF;
  IF jsonb_typeof(NEW.report->'checks') <> 'array' OR jsonb_array_length(NEW.report->'checks')=0 THEN
    RAISE EXCEPTION 'launch qualification checks are required';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.report->'checks') x WHERE x->>'status' IS DISTINCT FROM 'pass') THEN
    RAISE EXCEPTION 'launch qualification contains non-pass checks';
  END IF;
  BEGIN
    generated := (NEW.report->>'generated_at')::timestamptz;
  EXCEPTION WHEN others THEN
    RAISE EXCEPTION 'launch qualification generated_at is invalid';
  END;
  IF abs(extract(epoch FROM (generated-NEW.report_generated_at))) > 1 THEN
    RAISE EXCEPTION 'launch qualification generated_at does not match report_generated_at';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS validate_launch_qualification ON recovery.platform_launch_qualifications;
CREATE TRIGGER validate_launch_qualification BEFORE INSERT ON recovery.platform_launch_qualifications
FOR EACH ROW EXECUTE FUNCTION recovery_private.validate_launch_qualification();

-- Workspace-access grants are email-hash based so pilot/invite rollout can occur before
-- a user has a Recovery OS app_users row. Only a masked hint is stored for operators.
CREATE TABLE IF NOT EXISTS recovery.platform_launch_access_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_email_sha256 char(64) NOT NULL,
    subject_hint text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN ('granted','revoked')),
    expires_at timestamptz,
    actor_user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (subject_email_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(subject_hint)<>'' AND length(subject_hint)<=320),
    CHECK (btrim(reason)<>'' AND length(reason)<=2000),
    CHECK (expires_at IS NULL OR expires_at>occurred_at)
);
CREATE INDEX IF NOT EXISTS platform_launch_access_latest_idx
    ON recovery.platform_launch_access_events(subject_email_sha256,occurred_at DESC,id DESC);

-- Platform-only history is visible to platform operators. Current launch mode itself is
-- intentionally non-secret and can be read by runtime code to fail closed on workspace creation.
ALTER TABLE recovery.platform_launch_qualifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_launch_qualifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS launch_qualification_operator_select ON recovery.platform_launch_qualifications;
CREATE POLICY launch_qualification_operator_select ON recovery.platform_launch_qualifications
    FOR SELECT USING (recovery_private.is_platform_operator());
DROP POLICY IF EXISTS launch_qualification_admin_insert ON recovery.platform_launch_qualifications;
CREATE POLICY launch_qualification_admin_insert ON recovery.platform_launch_qualifications
    FOR INSERT WITH CHECK (recovery_private.current_platform_operator_role()='platform_admin' AND imported_by=recovery_private.current_user_id());

ALTER TABLE recovery.platform_launch_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_launch_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS launch_events_runtime_select ON recovery.platform_launch_events;
CREATE POLICY launch_events_runtime_select ON recovery.platform_launch_events FOR SELECT USING (true);
DROP POLICY IF EXISTS launch_events_admin_insert ON recovery.platform_launch_events;
CREATE POLICY launch_events_admin_insert ON recovery.platform_launch_events
    FOR INSERT WITH CHECK (recovery_private.current_platform_operator_role()='platform_admin' AND actor_user_id=recovery_private.current_user_id());

ALTER TABLE recovery.platform_launch_access_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.platform_launch_access_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS launch_access_operator_or_self_select ON recovery.platform_launch_access_events;
CREATE POLICY launch_access_operator_or_self_select ON recovery.platform_launch_access_events
    FOR SELECT USING (
        recovery_private.is_platform_operator()
        OR subject_email_sha256 = COALESCE((
            SELECT encode(digest(lower(btrim(u.email)),'sha256'),'hex')
            FROM recovery.app_users u WHERE u.id=recovery_private.current_user_id()
        ),'')
    );
DROP POLICY IF EXISTS launch_access_admin_insert ON recovery.platform_launch_access_events;
CREATE POLICY launch_access_admin_insert ON recovery.platform_launch_access_events
    FOR INSERT WITH CHECK (recovery_private.current_platform_operator_role()='platform_admin' AND actor_user_id=recovery_private.current_user_id());

CREATE OR REPLACE FUNCTION recovery_private.validate_public_launch_event()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE q record;
BEGIN
  IF NEW.launch_mode='public' THEN
    IF NEW.release_id IS NULL OR NEW.qualification_id IS NULL THEN
      RAISE EXCEPTION 'public launch requires release_id and qualification_id';
    END IF;
    SELECT release_id,report,report_generated_at INTO q
    FROM recovery.platform_launch_qualifications WHERE id=NEW.qualification_id;
    IF q.release_id IS NULL OR q.release_id<>NEW.release_id THEN
      RAISE EXCEPTION 'launch qualification release does not match launch release';
    END IF;
    IF COALESCE((q.report->>'qualified')::boolean,false) IS NOT TRUE THEN
      RAISE EXCEPTION 'launch qualification is not qualified';
    END IF;
    IF q.report_generated_at < now()-interval '24 hours' OR q.report_generated_at > now()+interval '5 minutes' THEN
      RAISE EXCEPTION 'launch qualification is stale or future-dated';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS validate_public_launch_event ON recovery.platform_launch_events;
CREATE TRIGGER validate_public_launch_event BEFORE INSERT ON recovery.platform_launch_events
FOR EACH ROW EXECUTE FUNCTION recovery_private.validate_public_launch_event();

-- All launch-control history is immutable. Closing signup is a new event, never a destructive update.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['platform_launch_qualifications','platform_launch_events','platform_launch_access_events'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.%I',t);
    EXECUTE format('CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.%I FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation()',t);
  END LOOP;
END $$;

-- Legal acceptance is recorded in Recovery OS at the workspace-creation boundary. It is
-- append-only and tied to the exact published version identifiers supplied by deployment.
CREATE TABLE IF NOT EXISTS recovery.user_legal_acceptance_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES recovery.app_users(id) ON DELETE RESTRICT,
    tenant_id uuid REFERENCES recovery.tenants(id) ON DELETE RESTRICT,
    terms_url text NOT NULL,
    terms_version text NOT NULL,
    privacy_url text NOT NULL,
    privacy_version text NOT NULL,
    source text NOT NULL DEFAULT 'workspace_creation' CHECK (source IN ('workspace_creation')),
    accepted_at timestamptz NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CHECK (terms_url ~ '^https://[^[:space:]]+$' AND length(terms_url)<=2048),
    CHECK (btrim(terms_version)<>'' AND length(terms_version)<=120),
    CHECK (privacy_url ~ '^https://[^[:space:]]+$' AND length(privacy_url)<=2048),
    CHECK (btrim(privacy_version)<>'' AND length(privacy_version)<=120),
    CHECK (accepted_at<=occurred_at+interval '5 minutes')
);
CREATE INDEX IF NOT EXISTS user_legal_acceptance_recent_idx ON recovery.user_legal_acceptance_events(user_id,occurred_at DESC,id DESC);
ALTER TABLE recovery.user_legal_acceptance_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE recovery.user_legal_acceptance_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS legal_acceptance_self_select ON recovery.user_legal_acceptance_events;
CREATE POLICY legal_acceptance_self_select ON recovery.user_legal_acceptance_events FOR SELECT USING (
    user_id=recovery_private.current_user_id()
    OR recovery_private.current_platform_operator_role() IN ('platform_admin','security_auditor')
);
DROP POLICY IF EXISTS legal_acceptance_self_insert ON recovery.user_legal_acceptance_events;
CREATE POLICY legal_acceptance_self_insert ON recovery.user_legal_acceptance_events FOR INSERT WITH CHECK (user_id=recovery_private.current_user_id());
DROP TRIGGER IF EXISTS prevent_immutable_mutation ON recovery.user_legal_acceptance_events;
CREATE TRIGGER prevent_immutable_mutation BEFORE UPDATE OR DELETE ON recovery.user_legal_acceptance_events FOR EACH ROW EXECUTE FUNCTION recovery_private.prevent_immutable_mutation();
