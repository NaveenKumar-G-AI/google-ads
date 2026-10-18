from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/'src/recovery/db/migrations/0015_epic07_recovery_center.sql').read_text()

def test_epic7_adds_latest_snapshot_indexes_without_new_financial_truth_table():
    assert 'recovery_ledger_mutation_latest_idx' in SQL
    assert 'recovery_mutation_case_latest_idx' in SQL
    assert 'CREATE TABLE' not in SQL
    assert 'No new financial-truth table' in SQL
