from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from recovery.google_ads.sync import is_retryable_google_ads_error
from recovery.semantic_ai import SemanticAIRetryableError

from .domain import PermanentWorkerError, ReconciliationRequired, RetryDecision, RetryableWorkerError


@dataclass(frozen=True, slots=True)
class WorkerRetryPolicy:
    base_delay_seconds: float = 5.0
    multiplier: float = 2.0
    max_delay_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be >= 1")

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        raw = self.base_delay_seconds * math.pow(self.multiplier, attempt - 1)
        return min(self.max_delay_seconds, raw)


def _google_request_id(exc: BaseException) -> str | None:
    value = getattr(exc, "request_id", None)
    if value:
        return str(value)
    failure = getattr(exc, "failure", None)
    value = getattr(failure, "request_id", None) if failure is not None else None
    return str(value) if value else None


def classify_safe_job_failure(exc: BaseException, *, attempt: int, policy: WorkerRetryPolicy) -> RetryDecision | None:
    """Classify failures for jobs whose work is safe to repeat.

    Sync/analysis work is designed to be idempotent. Google transient failures may be
    retried. Programming/validation/permanent errors are not hidden behind retries.
    """
    if isinstance(exc, RetryableWorkerError):
        return RetryDecision(policy.delay_for_attempt(attempt), exc.code, str(exc))
    if isinstance(exc, (PermanentWorkerError, ReconciliationRequired)):
        return None
    if isinstance(exc, SemanticAIRetryableError):
        return RetryDecision(policy.delay_for_attempt(attempt), "AI_TRANSIENT", str(exc))
    if is_retryable_google_ads_error(exc):
        return RetryDecision(policy.delay_for_attempt(attempt), "GOOGLE_TRANSIENT", str(exc))
    return None


def mutation_exception_context(exc: BaseException) -> dict[str, Any]:
    request_id = _google_request_id(exc)
    return {
        "exception_type": type(exc).__name__,
        "google_request_id": request_id,
        "message": str(exc)[:2000],
    }
