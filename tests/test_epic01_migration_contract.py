from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/"src/recovery/db/migrations/0009_epic01_product_shell.sql").read_text()

def test_epic1_creates_first_class_product_shell_entities():
    for table in ("portfolios","portfolio_accounts","shell_tasks","user_notifications","user_shell_preferences"):
        assert f"CREATE TABLE IF NOT EXISTS recovery.{table}" in SQL

def test_epic1_operational_entities_are_rls_protected():
    assert "ARRAY['portfolios','portfolio_accounts','shell_tasks']" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "ALTER TABLE recovery.user_notifications ENABLE ROW LEVEL SECURITY" in SQL
    assert "ALTER TABLE recovery.user_notifications FORCE ROW LEVEL SECURITY" in SQL
    assert "CREATE POLICY notification_self" in SQL
    assert "user_id = recovery_private.current_user_id()" in SQL
    assert "ALTER TABLE recovery.user_shell_preferences FORCE ROW LEVEL SECURITY" in SQL

def test_portfolio_membership_is_relational_not_json():
    assert "CREATE TABLE IF NOT EXISTS recovery.portfolio_accounts" in SQL
    assert "REFERENCES recovery.google_ads_accounts(tenant_id, id)" in SQL

def test_task_schema_has_real_lifecycle_and_assignment():
    assert "priority text NOT NULL" in SQL
    assert "status text NOT NULL" in SQL
    assert "assigned_to uuid REFERENCES recovery.app_users" in SQL
    assert "due_at timestamptz" in SQL
