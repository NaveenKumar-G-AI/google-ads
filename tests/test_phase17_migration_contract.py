from pathlib import Path

SQL=Path("src/recovery/db/migrations/0007_phase17_billing_onboarding.sql").read_text()

def test_billing_history_and_tenant_state_contract():
    for table in ["billing_checkout_intents","billing_webhook_events","billing_webhook_results","billing_subscription_snapshots","billing_tenant_current","billing_account_slots"]:
        assert f"recovery.{table}" in SQL
    assert "signature_verified boolean NOT NULL CHECK (signature_verified = true)" in SQL
    assert "billing_subscription_snapshots_append_only" in SQL
    assert "billing_webhook_events_append_only" in SQL
    assert "billing_webhook_results_append_only" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "provider_subscription_id text NOT NULL UNIQUE" in SQL

def test_checkout_ambiguity_state_is_explicit():
    assert "'in_flight'" in SQL and "'ambiguous'" in SQL
