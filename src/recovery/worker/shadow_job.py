from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.search_intent import normalize_query
from recovery.semantic_ai import CandidateSemanticAI
from recovery.semantic_registry import PostgresSemanticRegistry
from recovery.semantic_release import ShadowInput, ShadowSemanticRunner

from .domain import PermanentWorkerError


class SemanticShadowJobRunner:
    """Execute candidate semantics against real imported queries in non-production shadow mode."""

    def __init__(
        self,
        *,
        core: PostgresRecoveryRepository,
        candidate: CandidateSemanticAI,
        registry: PostgresSemanticRegistry | None = None,
    ) -> None:
        self.core = core
        self.candidate = candidate
        self.registry = registry or PostgresSemanticRegistry(core)
        self.shadow = ShadowSemanticRunner(candidate)

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            account_id = UUID(str(payload["account_id"]))
            sync_run_id = UUID(str(payload["sync_run_id"]))
            truth_snapshot_id = UUID(str(payload["truth_snapshot_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise PermanentWorkerError("invalid semantic shadow job payload", code="BAD_SHADOW_PAYLOAD") from exc

        truth, rows = self._load_inputs(
            tenant_id=tenant_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            truth_snapshot_id=truth_snapshot_id,
        )
        request_id = f"worker-job:{job_id}"
        run_id = self.registry.begin_shadow_run(
            tenant_id=tenant_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            truth_snapshot_id=truth_snapshot_id,
            request_id=request_id,
            candidate_contract_fingerprint=self.candidate.contract_fingerprint,
            provider=str(getattr(self.candidate.transport, "provider", "unknown")),
            model=self.candidate.config.model,
            thinking_level=self.candidate.config.thinking_level.value,
            prompt_version=self.candidate.prompt_version,
            semantic_schema_version=1,
        )

        grouped: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
        raw_by_key: dict[tuple[str, str, str, str, str], str] = {}
        for row in rows:
            key = (
                row["customer_id"], row["campaign_id"], row["ad_group_id"],
                row["network"].upper(), normalize_query(row["raw_query"]),
            )
            grouped[key].append(row["observation_id"])
            raw_by_key.setdefault(key, row["raw_query"])

        inputs = tuple(
            ShadowInput.create(
                raw_query=raw_by_key[key],
                customer_id=key[0], campaign_id=key[1], ad_group_id=key[2], network=key[3],
                observation_ids=tuple(sorted(grouped[key])),
                truth_fingerprint=truth.fingerprint_sha256,
            )
            for key in sorted(grouped)
        )
        if not inputs:
            raise PermanentWorkerError("completed sync contains no search terms for shadow mode", code="EMPTY_SHADOW_SYNC")

        result = self.shadow.run(inputs=inputs, truth=truth)
        self.registry.save_shadow_predictions(tenant_id=tenant_id, shadow_run_id=run_id, result=result)
        self.registry.complete_shadow_run(tenant_id=tenant_id, shadow_run_id=run_id, result=result)
        return {
            "shadow_run_id": str(run_id),
            "prediction_count": result.prediction_count,
            "disagreement_count": result.disagreement_count,
            "candidate_irrelevant_count": result.irrelevant_candidate_count,
            "provider": result.provider,
            "model": result.model,
            "provider_model_version": result.provider_model_version,
            "candidate_contract_fingerprint": result.candidate_contract_fingerprint,
            "production_effect_allowed": False,
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "thinking_tokens": result.usage.thinking_tokens,
                "total_tokens": result.usage.total_tokens,
            },
        }

    def terminal_failure(self, job, exc: BaseException) -> None:
        self.registry.fail_shadow_run_by_request(
            tenant_id=job.tenant_id,
            request_id=f"worker-job:{job.job_id}",
            failure_code=str(getattr(exc, "code", None) or type(exc).__name__)[:120],
            failure_detail=str(exc),
        )

    def _load_inputs(
        self, *, tenant_id: UUID, account_id: UUID, sync_run_id: UUID, truth_snapshot_id: UUID
    ):
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT s.status, s.account_id, b.payload, b.account_id AS truth_account
                FROM recovery.sync_runs s
                JOIN recovery.business_truth_snapshots b
                  ON b.tenant_id=s.tenant_id AND b.id=%s
                WHERE s.tenant_id=%s AND s.id=%s
                """,
                (truth_snapshot_id, tenant_id, sync_run_id),
            )
            source = cur.fetchone()
            if source is None or source["status"] != "completed":
                raise PermanentWorkerError("semantic shadow requires completed sync", code="SYNC_NOT_READY")
            if source["account_id"] != account_id or source["truth_account"] != account_id:
                raise PermanentWorkerError("shadow sync/truth account mismatch", code="SHADOW_ACCOUNT_MISMATCH")
            truth_payload = dict(source["payload"])
            try:
                truth = parse_business_truth_payload(
                    truth_payload,
                    submitted_by=str(truth_payload["created_by"]),
                    submitted_at=datetime.fromisoformat(str(truth_payload["created_at"]).replace("Z", "+00:00")),
                )
            except Exception as exc:
                raise PermanentWorkerError("stored Business Truth cannot be reconstructed", code="TRUTH_REPLAY_FAILED") from exc

            # Deliberately project only semantic/scope fields. Cost/click/conversion
            # metrics are not loaded into the shadow runner at all.
            cur.execute(
                """
                SELECT v.id::text AS observation_id,
                       v.payload->>'customer_id' AS customer_id,
                       v.payload->>'campaign_id' AS campaign_id,
                       v.payload->>'ad_group_id' AS ad_group_id,
                       v.payload->>'network' AS network,
                       v.payload->>'search_term' AS raw_query
                FROM recovery.search_term_version_occurrences o
                JOIN recovery.search_term_observation_versions v
                  ON v.tenant_id=o.tenant_id AND v.id=o.version_id
                JOIN recovery.sync_chunks c
                  ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                WHERE o.tenant_id=%s AND c.sync_run_id=%s
                ORDER BY c.chunk_start, v.id
                """,
                (tenant_id, sync_run_id),
            )
            rows = tuple(dict(x) for x in cur.fetchall())
            return truth, rows
