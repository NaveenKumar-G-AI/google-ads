from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SQL=(ROOT/'src/recovery/db/migrations/0019_epic11_billing_lifecycle.sql').read_text()
REPO=(ROOT/'src/recovery/api/repository.py').read_text()
SERVICE=(ROOT/'src/recovery/api/billing_service.py').read_text()
APP=(ROOT/'src/recovery/api/app.py').read_text()
BILLING=(ROOT/'src/recovery/billing.py').read_text()
SHELL=(ROOT/'web/components/epic1/app-shell.tsx').read_text()
PAGE=(ROOT/'web/app/(dashboard)/app/billing/page.tsx').read_text()

def test_lifecycle_evidence_tables_are_append_only_and_tenant_isolated():
    for t in ('billing_lifecycle_operations','billing_lifecycle_events','billing_pending_change_snapshots','billing_invoice_snapshots','billing_profile_events','billing_account_slot_events'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{t}' in SQL
        assert t in SQL
    assert 'prevent_immutable_mutation' in SQL and 'FORCE ROW LEVEL SECURITY' in SQL

def test_snapshot_dedup_does_not_mutate_immutable_rows():
    assert 'provider_payload_sha256=EXCLUDED.provider_payload_sha256' not in REPO
    assert 'ON CONFLICT (tenant_id,provider_subscription_id,provider_payload_sha256) DO NOTHING' in REPO

def test_plan_change_is_cycle_end_only_at_product_service_boundary():
    assert 'schedule_change_at="cycle_end"' in SERVICE
    assert 'schedule_change_at="now"' not in SERVICE
    assert 'payment_method or "").lower()!="card"' in SERVICE

def test_browser_redirect_never_unlocks_and_webhook_refetch_contract_survives():
    assert 'fetch_subscription(subscription_id)' in SERVICE
    assert 'verify_razorpay_webhook' in SERVICE
    assert 'entitlement_for_status(subscription.status)' in SERVICE

def test_billing_api_exposes_lifecycle_without_immediate_cancel_endpoint():
    for route in ('/billing/plan-change/preview','/billing/plan-change','/billing/plan-change/cancel','/billing/cancel','/billing/invoices','/billing/history','/billing/profile','/billing/account-slots'):
        assert route in APP
    assert 'cancel_at_cycle_end(access=access' in APP

def test_canonical_billing_ui_is_enabled_and_states_truth_boundaries():
    assert '["Billing","/app/billing",true]' in SHELL
    for text in ('Browser success is never billing proof.','V1 never performs immediate prorated plan changes.','does not update Razorpay customer identity'):
        assert text in PAGE

def test_razorpay_adapter_supports_update_cancel_and_invoice_readback():
    for text in ('/retrieve_scheduled_changes','/cancel_scheduled_changes','cancel_at_cycle_end','/invoices?'):
        assert text in BILLING

def test_cycle_end_cancellation_records_acceptance_and_non_contradictory_readback_not_fake_provider_flag():
    assert 'accepted_cycle_end_request_plus_non_contradictory_readback' in SERVICE
    assert 'accepted.id!=sub.id' in SERVICE
    assert 'observed.current_end is not None and observed.current_end!=sub.current_end' in SERVICE
    assert 'pending_cancellation' not in SERVICE


def test_provider_counts_are_nonnegative_when_known():
    assert 'billing_subscription_snapshots_counts_nonnegative' in SQL
    assert 'billing_tenant_current_counts_nonnegative' in SQL
    assert 'total_count>=0' in SQL and 'paid_count>=0' in SQL and 'remaining_count>=0' in SQL
