from pathlib import Path

SQL = Path("src/recovery/db/migrations/0002_phase9_api_boundary.sql").read_text(encoding="utf-8")


def test_phase9_tables_exist():
    for table in ("app_users", "tenant_memberships", "api_jobs", "api_idempotency_keys"):
        assert f"CREATE TABLE IF NOT EXISTS recovery.{table}" in SQL


def test_membership_roles_are_explicit_and_dangerous_jobs_are_durable():
    assert "'owner','admin','analyst','viewer'" in SQL
    assert "'google_ads_sync','analysis_run','apply_negative','rollback_negative'" in SQL
    assert "status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled'))" in SQL


def test_user_and_tenant_rls_contract_present():
    assert "current_user_id" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "membership_self" in SQL
    assert "tenant_isolation" in SQL


def test_idempotency_prevents_same_key_duplicates():
    assert "UNIQUE (tenant_id, user_id, endpoint, idempotency_key)" in SQL
    assert "request_sha256 char(64) NOT NULL" in SQL


def test_job_idempotency_is_scoped_to_exact_endpoint():
    assert "endpoint text NOT NULL" in SQL
    assert "UNIQUE (tenant_id, requested_by, endpoint, idempotency_key)" in SQL


def test_membership_web_policy_is_read_only():
    assert "CREATE POLICY membership_self ON recovery.tenant_memberships\n    FOR SELECT" in SQL

def test_business_truth_lineage_is_database_indexed():
    assert "business_id text GENERATED ALWAYS AS" in SQL
    assert "business_truth_version_uq" in SQL


def test_api_idempotency_records_are_append_only_and_not_expiring():
    assert "prevent_immutable_mutation ON recovery.api_idempotency_keys" in SQL
    assert "expires_at" not in SQL


def test_phase9_idempotency_has_no_reuse_expiry():
    assert "expires_at" not in SQL


def test_business_truth_is_bound_to_exact_google_ads_account():
    assert "ADD COLUMN IF NOT EXISTS account_id uuid" in SQL
    assert "business_truth_account_fk" in SQL
    assert "(tenant_id, account_id, business_id, business_version)" in SQL


def test_new_business_truth_inserts_cannot_be_unbound():
    assert "require_business_truth_account" in SQL
    assert "NEW.account_id IS NULL" in SQL


def test_mutation_jobs_have_domain_level_uniqueness():
    assert "operation_key text" in SQL
    assert "api_jobs_operation_uq" in SQL

def test_analysis_truth_same_account_is_database_constrained():
    assert "analysis_truth_same_account_fk" in SQL
    assert "FOREIGN KEY (tenant_id, account_id, truth_snapshot_id)" in SQL
