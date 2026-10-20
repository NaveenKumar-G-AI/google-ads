from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/"web"

def read(rel): return (ROOT/rel).read_text(encoding="utf-8")

def test_root_is_public_marketing_and_authenticated_product_remains_at_app():
    homepage = read("app/page.tsx")
    assert "MarketingHome" in homepage
    assert "redirect(" not in homepage
    product = read("app/(dashboard)/app/page.tsx")
    assert "resolveAppContext" in product
    assert "AppShell" in product

def test_canonical_shell_has_org_portfolio_account_context_and_mature_navigation():
    shell=read("components/epic1/app-shell.tsx")
    switcher=read("components/epic1/context-switcher.tsx")
    for section in ("Intelligence","Operations","Proof","Organization"):
        assert section in shell
    for label in ("Organization","Portfolio","Account"):
        assert label in switcher

def test_command_center_does_not_merge_candidate_and_verified_money():
    page=read("app/(dashboard)/app/page.tsx")
    money=read("components/epic1/money-panel.tsx")
    assert "Potentially avoidable observed" in money
    assert "Verified recovery" in money
    assert "Not recovered" in money
    assert "money_by_currency" in page

def test_new_shell_includes_tasks_notifications_search_accounts_and_portfolios():
    required=[
        "app/(dashboard)/app/tasks/page.tsx",
        "app/(dashboard)/app/notifications/page.tsx",
        "app/(dashboard)/app/search/page.tsx",
        "app/(dashboard)/app/accounts/page.tsx",
        "app/(dashboard)/app/portfolios/page.tsx",
    ]
    for rel in required: assert (ROOT/rel).exists(), rel

def test_frontend_still_contains_no_server_secrets():
    text="\n".join(p.read_text(encoding="utf-8") for source in ("app", "lib", "components") for p in (ROOT/source).rglob("*.ts*") if p.is_file())
    for secret in ("SUPABASE_SERVICE_ROLE_KEY","RECOVERY_WORKER_DATABASE_URL","GEMINI_API_KEY","RAZORPAY_KEY_SECRET","GOOGLE_ADS_SERVICE_ACCOUNT_JSON"):
        assert secret not in text
