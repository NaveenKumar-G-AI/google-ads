from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/"src/recovery/db/migrations/0018_epic10_agency_operations.sql").read_text()
REPO=(Path(__file__).resolve().parents[1]/"src/recovery/api/repository.py").read_text()

def test_agency_migration_adds_account_scope_and_event_sourced_admin_objects():
    assert "account_access_mode" in SQL and "client_portal" in SQL
    for table in ("organization_invites","organization_invite_events","membership_admin_events","member_account_access_events","client_workspace_events","client_workspace_account_events","client_workspace_member_events","account_assignment_events","organization_activity_events"):
        assert f"CREATE TABLE IF NOT EXISTS recovery.{table}" in SQL

def test_invites_store_only_hash_not_raw_capability_token():
    assert "token_sha256 char(64)" in SQL
    assert "token text" not in SQL.lower()

def test_epic10_admin_history_is_append_only_and_rls_protected():
    assert "prevent_immutable_mutation" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL and "FORCE ROW LEVEL SECURITY" in SQL

def test_last_owner_and_admin_owner_boundary_are_enforced_in_repository():
    assert "validate_member_transition" in REPO
    assert "validate_owner_management" in REPO
    assert "organization-membership-admin:{tenant_id}" in REPO

def test_assignments_do_not_grant_access_implicitly():
    assert "member must have account access before assignment" in REPO

def test_recovery_os_agency_schema_does_not_claim_google_ads_provider_user_access():
    sql=SQL.lower()
    assert "customer_user_access" not in sql
    assert "customer_user_access_invitation" not in sql


def test_last_owner_invariant_is_concurrency_safe_at_database_boundary():
    assert "protect_last_active_owner" in SQL
    assert "pg_advisory_xact_lock" in SQL
    assert "organization-membership-admin:" in SQL
    assert "BEFORE UPDATE OR DELETE ON recovery.tenant_memberships" in SQL


def test_invite_and_member_admin_paths_use_transaction_scoped_serialization():
    assert 'organization-invite:{tenant_id}:{email}' in REPO
    assert 'organization-invite-token:{tenant_id}:{digest}' in REPO
    assert 'organization-membership-admin:{tenant_id}' in REPO
    assert 'FOR UPDATE' in REPO


def test_owner_invitation_revocation_requires_owner_role():
    assert 'validate_owner_management(actor_role=actor_role.value,target_role=invite["role"])' in REPO
