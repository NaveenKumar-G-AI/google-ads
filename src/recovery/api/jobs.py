from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


class JobType(str, Enum):
    GOOGLE_ADS_SYNC = "google_ads_sync"
    ANALYSIS_RUN = "analysis_run"
    APPLY_NEGATIVE = "apply_negative"
    ROLLBACK_NEGATIVE = "rollback_negative"
    SEMANTIC_SHADOW = "semantic_shadow"
    DEPLOYMENT_PROBE = "deployment_probe"
    GOOGLE_ADS_ACCOUNT_DISCOVERY = "google_ads_account_discovery"
    MONITORING_EVALUATION = "monitoring_evaluation"
    REPORT_GENERATION = "report_generation"
    PILOT_GOOGLE_ADS_READ_PROBE = "pilot_google_ads_read_probe"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_RECONCILIATION = "needs_reconciliation"


@dataclass(frozen=True, slots=True)
class JobReceipt:
    job_id: UUID
    job_type: JobType
    status: JobStatus
    idempotency_replay: bool = False
    result: dict[str, Any] | None = None
