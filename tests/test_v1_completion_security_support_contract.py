from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0024_v1_customer_security_support.sql').read_text()
REPO=(ROOT/'src/recovery/api/repository.py').read_text()
SHELL=(ROOT/'web/components/epic1/app-shell.tsx').read_text()
ANALYSIS=(ROOT/'src/recovery/worker/analysis_job.py').read_text()


def test_customer_support_and_data_requests_are_event_sourced_and_rls_protected():
    for table in ('customer_support_cases','customer_support_events','customer_data_requests','customer_data_request_events'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
        assert table in SQL
    assert 'prevent_immutable_mutation' in SQL
    assert 'FORCE ROW LEVEL SECURITY' in SQL
    assert "'organization_deletion'" in SQL and "'google_ads_disconnect'" in SQL


def test_configuration_export_explicitly_excludes_secret_material():
    assert 'security_configuration_export' in REPO
    assert 'refresh_token_secret_ref' not in REPO[REPO.index('def security_configuration_export'):REPO.index('# --- Epic 12',REPO.index('def security_configuration_export'))]
    assert 'OAuth refresh tokens/secret references' in REPO
    assert 'report share raw tokens' in REPO


def test_business_truth_and_security_are_enabled_canonical_v1_surfaces():
    assert '["Business Truth","/app/business-truth",true]' in SHELL
    assert '["Security & Data","/app/security-data",true]' in SHELL
    for rel in (
        'web/app/(dashboard)/app/business-truth/page.tsx',
        'web/app/(dashboard)/app/business-truth/versions/[snapshotId]/page.tsx',
        'web/app/(dashboard)/app/security-data/page.tsx',
        'web/app/(dashboard)/app/help/page.tsx',
        'web/app/(dashboard)/app/help/support/[caseId]/page.tsx',
    ):
        assert (ROOT/rel).exists(),rel


def test_protected_business_queries_reach_negative_keyword_safety_engine():
    assert 'truth.confirmed_protected_queries()' in ANALYSIS
    assert 'protected_queries=protected' in ANALYSIS
    page=(ROOT/'web/app/(dashboard)/app/business-truth/page.tsx').read_text()
    assert 'Protected queries / brand traffic' in page
    assert 'negative-keyword collision safety' in page


def test_destructive_customer_data_actions_are_requests_not_direct_deletes():
    page=(ROOT/'web/app/(dashboard)/app/security-data/page.tsx').read_text()
    assert 'No direct destructive browser action.' in page
    assert 'controlled deletion request' in page
    app=(ROOT/'src/recovery/api/app.py').read_text()
    assert '/security-data/requests' in app
    assert 'delete_organization' not in app
