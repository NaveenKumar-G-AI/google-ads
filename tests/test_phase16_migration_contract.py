from importlib import resources

def sql():
    return resources.files("recovery.db.migrations").joinpath("0006_phase16_dashboard_summary.sql").read_text(encoding="utf-8").lower()

def test_dashboard_summary_is_append_only_and_rls_protected():
    text=sql()
    assert "create table if not exists recovery.analysis_summaries" in text
    assert "prevent_immutable_mutation" in text
    assert "enable row level security" in text
    assert "force row level security" in text
    assert "potentially_avoidable_observed_micros <= visible_search_term_micros" in text

def test_dashboard_summary_keeps_visible_and_unobserved_money_separate():
    text=sql()
    assert "visible_search_term_micros" in text
    assert "unobserved_search_micros" in text
    assert "verified_recovery" not in text  # verified recovery stays in the Recovery Ledger, not analysis summary
