from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from recovery.api.jobs import JobStatus, JobType


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    RECONCILIATION = "reconciliation"
    LEASE_LOST = "lease_lost"


class EffectState(str, Enum):
    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    COMMITTED = "committed"
    RECONCILED = "reconciled"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: UUID
    tenant_id: UUID
    job_type: JobType
    payload: dict[str, Any]
    requested_by: UUID
    operation_key: str | None
    attempts: int
    max_attempts: int
    run_token: UUID
    lease_owner: str
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        if self.attempts < 1 or self.max_attempts < self.attempts:
            raise ValueError("claimed job attempt counters are invalid")
        if self.lease_expires_at.tzinfo is None or self.lease_expires_at.utcoffset() is None:
            raise ValueError("lease_expires_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class JobSuccess:
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    delay_seconds: float
    code: str
    detail: str

    def __post_init__(self) -> None:
        if self.delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        if not self.code.strip():
            raise ValueError("retry code is required")


class WorkerError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class RetryableWorkerError(WorkerError):
    pass


class PermanentWorkerError(WorkerError):
    pass


class ReconciliationRequired(WorkerError):
    """Remote side effect may have happened; automatic retry is forbidden."""

    def __init__(self, message: str, *, code: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=code)
        self.context = context or {}


class LeaseLost(WorkerError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalEffect:
    effect_id: UUID
    tenant_id: UUID
    job_id: UUID
    effect_key: str
    effect_kind: str
    state: EffectState
    plan_fingerprint: str
    proposal_artifact_id: UUID | None
    run_token: UUID | None
    resource_name: str | None
    google_request_id: str | None
    started_at: datetime | None


TERMINAL_JOB_STATUSES = frozenset({
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.NEEDS_RECONCILIATION,
})
