from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_ledger_idempotency_is_bound_to_exact_mutation_event():
    src=(ROOT/'src/recovery/db/postgres.py').read_text()
    assert '"mutation_event_id": str(mutation_event_id)' in src
    assert 'ledger_fingerprint' in src

def test_apply_bootstraps_case_specific_ledger_but_never_verified_recovery():
    src=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
    assert 'recovery_ledger_entry_id' in src
    assert 'record_recovery_ledger' in src
    assert 'mutation_event_id=event_id' in src
    # Initial ledger is built without a causal result; apply itself never proves recovery.
    assert 'recovery_engine.summarize(' in src
    segment=src[src.index('ledger_summary=recovery_engine.summarize('):src.index('return {**canonical_payload(mutation)',src.index('ledger_summary=recovery_engine.summarize('))]
    assert 'causal=' not in segment

def test_recovery_center_repository_uses_latest_snapshot_per_mutation():
    src=(ROOT/'src/recovery/api/repository.py').read_text()
    assert 'DISTINCT ON (l.mutation_event_id)' in src
    assert 'Unobserved search spend remains a coverage limitation' in src
    assert 'observed_difference_vs_projection_micros' in src
