from __future__ import annotations

import os
from typing import Any
from uuid import UUID
from recovery.build_identity import get_build_identity


class DeploymentProbeJobRunner:
    """No external effects. Proves the deployed worker can claim and complete jobs."""

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("probe") != "deployment_round_trip":
            raise ValueError("invalid deployment probe payload")
        return {
            "probe": "ok",
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "worker_version": "0.35.0",
            "release_id": os.environ.get("RECOVERY_RELEASE_ID", "unversioned").strip() or "unversioned",
            **get_build_identity(),
        }
