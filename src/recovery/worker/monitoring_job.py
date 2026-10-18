from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from recovery.api.repository import PostgresApiRepository
from recovery.db.postgres import PostgresRecoveryRepository
from .domain import PermanentWorkerError

@dataclass(slots=True)
class MonitoringEvaluationJobRunner:
    core: PostgresRecoveryRepository
    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        try: account_id=UUID(str(payload["account_id"]))
        except (KeyError,ValueError,TypeError) as exc:
            raise PermanentWorkerError("invalid monitoring payload",code="BAD_MONITORING_PAYLOAD") from exc
        return PostgresApiRepository(self.core).monitoring_evaluate(
            tenant_id=tenant_id,account_id=account_id,actor=f"system:monitoring-job:{job_id}"
        )
