from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from .db.canonical import canonical_payload, payload_sha256
from .db.postgres import Jsonb, PostgresRecoveryRepository
from .search_intent import FitDisposition
from .semantic_router import (
    ActiveSemanticRelease,
    DriftEvaluation,
    ProductionSemanticRouter,
    ReviewedProductionDecision,
    SemanticDriftGuard,
    SemanticRouteDecision,
    RouteSource,
)


class PostgresSemanticReleaseResolver:
    def __init__(self, core: PostgresRecoveryRepository, *, tenant_id: UUID, account_id: UUID) -> None:
        self.core = core
        self.tenant_id = tenant_id
        self.account_id = account_id

    def active_release(self) -> ActiveSemanticRelease | None:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, self.tenant_id)
            cur.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (e.release_definition_id)
                        e.release_definition_id, e.event_type, e.recorded_at
                    FROM recovery.semantic_release_events e
                    WHERE e.tenant_id=%s
                    ORDER BY e.release_definition_id, e.recorded_at DESC, e.id DESC
                )
                SELECT d.id, d.release_fingerprint, d.selected_confidence_threshold,
                       d.approved_languages, d.scope_kind,
                       ev.provider, ev.model, ev.provider_model_version, ev.thinking_level,
                       ev.prompt_version, ev.candidate_contract_fingerprint,
                       ev.semantic_schema_version,
                       COALESCE(s.state,'healthy') AS safety_state, s.trip_reason,
                       l.recorded_at
                FROM recovery.semantic_release_definitions d
                JOIN latest l ON l.release_definition_id=d.id AND l.event_type='activate'
                JOIN recovery.semantic_evaluation_runs ev
                  ON ev.tenant_id=d.tenant_id AND ev.id=d.evaluation_run_id
                LEFT JOIN recovery.semantic_release_safety_state s
                  ON s.tenant_id=d.tenant_id AND s.release_definition_id=d.id
                WHERE d.tenant_id=%s
                  AND ((d.scope_kind='account' AND d.account_id=%s) OR d.scope_kind='tenant')
                ORDER BY CASE d.scope_kind WHEN 'account' THEN 0 ELSE 1 END,
                         l.recorded_at DESC, d.id DESC
                LIMIT 2
                """,
                (self.tenant_id, self.tenant_id, self.account_id),
            )
            rows = cur.fetchall()
            if not rows:
                return None
            # The database blocks duplicate actives at an exact scope. If legacy/corrupt
            # data still presents two with equal specificity, fail closed to baseline.
            if len(rows) > 1 and rows[0]["scope_kind"] == rows[1]["scope_kind"]:
                return None
            row = rows[0]
            return ActiveSemanticRelease(
                release_definition_id=str(row["id"]),
                release_fingerprint=row["release_fingerprint"],
                provider=row["provider"],
                model=row["model"],
                provider_model_version=row["provider_model_version"],
                thinking_level=row["thinking_level"],
                prompt_version=row["prompt_version"],
                candidate_contract_fingerprint=row["candidate_contract_fingerprint"],
                semantic_schema_version=int(row["semantic_schema_version"]),
                selected_confidence_threshold=Decimal(str(row["selected_confidence_threshold"])),
                approved_languages=tuple(row["approved_languages"]),
                tripped=row["safety_state"] == "tripped",
                trip_reason=row["trip_reason"],
            )

    def trip_release(self, release: ActiveSemanticRelease, reason: str) -> None:
        release_id = UUID(release.release_definition_id)
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, self.tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-release-safety:{self.tenant_id}:{release_id}")
            cur.execute(
                """
                INSERT INTO recovery.semantic_release_safety_state(
                    tenant_id, release_definition_id, state, trip_reason, tripped_at, updated_at
                ) VALUES (%s,%s,'tripped',%s,now(),now())
                ON CONFLICT (tenant_id, release_definition_id) DO UPDATE
                SET state='tripped',
                    trip_reason=COALESCE(recovery.semantic_release_safety_state.trip_reason, EXCLUDED.trip_reason),
                    tripped_at=COALESCE(recovery.semantic_release_safety_state.tripped_at, EXCLUDED.tripped_at),
                    updated_at=now()
                """,
                (self.tenant_id, release_id, reason[:2000]),
            )


class PostgresSemanticProductionStore:
    def __init__(self, core: PostgresRecoveryRepository) -> None:
        self.core = core

    def record_decision(
        self, *, tenant_id: UUID, account_id: UUID, analysis_run_id: UUID,
        source_identity: str, truth_fingerprint: str, decision: SemanticRouteDecision,
        release_definition_id: UUID | None,
    ) -> UUID:
        persisted_fingerprint = payload_sha256({"source_identity": source_identity, "route_decision": decision.fingerprint_sha256})
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO recovery.semantic_production_decisions(
                    tenant_id, account_id, analysis_run_id, release_definition_id,
                    source_identity, raw_query, truth_fingerprint, route_source,
                    fallback_reason, release_fingerprint, declared_confidence,
                    provider_model_version, language_code, final_assessment, final_fit,
                    baseline_assessment, baseline_fit, candidate_assessment, candidate_fit,
                    decision_fingerprint, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, analysis_run_id, source_identity) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, account_id, analysis_run_id, release_definition_id,
                    source_identity, decision.raw_query, truth_fingerprint,
                    decision.route_source.value,
                    decision.fallback_reason.value if decision.fallback_reason else None,
                    decision.release_fingerprint,
                    str(decision.declared_confidence) if decision.declared_confidence is not None else None,
                    decision.provider_model_version,
                    decision.assessment.language_code,
                    Jsonb(canonical_payload(decision.assessment)), Jsonb(canonical_payload(decision.fit)),
                    Jsonb(canonical_payload(decision.baseline_assessment)), Jsonb(canonical_payload(decision.baseline_fit)),
                    Jsonb(canonical_payload(decision.candidate_assessment)) if decision.candidate_assessment else None,
                    Jsonb(canonical_payload(decision.candidate_fit)) if decision.candidate_fit else None,
                    persisted_fingerprint, decision.created_at,
                ),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                """SELECT id, decision_fingerprint FROM recovery.semantic_production_decisions
                   WHERE tenant_id=%s AND analysis_run_id=%s AND source_identity=%s""",
                (tenant_id, analysis_run_id, source_identity),
            )
            prior = cur.fetchone()
            if prior is None or prior["decision_fingerprint"] != persisted_fingerprint:
                raise ValueError("production semantic retry produced a different decision")
            return prior["id"]

    def record_drift_evaluation(
        self, *, tenant_id: UUID, release_definition_id: UUID, evaluation: DriftEvaluation
    ) -> UUID:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-drift:{tenant_id}:{release_definition_id}")
            cur.execute(
                """
                INSERT INTO recovery.semantic_drift_evaluations(
                    tenant_id, release_definition_id, release_fingerprint, policy_fingerprint,
                    evaluation_fingerprint, reviewed_cases, actionable_irrelevant_cases,
                    unsafe_false_exclusions, wilson_upper_unsafe_rate, sufficient_evidence,
                    tripped, reasons
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, evaluation_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, release_definition_id, evaluation.release_fingerprint,
                    evaluation.policy_fingerprint, evaluation.fingerprint_sha256,
                    evaluation.reviewed_cases, evaluation.actionable_irrelevant_cases,
                    evaluation.unsafe_false_exclusions,
                    str(evaluation.wilson_upper_unsafe_rate) if evaluation.wilson_upper_unsafe_rate is not None else None,
                    evaluation.sufficient_evidence, evaluation.tripped, Jsonb(list(evaluation.reasons)),
                ),
            )
            row=cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT id FROM recovery.semantic_drift_evaluations WHERE tenant_id=%s AND evaluation_fingerprint=%s",
                    (tenant_id, evaluation.fingerprint_sha256),
                )
                row=cur.fetchone()
            if evaluation.tripped:
                cur.execute(
                    """
                    INSERT INTO recovery.semantic_release_safety_state(
                        tenant_id, release_definition_id, state, trip_reason, tripped_at, updated_at
                    ) VALUES (%s,%s,'tripped',%s,now(),now())
                    ON CONFLICT (tenant_id, release_definition_id) DO UPDATE
                    SET state='tripped', trip_reason=COALESCE(recovery.semantic_release_safety_state.trip_reason, EXCLUDED.trip_reason),
                        tripped_at=COALESCE(recovery.semantic_release_safety_state.tripped_at, EXCLUDED.tripped_at), updated_at=now()
                    """,
                    (tenant_id, release_definition_id, "; ".join(evaluation.reasons)[:2000]),
                )
            return row["id"]

    def reviewed_decisions(
        self, *, tenant_id: UUID, release_definition_id: UUID, release_fingerprint: str
    ) -> tuple[ReviewedProductionDecision, ...]:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT d.decision_fingerprint, d.route_source,
                       d.final_fit->>'disposition' AS predicted_disposition,
                       g.payload->>'expected_disposition' AS gold_disposition
                FROM recovery.semantic_production_decisions d
                JOIN recovery.semantic_production_review_links l
                  ON l.tenant_id=d.tenant_id AND l.production_decision_id=d.id
                JOIN recovery.semantic_gold_case_versions g
                  ON g.tenant_id=l.tenant_id AND g.id=l.gold_case_version_id
                WHERE d.tenant_id=%s AND d.release_definition_id=%s AND d.release_fingerprint=%s
                ORDER BY d.created_at, d.id
                """,
                (tenant_id, release_definition_id, release_fingerprint),
            )
            return tuple(
                ReviewedProductionDecision(
                    decision_fingerprint=r["decision_fingerprint"],
                    release_fingerprint=release_fingerprint,
                    route_source=RouteSource(r["route_source"]),
                    predicted_disposition=FitDisposition(r["predicted_disposition"]),
                    gold_disposition=FitDisposition(r["gold_disposition"]),
                )
                for r in cur.fetchall()
            )


    def link_gold_review_and_evaluate(
        self, *, tenant_id: UUID, production_decision_id: UUID, gold_case_version_id: UUID,
        linked_by: str, guard: SemanticDriftGuard,
    ) -> DriftEvaluation:
        if not linked_by.strip():
            raise ValueError("linked_by is required")
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"semantic-production-review:{tenant_id}:{production_decision_id}")
            cur.execute(
                """SELECT release_definition_id, release_fingerprint
                   FROM recovery.semantic_production_decisions
                   WHERE tenant_id=%s AND id=%s""",
                (tenant_id, production_decision_id),
            )
            decision=cur.fetchone()
            if decision is None or decision["release_definition_id"] is None or decision["release_fingerprint"] is None:
                raise ValueError("only decisions associated with a semantic release can feed release drift")
            cur.execute(
                "SELECT id FROM recovery.semantic_gold_case_versions WHERE tenant_id=%s AND id=%s AND blinded_release_eligible=true",
                (tenant_id, gold_case_version_id),
            )
            if cur.fetchone() is None:
                raise ValueError("drift monitoring requires blinded release-eligible gold")
            cur.execute(
                """INSERT INTO recovery.semantic_production_review_links(
                       tenant_id, production_decision_id, gold_case_version_id, linked_by
                   ) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (tenant_id, production_decision_id) DO NOTHING""",
                (tenant_id, production_decision_id, gold_case_version_id, linked_by),
            )
            release_definition_id=decision["release_definition_id"]
            release_fingerprint=decision["release_fingerprint"]
        rows=self.reviewed_decisions(
            tenant_id=tenant_id, release_definition_id=release_definition_id,
            release_fingerprint=release_fingerprint,
        )
        evaluation=guard.evaluate(release_fingerprint=release_fingerprint, observations=rows)
        self.record_drift_evaluation(
            tenant_id=tenant_id, release_definition_id=release_definition_id, evaluation=evaluation
        )
        return evaluation

    def evaluate_drift(
        self, *, tenant_id: UUID, release: ActiveSemanticRelease, guard: SemanticDriftGuard
    ) -> DriftEvaluation:
        rows = self.reviewed_decisions(
            tenant_id=tenant_id,
            release_definition_id=UUID(release.release_definition_id),
            release_fingerprint=release.release_fingerprint,
        )
        evaluation = guard.evaluate(release_fingerprint=release.release_fingerprint, observations=rows)
        self.record_drift_evaluation(
            tenant_id=tenant_id,
            release_definition_id=UUID(release.release_definition_id),
            evaluation=evaluation,
        )
        return evaluation
