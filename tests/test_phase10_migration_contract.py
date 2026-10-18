from importlib import resources
import inspect

from recovery.worker.store import PostgresWorkerStore


def sql():
    return resources.files('recovery.db.migrations').joinpath('0003_phase10_worker_runtime.sql').read_text()


def test_job_status_supports_reconciliation_and_leases():
    s=sql().lower()
    assert "needs_reconciliation" in s
    assert "lease_expires_at" in s and "run_token" in s and "heartbeat_at" in s


def test_external_effect_fence_has_unique_effect_key():
    s=sql().lower()
    assert "create table if not exists recovery.external_effects" in s
    assert "unique (tenant_id, effect_key)" in s
    assert "in_flight" in s and "committed" in s and "ambiguous" in s


def test_worker_claim_uses_skip_locked_and_excludes_inflight_effects():
    src=inspect.getsource(PostgresWorkerStore.claim_next).lower()
    assert "for update skip locked" in src
    assert "external_effects" in src and "in_flight" in src


def test_expired_inflight_effect_is_swept_not_claimed_again():
    src=inspect.getsource(PostgresWorkerStore.sweep_ambiguous_expired_effects).lower()
    assert "needs_reconciliation" in src
    assert "mutation_events" in src
    assert "recovered_after_worker_crash" in src

def test_expired_final_attempt_is_failed_instead_of_stuck_running():
    src=inspect.getsource(PostgresWorkerStore.sweep_ambiguous_expired_effects).lower()
    assert "lease_expired_max_attempts" in src
    assert "attempts >= j.max_attempts" in src
    assert "recovery.sync_runs" in src and "recovery.analysis_runs" in src

def test_external_effect_reconciliation_is_fenced_by_job_or_effect_token():
    src=inspect.getsource(PostgresWorkerStore.reconcile_external_effect).lower()
    assert "self._owned_job(cur, job)" in src
    assert 'current["run_token"] != job.run_token' in src


def test_expired_inflight_sweep_marks_effect_ambiguous_too():
    src=inspect.getsource(PostgresWorkerStore.sweep_ambiguous_expired_effects).lower()
    assert "update recovery.external_effects" in src
    assert "state='ambiguous'" in src
