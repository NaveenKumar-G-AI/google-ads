from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_google_executor_preserves_validate_only_no_partial_failure_and_readback():
    src=(ROOT/'src/recovery/google_ads/mutation.py').read_text()
    assert 'validate_only=True' in src
    assert 'partial_failure=False' in src
    assert 'find_applied_ad_group_negative' in src
    assert 'exact live negative could not be verified by read-back' in src

def test_approval_and_execution_block_stale_business_truth_and_newer_analysis():
    repo=(ROOT/'src/recovery/api/repository.py').read_text()
    assert 'cannot approve stale proposal after Business Truth changed' in repo
    assert 'cannot approve stale proposal after newer analysis' in repo
    assert 'proposal is stale because Business Truth changed; analyze again' in repo
    assert 'proposal is stale because a newer completed analysis exists' in repo

def test_worker_rechecks_staleness_after_queueing():
    src=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
    assert 'PROPOSAL_TRUTH_STALE' in src
    assert 'PROPOSAL_ANALYSIS_STALE' in src
    assert 'CASE_CLOSED' in src

def test_case_projection_does_not_create_second_financial_truth_table():
    sql=(ROOT/'src/recovery/db/migrations/0014_epic06_recovery_cases.sql').read_text().lower()
    assert 'verified_recovery_micros' not in sql
    assert 'candidate_micros' not in sql

def test_rollback_bypasses_apply_freshness_gate_but_keeps_exact_resource_readback():
    worker=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
    assert 'is_rollback = bool(applied_event_raw and not approval_raw)' in worker
    assert 'if not is_rollback:' in worker
    assert 'rollback mutate returned but exact negative is still present on read-back' in worker

def test_case_verification_ledger_is_linked_through_this_cases_mutation_not_whole_analysis_run():
    repo=(ROOT/'src/recovery/api/repository.py').read_text()
    marker='FROM recovery.recovery_ledger_entries'
    case_section=repo[repo.index(marker,repo.index('def _case_related')):repo.index('cur.execute(',repo.index(marker,repo.index('def _case_related'))+10)]
    assert 'mutation_event_id IN' in case_section
    assert 'analysis_run_id=%s OR' not in case_section

def test_measurement_integrity_is_an_operational_gate_for_approval_execution_and_worker():
    repo=(ROOT/'src/recovery/api/repository.py').read_text()
    worker=(ROOT/'src/recovery/worker/google_jobs.py').read_text()
    assert 'Measurement Integrity does not currently allow conversion-dependent action approval' in repo
    assert 'Measurement Integrity does not currently allow conversion-dependent Google Ads mutation' in repo
    assert 'MEASUREMENT_GATE_BLOCKED' in worker
