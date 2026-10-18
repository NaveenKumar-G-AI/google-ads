import pytest
from recovery.worker.retry import WorkerRetryPolicy, classify_safe_job_failure
from recovery.worker.domain import PermanentWorkerError, RetryableWorkerError


def test_exponential_backoff_is_bounded():
    p=WorkerRetryPolicy(base_delay_seconds=5,multiplier=2,max_delay_seconds=12)
    assert p.delay_for_attempt(1)==5
    assert p.delay_for_attempt(2)==10
    assert p.delay_for_attempt(3)==12
    assert p.delay_for_attempt(10)==12


def test_explicit_retryable_error_is_retried():
    p=WorkerRetryPolicy(base_delay_seconds=3)
    d=classify_safe_job_failure(RetryableWorkerError("x",code="TEMP"),attempt=2,policy=p)
    assert d is not None and d.delay_seconds==6 and d.code=="TEMP"


def test_permanent_error_is_not_retried():
    assert classify_safe_job_failure(PermanentWorkerError("x",code="BAD"),attempt=1,policy=WorkerRetryPolicy()) is None


def test_retry_policy_rejects_invalid_values():
    with pytest.raises(ValueError): WorkerRetryPolicy(multiplier=0.5)


def test_phase13_ai_transient_failure_is_safe_job_retryable():
    from recovery.semantic_ai import SemanticAIRetryableError
    decision=classify_safe_job_failure(
        SemanticAIRetryableError("429 provider overload"), attempt=1,
        policy=WorkerRetryPolicy(base_delay_seconds=1,max_delay_seconds=10),
    )
    assert decision is not None
    assert decision.code=="AI_TRANSIENT"
