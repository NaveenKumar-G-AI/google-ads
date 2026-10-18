from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from recovery.api.jobs import JobStatus, JobType
from recovery.worker.domain import (
    ClaimedJob, EffectState, ExternalEffect, JobSuccess,
    PermanentWorkerError, ReconciliationRequired, RetryableWorkerError,
)
from recovery.worker.handlers import DurableMutationHandler, HandlerRegistry, SafeJobHandler
from recovery.worker.retry import WorkerRetryPolicy
from recovery.worker.runtime import WorkerRuntime


NOW = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)


def job(job_type=JobType.GOOGLE_ADS_SYNC, *, attempts=1, operation_key=None):
    return ClaimedJob(
        job_id=uuid4(), tenant_id=uuid4(), job_type=job_type,
        payload={}, requested_by=uuid4(), operation_key=operation_key,
        attempts=attempts, max_attempts=5, run_token=uuid4(), lease_owner="worker-1",
        lease_expires_at=NOW + timedelta(minutes=5),
    )


class FakeStore:
    def __init__(self, jobs=()):
        self.jobs=list(jobs); self.succeeded=[]; self.retried=[]; self.failed=[]; self.reconciled=[]
        self.effects={}; self.heartbeats=0; self.sweeps=0
    def claim_next(self, **kwargs):
        return self.jobs.pop(0) if self.jobs else None
    def heartbeat(self, *, job, extend_seconds):
        self.heartbeats += 1
        return NOW + timedelta(seconds=extend_seconds)
    def succeed(self, *, job, result): self.succeeded.append((job,result))
    def retry(self, *, job, delay_seconds, code, detail): self.retried.append((job,delay_seconds,code,detail))
    def fail(self, *, job, code, detail): self.failed.append((job,code,detail))
    def needs_reconciliation(self, *, job, code, detail, context=None):
        self.reconciled.append((job,code,detail,context or {}))
    def sweep_ambiguous_expired_effects(self, **kwargs): self.sweeps += 1; return 0
    def prepare_external_effect(self, *, job, effect_key, effect_kind, plan_fingerprint, proposal_artifact_id, payload):
        e=self.effects.get(effect_key)
        if e is None:
            e=ExternalEffect(uuid4(),job.tenant_id,job.job_id,effect_key,effect_kind,EffectState.PREPARED,plan_fingerprint,proposal_artifact_id,None,None,None,None)
            self.effects[effect_key]=e
        return e
    def mark_effect_in_flight(self, *, job, effect_id):
        key=next(k for k,v in self.effects.items() if v.effect_id==effect_id); old=self.effects[key]
        e=ExternalEffect(old.effect_id,old.tenant_id,old.job_id,old.effect_key,old.effect_kind,EffectState.IN_FLIGHT,old.plan_fingerprint,old.proposal_artifact_id,job.run_token,None,None,NOW)
        self.effects[key]=e; return e
    def commit_external_effect(self, *, job, effect_id, resource_name, google_request_id, payload):
        key=next(k for k,v in self.effects.items() if v.effect_id==effect_id); old=self.effects[key]
        e=ExternalEffect(old.effect_id,old.tenant_id,old.job_id,old.effect_key,old.effect_kind,EffectState.COMMITTED,old.plan_fingerprint,old.proposal_artifact_id,job.run_token,resource_name,google_request_id,NOW)
        self.effects[key]=e; return e
    def reconcile_external_effect(self, *, job, effect_id, state, resource_name, detail, payload=None):
        key=next(k for k,v in self.effects.items() if v.effect_id==effect_id); old=self.effects[key]
        e=ExternalEffect(old.effect_id,old.tenant_id,old.job_id,old.effect_key,old.effect_kind,state,old.plan_fingerprint,old.proposal_artifact_id,old.run_token,resource_name,None,old.started_at)
        self.effects[key]=e; return e
    def get_external_effect(self, **kwargs): return self.effects.get(kwargs['effect_key'])


class SuccessRunner:
    def __call__(self, **kwargs): return {"ok": True}

class RetryRunner:
    def __call__(self, **kwargs): raise RetryableWorkerError("temporary", code="TEMP")

class PermanentRunner:
    def __call__(self, **kwargs): raise PermanentWorkerError("bad input", code="BAD")


def runtime(store, handler):
    return WorkerRuntime(
        store=store, registry=HandlerRegistry({JobType.GOOGLE_ADS_SYNC: handler}),
        worker_id="worker-1", lease_seconds=30, heartbeat_interval_seconds=10,
        retry_policy=WorkerRetryPolicy(base_delay_seconds=3,max_delay_seconds=30),
    )


def test_successful_safe_job_is_marked_succeeded():
    j=job(); store=FakeStore([j]); r=runtime(store,SafeJobHandler(SuccessRunner()))
    assert r.run_once() is True
    assert store.succeeded[0][1]=={"ok":True}
    assert not store.failed and not store.retried
    assert store.sweeps==1


def test_retryable_safe_job_is_requeued_with_backoff():
    j=job(attempts=2); store=FakeStore([j]); r=runtime(store,SafeJobHandler(RetryRunner()))
    r.run_once()
    assert store.retried[0][1]==6
    assert store.retried[0][2]=="TEMP"


def test_permanent_safe_job_is_failed_not_retried():
    j=job(); store=FakeStore([j]); r=runtime(store,SafeJobHandler(PermanentRunner()))
    r.run_once()
    assert store.failed[0][1]=="BAD"
    assert not store.retried


def test_empty_queue_returns_false_after_sweep():
    store=FakeStore(); r=runtime(store,SafeJobHandler(SuccessRunner()))
    assert r.run_once() is False
    assert store.sweeps==1


class MutationRunner:
    def __init__(self, *, preflight=None, apply_error=None):
        self.preflight_result=preflight or {"exact_negative_present":False}
        self.apply_error=apply_error; self.calls=[]
    def preflight(self, **kwargs): self.calls.append("preflight"); return self.preflight_result
    def validate(self, **kwargs): self.calls.append("validate"); return {"validated":True}
    def apply(self, **kwargs):
        self.calls.append("apply")
        if self.apply_error: raise self.apply_error
        return {"resource_name":"customers/1234567890/adGroupCriteria/20~99"}
    def rollback(self, **kwargs): self.calls.append("rollback"); return {"resource_name":kwargs['payload'].get('resource_name')}


def mutation_job(*, rollback=False):
    p=uuid4()
    payload={"proposal_artifact_id":str(p)}
    if rollback:
        payload.update({"resource_name":"customers/1234567890/adGroupCriteria/20~99","applied_mutation_event_id":str(uuid4())})
    else:
        payload.update({"proposal_fingerprint":"a"*64,"approval_event_id":str(uuid4())})
    return ClaimedJob(
        job_id=uuid4(),tenant_id=uuid4(),job_type=JobType.ROLLBACK_NEGATIVE if rollback else JobType.APPLY_NEGATIVE,
        payload=payload,requested_by=uuid4(),operation_key=f"proposal:{p}:{'rollback' if rollback else 'apply'}",
        attempts=1,max_attempts=5,run_token=uuid4(),lease_owner="w",lease_expires_at=NOW+timedelta(minutes=5),
    )


def test_apply_mutation_goes_preflight_validate_inflight_apply_commit():
    j=mutation_job(); store=FakeStore(); runner=MutationRunner()
    out=DurableMutationHandler(store,runner)(j)
    assert runner.calls==["preflight","validate","apply"]
    assert out.result["effect_state"]=="committed"


def test_preexisting_negative_is_not_duplicated_and_requires_reconciliation():
    j=mutation_job(); store=FakeStore(); runner=MutationRunner(preflight={"exact_negative_present":True,"resource_name":"x"})
    with pytest.raises(ReconciliationRequired) as e:
        DurableMutationHandler(store,runner)(j)
    assert e.value.code=="PREEXISTING_NEGATIVE_AFTER_APPROVAL"
    assert runner.calls==["preflight"]
    assert next(iter(store.effects.values())).state is EffectState.AMBIGUOUS


def test_live_mutate_exception_becomes_reconciliation_not_retry():
    j=mutation_job(); store=FakeStore(); runner=MutationRunner(apply_error=RuntimeError("connection lost"))
    with pytest.raises(ReconciliationRequired) as e:
        DurableMutationHandler(store,runner)(j)
    assert e.value.code=="GOOGLE_MUTATE_OUTCOME_AMBIGUOUS"
    assert next(iter(store.effects.values())).state is EffectState.AMBIGUOUS


def test_runtime_routes_ambiguous_mutation_to_needs_reconciliation():
    j=mutation_job(); store=FakeStore([j]); runner=MutationRunner(apply_error=RuntimeError("lost"))
    r=WorkerRuntime(
        store=store,
        registry=HandlerRegistry({JobType.APPLY_NEGATIVE:DurableMutationHandler(store,runner)}),
        worker_id="w",lease_seconds=30,heartbeat_interval_seconds=10,
    )
    r.run_once()
    assert store.reconciled and not store.retried and not store.failed


def test_rollback_already_absent_is_reconciled_without_live_remove():
    j=mutation_job(rollback=True); store=FakeStore(); runner=MutationRunner(preflight={"resource_absent":True})
    out=DurableMutationHandler(store,runner,rollback=True)(j)
    assert runner.calls==["preflight"]
    assert out.result["effect_state"]=="reconciled"
    assert out.result["attribution"]=="not_claimed"


def test_prior_inflight_effect_is_never_replayed():
    j=mutation_job(); store=FakeStore(); runner=MutationRunner()
    e=store.prepare_external_effect(job=j,effect_key=j.operation_key,effect_kind="apply_negative",plan_fingerprint="a"*64,proposal_artifact_id=UUID(j.payload['proposal_artifact_id']),payload=j.payload)
    store.mark_effect_in_flight(job=j,effect_id=e.effect_id)
    with pytest.raises(ReconciliationRequired) as err:
        DurableMutationHandler(store,runner)(j)
    assert err.value.code=="AMBIGUOUS_PRIOR_EFFECT"
    assert runner.calls==[]


def test_committed_effect_is_idempotent_replay_without_google_call():
    j=mutation_job(); store=FakeStore(); runner=MutationRunner()
    e=store.prepare_external_effect(job=j,effect_key=j.operation_key,effect_kind="apply_negative",plan_fingerprint="a"*64,proposal_artifact_id=UUID(j.payload['proposal_artifact_id']),payload=j.payload)
    store.mark_effect_in_flight(job=j,effect_id=e.effect_id)
    store.commit_external_effect(job=j,effect_id=e.effect_id,resource_name="r",google_request_id=None,payload={})
    out=DurableMutationHandler(store,runner)(j)
    assert out.result["idempotent_replay"] is True
    assert runner.calls==[]


def test_job_status_has_reconciliation_terminal_state():
    assert JobStatus.NEEDS_RECONCILIATION.value=="needs_reconciliation"

class LeaseLostOnSucceedStore(FakeStore):
    def succeed(self, *, job, result):
        from recovery.worker.domain import LeaseLost
        raise LeaseLost("ownership changed", code="LEASE_LOST")


def test_success_transition_lease_loss_does_not_overwrite_new_owner():
    j=job(); store=LeaseLostOnSucceedStore([j]); r=runtime(store, SafeJobHandler(SuccessRunner()))
    assert r.run_once() is True
    assert not store.failed and not store.retried and not store.succeeded


class TerminalAwareRunner(PermanentRunner):
    def __init__(self): self.terminal=[]
    def terminal_failure(self, job, exc): self.terminal.append((job.job_id, str(exc)))


def test_terminal_failure_hook_runs_only_on_terminal_failure():
    runner=TerminalAwareRunner(); j=job(); store=FakeStore([j]); r=runtime(store, SafeJobHandler(runner))
    r.run_once()
    assert runner.terminal == [(j.job_id, "bad input")]

def test_retryable_failure_at_attempt_budget_runs_terminal_hook_and_fails():
    class RetryTerminal(RetryRunner):
        def __init__(self): self.terminal=[]
        def terminal_failure(self, job, exc): self.terminal.append(getattr(exc, "code", None))
    runner=RetryTerminal(); j=job(attempts=5); store=FakeStore([j]); r=runtime(store, SafeJobHandler(runner))
    r.run_once()
    assert runner.terminal == ["MAX_ATTEMPTS"]
    assert store.failed[0][1] == "MAX_ATTEMPTS"
    assert not store.retried
