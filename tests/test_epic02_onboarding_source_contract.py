from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/"src/recovery/api/onboarding_service.py").read_text()
CLI=(ROOT/"src/recovery/worker/cli.py").read_text()
JOBS=(ROOT/"src/recovery/worker/google_jobs.py").read_text()

def test_reauthorization_revokes_only_same_google_user_connections():
    assert "connected_by=%s AND status='connected'" in SRC

def test_discovered_duplicate_accounts_have_deterministic_precedence():
    assert "PARTITION BY d.customer_id" in SRC
    assert "d.direct_access DESC,d.hierarchy_level ASC,c.connected_at DESC" in SRC

def test_worker_uses_oauth_aware_resolver_for_sync_and_mutation():
    assert "PostgresOAuthAwareClientResolver" in CLI
    assert "GoogleAdsSyncJobRunner(core=core, client_resolver=resolver)" in CLI
    assert "GoogleAdsNegativeMutationJobRunner(core=core, client_resolver=resolver)" in CLI
    assert "GOOGLE_OAUTH_BINDING_MISSING" in JOBS
