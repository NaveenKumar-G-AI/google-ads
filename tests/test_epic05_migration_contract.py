from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/'src/recovery/db/migrations/0013_epic05_measurement_integrity.sql').read_text()

def test_measurement_provider_evidence_tables_are_first_class_and_immutable():
    for table in ('measurement_snapshots','conversion_action_observations','customer_conversion_goal_observations','campaign_conversion_goal_observations','campaign_goal_config_observations','conversion_lag_observations'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
    assert 'prevent_immutable_mutation' in SQL
    assert 'ENABLE ROW LEVEL SECURITY' in SQL and 'FORCE ROW LEVEL SECURITY' in SQL

def test_business_truth_mapping_is_append_only_event_not_mutable_flag_on_provider_row():
    assert 'CREATE TABLE IF NOT EXISTS recovery.conversion_action_mapping_events' in SQL
    assert "mapping_status IN ('mapped','cleared')" in SQL
    assert 'outcome_id' in SQL and 'truth_snapshot_id' in SQL
    assert 'mapped_outcome_id' not in SQL.split('CREATE TABLE IF NOT EXISTS recovery.conversion_action_observations',1)[1].split(');',1)[0]

def test_no_fake_numeric_measurement_score_is_persisted():
    lower=SQL.lower()
    assert 'measurement_score' not in lower
    assert 'confidence_score' not in lower
