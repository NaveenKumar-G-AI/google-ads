from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/'src/recovery/db/migrations/0014_epic06_recovery_cases.sql').read_text()

def test_recovery_case_collaboration_is_append_only_and_rls_protected():
    assert 'CREATE TABLE IF NOT EXISTS recovery.recovery_case_events' in SQL
    assert 'prevent_immutable_mutation' in SQL
    assert 'ENABLE ROW LEVEL SECURITY' in SQL and 'FORCE ROW LEVEL SECURITY' in SQL

def test_case_identity_reuses_immutable_proposal_artifact_not_duplicate_mutable_status_table():
    assert 'proposal_artifact_id uuid NOT NULL' in SQL
    assert 'REFERENCES recovery.analysis_artifacts(tenant_id, id)' in SQL
    assert 'status text' not in SQL.lower()

def test_case_events_cover_collaboration_without_rewriting_decision_or_mutation_truth():
    for t in ('assigned','unassigned','commented','review_requested','closed','reopened'):
        assert f"'{t}'" in SQL
    assert 'approved' not in SQL and 'applied' not in SQL
