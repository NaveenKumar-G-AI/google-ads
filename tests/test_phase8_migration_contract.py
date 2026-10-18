from importlib import resources


def migration_sql() -> str:
    return resources.files("recovery.db.migrations").joinpath("0001_phase8_core.sql").read_text(encoding="utf-8")


def test_migration_enforces_rls_and_default_tenant_context():
    sql = migration_sql().lower()
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "recovery_private.current_tenant_id" in sql
    assert "create policy tenant_isolation" in sql


def test_evidence_and_decision_tables_are_append_only():
    sql = migration_sql().lower()
    assert "prevent_immutable_mutation" in sql
    for table in (
        "search_term_observation_versions",
        "business_truth_snapshots",
        "analysis_artifacts",
        "proposal_decision_events",
        "mutation_events",
        "recovery_ledger_entries",
        "audit_events",
    ):
        assert f"'{table}'" in sql


def test_conversion_lag_version_model_is_present():
    sql = migration_sql().lower()
    assert "search_term_observation_keys" in sql
    assert "search_term_observation_versions" in sql
    assert "payload_sha256" in sql
    assert "search_term_version_occurrences" in sql


def test_database_does_not_define_raw_secret_key_columns():
    sql = migration_sql().lower()
    forbidden = (
        "developer_token text",
        "client_secret text",
        "refresh_token text",
        "private_key text",
        "service_account_json",
    )
    for token in forbidden:
        assert token not in sql
    assert "credential_ref" in sql
    assert "credential_fingerprint" in sql


def test_verified_recovery_has_its_own_column_and_is_not_alias_of_projection():
    sql = migration_sql().lower()
    assert "projected_prevented_micros bigint" in sql
    assert "verified_recovery_micros bigint" in sql
