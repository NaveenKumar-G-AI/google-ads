from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from .db.canonical import canonical_payload, payload_sha256
from .db.postgres import IdempotencyConflict, Jsonb, PostgresRecoveryRepository
from .semantic_release import (
    BlindHumanReview,
    SemanticReleaseDefinition,
    SemanticReleaseEvent,
    ShadowPrediction,
    ShadowRunResult,
    evaluation_report_fingerprint,
    release_policy_fingerprint,
)
from .semantic_ai import CandidateReleaseEvaluation
from .semantic_eval import GoldSemanticCase, ReleasePolicy, dataset_fingerprint


class PostgresSemanticRegistry:
    """Phase-13 persistence facade.

    Evidence tables are append-only in PostgreSQL. Only shadow-run operational status
    is mutable. This class never writes financial findings or action proposals.
    """

    def __init__(self, core: PostgresRecoveryRepository) -> None:
        self.core = core

    def begin_shadow_run(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        sync_run_id: UUID,
        truth_snapshot_id: UUID,
        request_id: str,
        candidate_contract_fingerprint: str,
        provider: str,
        model: str,
        thinking_level: str,
        prompt_version: str,
        semantic_schema_version: int,
    ) -> UUID:
        if not request_id.strip():
            raise ValueError("request_id is required")
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-shadow:{tenant_id}:{request_id}")
            cur.execute(
                """
                SELECT * FROM recovery.semantic_shadow_runs
                WHERE tenant_id=%s AND request_id=%s
                """,
                (tenant_id, request_id),
            )
            existing = cur.fetchone()
            expected = {
                "account_id": account_id,
                "sync_run_id": sync_run_id,
                "truth_snapshot_id": truth_snapshot_id,
                "candidate_contract_fingerprint": candidate_contract_fingerprint,
                "provider": provider,
                "model": model,
                "thinking_level": thinking_level,
                "prompt_version": prompt_version,
                "semantic_schema_version": semantic_schema_version,
            }
            if existing is not None:
                for key, value in expected.items():
                    if existing[key] != value:
                        raise IdempotencyConflict(
                            f"semantic shadow request_id already exists with different {key}"
                        )
                return existing["id"]

            cur.execute(
                """
                SELECT s.status AS sync_status, s.account_id AS sync_account,
                       b.account_id AS truth_account
                FROM recovery.sync_runs s
                JOIN recovery.business_truth_snapshots b
                  ON b.tenant_id=s.tenant_id AND b.id=%s
                WHERE s.tenant_id=%s AND s.id=%s
                """,
                (truth_snapshot_id, tenant_id, sync_run_id),
            )
            source = cur.fetchone()
            if source is None:
                raise ValueError("sync/truth inputs do not exist")
            if source["sync_status"] != "completed":
                raise ValueError("shadow mode requires a completed sync")
            if source["sync_account"] != account_id or source["truth_account"] != account_id:
                raise ValueError("shadow sync/truth must belong to the exact advertiser account")

            cur.execute(
                """
                INSERT INTO recovery.semantic_shadow_runs(
                    tenant_id, account_id, sync_run_id, truth_snapshot_id, request_id,
                    candidate_contract_fingerprint, provider, model, thinking_level,
                    prompt_version, semantic_schema_version, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running')
                RETURNING id
                """,
                (
                    tenant_id, account_id, sync_run_id, truth_snapshot_id, request_id,
                    candidate_contract_fingerprint, provider, model, thinking_level,
                    prompt_version, semantic_schema_version,
                ),
            )
            return cur.fetchone()["id"]

    def save_shadow_predictions(
        self,
        *,
        tenant_id: UUID,
        shadow_run_id: UUID,
        result: ShadowRunResult,
    ) -> int:
        inserted = 0
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT truth_snapshot_id, candidate_contract_fingerprint, status
                FROM recovery.semantic_shadow_runs
                WHERE tenant_id=%s AND id=%s
                FOR UPDATE
                """,
                (tenant_id, shadow_run_id),
            )
            run = cur.fetchone()
            if run is None or run["status"] != "running":
                raise ValueError("shadow run does not exist or is not running")
            if run["candidate_contract_fingerprint"] != result.candidate_contract_fingerprint:
                raise IdempotencyConflict("shadow result candidate contract differs from run")
            for prediction in result.predictions:
                if prediction.truth_fingerprint != result.truth_fingerprint:
                    raise ValueError("prediction/result truth mismatch")
                cur.execute(
                    """
                    INSERT INTO recovery.semantic_shadow_predictions(
                        tenant_id, shadow_run_id, source_identity, raw_query, normalized_query,
                        customer_id, campaign_id, ad_group_id, network, observation_ids,
                        truth_fingerprint, candidate_contract_fingerprint,
                        request_prompt_fingerprint, provider, model, provider_model_version,
                        request_id, declared_confidence, candidate_assessment, candidate_fit,
                        baseline_assessment, baseline_fit, prediction_fingerprint,
                        production_effect_allowed, created_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s
                    )
                    ON CONFLICT (tenant_id, shadow_run_id, source_identity) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, shadow_run_id, prediction.source.source_identity,
                        prediction.source.raw_query, prediction.candidate_assessment.normalized_query,
                        prediction.source.customer_id, prediction.source.campaign_id,
                        prediction.source.ad_group_id, prediction.source.network,
                        Jsonb(list(prediction.source.observation_ids)), prediction.truth_fingerprint,
                        prediction.candidate_contract_fingerprint,
                        prediction.request_prompt_fingerprint, prediction.provider, prediction.model,
                        prediction.provider_model_version, prediction.request_id,
                        str(prediction.declared_confidence) if prediction.declared_confidence is not None else None,
                        Jsonb(canonical_payload(prediction.candidate_assessment)),
                        Jsonb(canonical_payload(prediction.candidate_fit)),
                        Jsonb(canonical_payload(prediction.baseline_assessment)),
                        Jsonb(canonical_payload(prediction.baseline_fit)),
                        prediction.fingerprint_sha256, prediction.created_at,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    inserted += 1
                else:
                    cur.execute(
                        """
                        SELECT prediction_fingerprint, provider_model_version, candidate_contract_fingerprint
                        FROM recovery.semantic_shadow_predictions
                        WHERE tenant_id=%s AND shadow_run_id=%s AND source_identity=%s
                        """,
                        (tenant_id, shadow_run_id, prediction.source.source_identity),
                    )
                    prior = cur.fetchone()
                    if prior is None or prior["prediction_fingerprint"] != prediction.fingerprint_sha256:
                        raise IdempotencyConflict(
                            "shadow retry produced different semantic output for an already persisted source"
                        )
                    if prior["provider_model_version"] != prediction.provider_model_version:
                        raise IdempotencyConflict(
                            "shadow retry crossed provider model revisions after persistence"
                        )
        return inserted

    def complete_shadow_run(
        self,
        *,
        tenant_id: UUID,
        shadow_run_id: UUID,
        result: ShadowRunResult,
    ) -> None:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT count(*) AS n, min(provider_model_version) AS min_version,
                       max(provider_model_version) AS max_version,
                       min(candidate_contract_fingerprint) AS min_contract,
                       max(candidate_contract_fingerprint) AS max_contract
                FROM recovery.semantic_shadow_predictions
                WHERE tenant_id=%s AND shadow_run_id=%s
                """,
                (tenant_id, shadow_run_id),
            )
            observed = cur.fetchone()
            if int(observed["n"]) != result.prediction_count:
                raise IdempotencyConflict("shadow run prediction count differs from persisted evidence")
            if observed["min_contract"] != result.candidate_contract_fingerprint or observed["max_contract"] != result.candidate_contract_fingerprint:
                raise IdempotencyConflict("shadow run contains mixed candidate contract fingerprints")
            if observed["min_version"] != observed["max_version"]:
                raise IdempotencyConflict("shadow run contains mixed provider model revisions")
            if observed["min_version"] != result.provider_model_version:
                raise IdempotencyConflict("shadow run provider revision differs from persisted predictions")
            cur.execute(
                """
                UPDATE recovery.semantic_shadow_runs
                SET status='completed', completed_at=now(), prediction_count=%s,
                    disagreement_count=%s, provider_model_version=%s, usage=%s
                WHERE tenant_id=%s AND id=%s AND status='running'
                """,
                (
                    result.prediction_count, result.disagreement_count,
                    result.provider_model_version, Jsonb(canonical_payload(result.usage)),
                    tenant_id, shadow_run_id,
                ),
            )
            if cur.rowcount != 1:
                raise ValueError("shadow run could not transition to completed")

    def fail_shadow_run_by_request(
        self,
        *,
        tenant_id: UUID,
        request_id: str,
        failure_code: str,
        failure_detail: str,
    ) -> None:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                UPDATE recovery.semantic_shadow_runs
                SET status='failed', failure_code=%s, failure_detail=%s, completed_at=now()
                WHERE tenant_id=%s AND request_id=%s AND status='running'
                """,
                (failure_code[:120], failure_detail[:4000], tenant_id, request_id),
            )

    def record_blind_review(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        truth_snapshot_id: UUID,
        review: BlindHumanReview,
    ) -> UUID:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-review:{tenant_id}:{review.case_key}:{review.reviewer_id}")
            cur.execute(
                "SELECT id FROM recovery.semantic_human_reviews WHERE tenant_id=%s AND review_fingerprint=%s",
                (tenant_id, review.review_fingerprint),
            )
            exact = cur.fetchone()
            if exact is not None:
                return exact["id"]
            cur.execute(
                """
                SELECT id, review_version FROM recovery.semantic_human_reviews
                WHERE tenant_id=%s AND case_key=%s AND reviewer_actor=%s
                ORDER BY review_version DESC LIMIT 1
                """,
                (tenant_id, review.case_key, review.reviewer_id),
            )
            prior = cur.fetchone()
            version = 1 if prior is None else int(prior["review_version"]) + 1
            cur.execute(
                """
                INSERT INTO recovery.semantic_human_reviews(
                    tenant_id, account_id, truth_snapshot_id, case_key, raw_query,
                    truth_fingerprint, reviewer_actor, review_version, supersedes_id,
                    expected_disposition, expected_status, language_code, tags, notes,
                    blinded_to_candidate, adjudicator, review_fingerprint, submitted_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    tenant_id, account_id, truth_snapshot_id, review.case_key, review.raw_query,
                    review.truth_fingerprint, review.reviewer_id, version, prior["id"] if prior else None,
                    review.expected_disposition.value, review.expected_status.value,
                    review.language_code, Jsonb(list(review.tags)), review.notes,
                    review.blinded_to_candidate, review.adjudicator, review.review_fingerprint,
                    review.submitted_at,
                ),
            )
            return cur.fetchone()["id"]

    def save_gold_case_version(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        truth_snapshot_id: UUID,
        case_key: str,
        gold: GoldSemanticCase,
        created_by: str,
        blinded_release_eligible: bool = True,
    ) -> UUID:
        case_payload = canonical_payload(gold)
        case_fingerprint = payload_sha256(case_payload)
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"gold-case:{tenant_id}:{case_key}")
            cur.execute(
                """
                SELECT id, version, case_fingerprint
                FROM recovery.semantic_gold_case_versions
                WHERE tenant_id=%s AND case_key=%s
                ORDER BY version DESC LIMIT 1
                """,
                (tenant_id, case_key),
            )
            prior = cur.fetchone()
            if prior is not None and prior["case_fingerprint"] == case_fingerprint:
                return prior["id"]
            version = 1 if prior is None else int(prior["version"]) + 1
            cur.execute(
                """
                INSERT INTO recovery.semantic_gold_case_versions(
                    tenant_id, account_id, truth_snapshot_id, case_key, version,
                    supersedes_id, case_id, identity_fingerprint, case_fingerprint, split,
                    label_source, reviewer_count, blinded_release_eligible, payload, created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    tenant_id, account_id, truth_snapshot_id, case_key, version,
                    prior["id"] if prior else None, gold.case_id, gold.identity_fingerprint,
                    case_fingerprint, gold.split.value, gold.label_source.value,
                    gold.reviewer_count, blinded_release_eligible, Jsonb(case_payload), created_by,
                ),
            )
            return cur.fetchone()["id"]


    def save_dataset_snapshot(
        self,
        *,
        tenant_id: UUID,
        cases: Iterable[tuple[UUID, GoldSemanticCase]],
        split_salt_fingerprint: str,
        created_by: str,
    ) -> tuple[UUID, str]:
        rows = tuple(cases)
        if not rows:
            raise ValueError("dataset snapshot requires at least one gold case")
        ids = [x[0] for x in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("dataset snapshot contains duplicate gold-case version IDs")
        gold = tuple(x[1] for x in rows)
        fingerprint = dataset_fingerprint(gold)
        split_salt_fingerprint = split_salt_fingerprint.strip().lower()
        if len(split_salt_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in split_salt_fingerprint):
            raise ValueError("split_salt_fingerprint must be SHA-256 hex")
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-dataset:{tenant_id}:{fingerprint}")
            cur.execute(
                "SELECT id FROM recovery.semantic_dataset_snapshots WHERE tenant_id=%s AND dataset_fingerprint=%s",
                (tenant_id, fingerprint),
            )
            existing = cur.fetchone()
            if existing is not None:
                return existing["id"], fingerprint
            cur.execute(
                """
                SELECT id, case_fingerprint, blinded_release_eligible
                FROM recovery.semantic_gold_case_versions
                WHERE tenant_id=%s AND id = ANY(%s)
                """,
                (tenant_id, ids),
            )
            found = {x["id"]: x for x in cur.fetchall()}
            if set(found) != set(ids):
                raise ValueError("dataset references missing gold-case versions")
            for gold_id, case in rows:
                if not found[gold_id]["blinded_release_eligible"]:
                    raise ValueError("release dataset cannot include non-blinded/ineligible gold")
                if found[gold_id]["case_fingerprint"] != payload_sha256(canonical_payload(case)):
                    raise IdempotencyConflict("gold-case payload differs from stored version")
            cur.execute(
                """
                INSERT INTO recovery.semantic_dataset_snapshots(
                    tenant_id, dataset_fingerprint, split_salt_fingerprint, case_version_ids,
                    case_count, created_by
                ) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (tenant_id, fingerprint, split_salt_fingerprint, Jsonb([str(x) for x in ids]), len(ids), created_by),
            )
            dataset_id = cur.fetchone()["id"]
            for ordinal, gold_id in enumerate(ids):
                cur.execute(
                    """
                    INSERT INTO recovery.semantic_dataset_case_members(
                        tenant_id, dataset_snapshot_id, gold_case_version_id, ordinal
                    ) VALUES (%s,%s,%s,%s)
                    """,
                    (tenant_id, dataset_id, gold_id, ordinal),
                )
            return dataset_id, fingerprint

    def record_evaluation(
        self,
        *,
        tenant_id: UUID,
        dataset_snapshot_id: UUID,
        evaluation: CandidateReleaseEvaluation,
        policy: ReleasePolicy,
        created_by: str,
    ) -> UUID:
        policy_fp = release_policy_fingerprint(policy)
        report_fp = evaluation_report_fingerprint(evaluation)
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                "SELECT dataset_fingerprint FROM recovery.semantic_dataset_snapshots WHERE tenant_id=%s AND id=%s",
                (tenant_id, dataset_snapshot_id),
            )
            ds = cur.fetchone()
            if ds is None:
                raise ValueError("semantic dataset snapshot does not exist")
            if ds["dataset_fingerprint"] != evaluation.test_report.dataset_fingerprint:
                raise IdempotencyConflict("evaluation dataset fingerprint differs from stored snapshot")
            cur.execute(
                """
                INSERT INTO recovery.semantic_evaluation_runs(
                    tenant_id, dataset_snapshot_id, candidate_fingerprint,
                    candidate_contract_fingerprint, provider, model, provider_model_version,
                    thinking_level, prompt_version, semantic_schema_version,
                    release_policy_fingerprint, selected_confidence_threshold, gate_passed,
                    evaluation_report_fingerprint, payload, created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, evaluation_report_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, dataset_snapshot_id, evaluation.candidate_fingerprint,
                    evaluation.candidate_contract_fingerprint, evaluation.provider, evaluation.model,
                    evaluation.provider_model_version, evaluation.thinking_level,
                    evaluation.prompt_version, evaluation.semantic_schema_version, policy_fp,
                    str(evaluation.selected_confidence_threshold) if evaluation.selected_confidence_threshold is not None else None,
                    evaluation.gate_result.passed, report_fp, Jsonb(canonical_payload(evaluation)), created_by,
                ),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "SELECT id FROM recovery.semantic_evaluation_runs WHERE tenant_id=%s AND evaluation_report_fingerprint=%s",
                (tenant_id, report_fp),
            )
            return cur.fetchone()["id"]

    def record_release_definition(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID | None,
        evaluation_run_id: UUID,
        definition: SemanticReleaseDefinition,
        scope_kind: str = "account",
    ) -> UUID:
        if scope_kind not in {"account", "tenant"}:
            raise ValueError("scope_kind must be account or tenant")
        if (scope_kind == "account") != (account_id is not None):
            raise ValueError("account scope requires account_id; tenant scope forbids it")
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-release-definition:{tenant_id}:{definition.release_fingerprint}")
            cur.execute(
                """
                SELECT gate_passed, candidate_fingerprint, candidate_contract_fingerprint,
                       provider, model, provider_model_version, thinking_level, prompt_version,
                       semantic_schema_version, selected_confidence_threshold,
                       evaluation_report_fingerprint, release_policy_fingerprint
                FROM recovery.semantic_evaluation_runs
                WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, evaluation_run_id),
            )
            evaluated = cur.fetchone()
            if evaluated is None or not evaluated["gate_passed"]:
                raise ValueError("release requires an existing passing evaluation")
            exact = {
                "candidate_fingerprint": definition.evaluation_candidate_fingerprint,
                "candidate_contract_fingerprint": definition.candidate.candidate_contract_fingerprint,
                "provider": definition.candidate.provider,
                "model": definition.candidate.model,
                "provider_model_version": definition.candidate.provider_model_version,
                "thinking_level": definition.candidate.thinking_level,
                "prompt_version": definition.candidate.prompt_version,
                "semantic_schema_version": definition.candidate.semantic_schema_version,
                "evaluation_report_fingerprint": definition.evaluation_report_fingerprint,
                "release_policy_fingerprint": definition.release_policy_fingerprint,
            }
            for key, value in exact.items():
                if evaluated[key] != value:
                    raise IdempotencyConflict(f"release definition differs from evaluated {key}")
            if str(evaluated["selected_confidence_threshold"]) != str(definition.selected_confidence_threshold):
                raise IdempotencyConflict("release threshold differs from evaluated threshold")
            cur.execute(
                """
                INSERT INTO recovery.semantic_release_definitions(
                    tenant_id, account_id, scope_kind, evaluation_run_id,
                    release_fingerprint, candidate_identity_fingerprint,
                    selected_confidence_threshold, approved_languages, payload, created_by, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, release_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, account_id, scope_kind, evaluation_run_id,
                    definition.release_fingerprint, definition.candidate.fingerprint_sha256,
                    str(definition.selected_confidence_threshold), list(definition.approved_languages),
                    Jsonb(canonical_payload(definition)), definition.created_by, definition.created_at,
                ),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "SELECT id FROM recovery.semantic_release_definitions WHERE tenant_id=%s AND release_fingerprint=%s",
                (tenant_id, definition.release_fingerprint),
            )
            return cur.fetchone()["id"]

    def record_release_event(
        self,
        *,
        tenant_id: UUID,
        release_definition_id: UUID,
        event: SemanticReleaseEvent,
    ) -> UUID:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-release-event:{tenant_id}:{release_definition_id}")
            cur.execute(
                "SELECT release_fingerprint FROM recovery.semantic_release_definitions WHERE tenant_id=%s AND id=%s",
                (tenant_id, release_definition_id),
            )
            release = cur.fetchone()
            if release is None:
                raise ValueError("semantic release definition does not exist")
            if release["release_fingerprint"] != event.release_fingerprint:
                raise IdempotencyConflict("release event fingerprint target mismatch")
            cur.execute(
                """
                INSERT INTO recovery.semantic_release_events(
                    tenant_id, release_definition_id, event_type, actor, reason,
                    event_fingerprint, occurred_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, event_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, release_definition_id, event.event_type.value,
                    event.actor, event.reason, event.event_fingerprint, event.occurred_at,
                ),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "SELECT id FROM recovery.semantic_release_events WHERE tenant_id=%s AND event_fingerprint=%s",
                (tenant_id, event.event_fingerprint),
            )
            return cur.fetchone()["id"]
