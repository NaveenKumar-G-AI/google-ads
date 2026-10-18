from pathlib import Path

SQL=Path('src/recovery/db/migrations/0005_phase14_production_semantic_router.sql').read_text().casefold()

def test_phase14_tables_and_append_only_evidence_exist():
    for name in ('semantic_release_safety_state','semantic_production_decisions','semantic_production_review_links','semantic_drift_evaluations'):
        assert f'create table if not exists recovery.{name}' in SQL
    assert 'production_effect_allowed' not in SQL  # production routing has explicit decision tables, not shadow reuse
    assert "'semantic_production_decisions','semantic_production_review_links','semantic_drift_evaluations'" in SQL
    assert 'prevent_immutable_mutation' in SQL

def test_tripped_release_is_terminal_and_activation_conflicts_are_blocked():
    assert 'prevent_semantic_safety_untrip' in SQL
    assert 'block_activation_of_tripped_release' in SQL
    assert 'prevent_multiple_active_semantic_releases' in SQL
    assert "state in ('healthy','tripped')" in SQL

def test_phase14_tables_force_rls():
    assert 'enable row level security' in SQL
    assert 'force row level security' in SQL
    assert 'current_tenant_id()' in SQL
