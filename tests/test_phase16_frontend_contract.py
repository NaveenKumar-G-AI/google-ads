from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"web"

def test_frontend_never_contains_backend_or_provider_secret_names():
    text="\n".join(p.read_text(encoding="utf-8") for source in ("app", "lib", "components") for p in (ROOT/source).rglob("*") if p.suffix in {".ts",".tsx"})
    for secret in ("SUPABASE_SERVICE_ROLE_KEY","RECOVERY_STAGING_DATABASE_URL","GOOGLE_ADS_JSON_KEY_FILE_PATH","GEMINI_API_KEY"):
        assert secret not in text

def test_dashboard_visually_separates_candidate_and_verified_money():
    text=(ROOT/"app/(dashboard)/dashboard/page.tsx").read_text(encoding="utf-8")
    assert "Potentially avoidable observed spend" in text
    assert "Verified recovery" in text
    assert "No hidden-query extrapolation" in text

def test_frontend_uses_backend_workspace_summary_not_client_money_recalculation():
    api=(ROOT/"lib/recovery-api.ts").read_text(encoding="utf-8")
    page=(ROOT/"app/(dashboard)/dashboard/page.tsx").read_text(encoding="utf-8")
    assert "/workspace" in api
    assert "potentially_avoidable_observed_micros" in page
    assert "verified_recovery_micros" in page
