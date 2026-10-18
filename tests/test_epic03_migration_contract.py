from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/'src/recovery/db/migrations/0011_epic03_search_intelligence.sql').read_text()

def test_saved_views_are_user_scoped_and_rls_forced():
    assert 'CREATE TABLE IF NOT EXISTS recovery.search_saved_views' in SQL
    assert 'ENABLE ROW LEVEL SECURITY' in SQL and 'FORCE ROW LEVEL SECURITY' in SQL
    assert 'user_id=recovery_private.current_user_id()' in SQL

def test_saved_view_requires_exactly_one_account_or_portfolio_scope():
    assert "CHECK (account_id IS NOT NULL OR portfolio_id IS NOT NULL)" in SQL
    assert "CHECK (NOT (account_id IS NOT NULL AND portfolio_id IS NOT NULL))" in SQL

def test_epic3_does_not_create_a_derived_money_table():
    assert 'CREATE TABLE IF NOT EXISTS recovery.search_intelligence' not in SQL
    assert 'no derived money is materialized' in SQL
