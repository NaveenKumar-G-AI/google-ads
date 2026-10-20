from pathlib import Path
ROOT=Path("web")

def test_billing_page_is_server_authoritative_and_contains_no_provider_secrets():
    page=(ROOT/"app/(dashboard)/dashboard/billing/page.tsx").read_text()
    api=(ROOT/"lib/recovery-api.ts").read_text()
    shell=(ROOT/"components/shell.tsx").read_text()
    assert "getBillingStatus" in page and "getBillingPlans" in page
    assert "/billing/checkout" in api and "/billing/reconcile" in api
    assert "Billing" in shell
    joined="\n".join(p.read_text(encoding="utf-8") for source in ("app", "lib", "components") for p in (ROOT/source).rglob("*.ts*") if p.is_file())
    for secret in ["RAZORPAY_KEY_SECRET","RAZORPAY_WEBHOOK_SECRET","BILLING_PLANS_JSON"]:
        assert secret not in joined
    assert "signed webhook" in page.lower()
