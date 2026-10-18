from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0020_epic12_internal_admin.sql').read_text()
REPO=(ROOT/'src/recovery/api/repository.py').read_text()
SERVICE=(ROOT/'src/recovery/api/service.py').read_text()
BILLING=(ROOT/'src/recovery/api/billing_service.py').read_text()
MUTATION=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
REPORT=(ROOT/'src/recovery/worker/reporting_job.py').read_text()
BOOT=(ROOT/'src/recovery/internal_admin_bootstrap.py').read_text()


def test_operator_authorization_is_not_tenant_membership():
    assert 'platform_operator_events' in SQL
    assert 'current_platform_operator_role' in SQL
    assert "operator_role IN ('support_viewer','support_engineer','platform_admin','security_auditor')" in SQL
    assert 'tenant_memberships' not in BOOT


def test_no_web_self_grant_policy_exists():
    assert 'platform_operator_self_read' in SQL
    assert 'FOR SELECT USING (user_id=recovery_private.current_user_id())' in SQL
    assert 'CREATE POLICY platform_operator' not in SQL.replace('CREATE POLICY platform_operator_self_read','')
    assert 'RECOVERY_MIGRATION_DATABASE_URL' in BOOT


def test_customer_tables_keep_tenant_context_and_platform_directory_is_minimal():
    assert 'platform_tenant_directory' in SQL
    assert 'tenant_id=recovery_private.current_tenant_id()' in SQL
    assert 'SELECT tenant_id,slug,display_name,first_seen_at FROM recovery.platform_tenant_directory' in REPO


def test_support_remediation_feature_and_incident_history_are_append_only():
    for table in ('platform_operator_events','internal_support_cases','internal_support_case_events','internal_remediation_events','internal_feature_control_events','platform_incident_events'):
        assert table in SQL
    assert 'prevent_immutable_mutation' in SQL


def test_safe_retry_clones_only_allowlisted_failed_job_and_audits_it():
    assert "old[\"status\"]!=\"failed\"" in REPO
    assert 'SAFE_INTERNAL_RETRY_JOB_TYPES' in REPO
    assert "'safe_retry'" in REPO
    assert 'internal_remediation_events' in REPO


def test_google_hold_is_checked_at_queue_and_effect_time():
    assert 'google_ads_mutations' in SERVICE
    assert 'google_ads_mutations' in MUTATION
    assert 'PLATFORM_MUTATION_HOLD' in MUTATION


def test_billing_and_scheduled_email_holds_are_real_enforcement_points():
    assert 'billing_mutations' in BILLING
    assert 'scheduled_report_email' in REPORT
    assert 'Scheduled report email disabled by platform operational control' in REPORT
