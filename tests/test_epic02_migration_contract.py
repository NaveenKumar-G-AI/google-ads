from pathlib import Path

SQL=Path('src/recovery/db/migrations/0010_epic02_onboarding_activation.sql').read_text().lower()

def test_epic02_has_resumable_onboarding_and_oauth_tables():
    for name in [
        'onboarding_progress','google_oauth_authorization_states','google_oauth_connections',
        'google_ads_discovered_accounts','google_ads_account_connections',
        'onboarding_business_truth_drafts','account_measurement_profiles',
    ]:
        assert f'create table if not exists recovery.{name}' in SQL

def test_refresh_token_plaintext_column_is_forbidden():
    assert 'refresh_token_secret_ref text not null' in SQL
    assert 'refresh_token_sha256 char(64)' in SQL
    assert 'refresh_token text' not in SQL

def test_oauth_state_is_one_time_and_expires():
    assert 'state_sha256' in SQL
    assert 'consumed_at' in SQL
    assert 'expires_at' in SQL

def test_discovery_job_type_is_registered_in_queue_constraint():
    assert "'google_ads_account_discovery'" in SQL

def test_onboarding_tables_force_rls():
    assert 'force row level security' in SQL

def test_organization_creation_function_blocks_direct_browser_roles_and_requests_are_user_rls_scoped():
    sql=SQL.lower()
    assert "current_user in ('anon','authenticated')" in sql
    assert "alter table recovery.onboarding_organization_requests enable row level security" in sql
    assert "onboarding_org_request_owner" in sql
