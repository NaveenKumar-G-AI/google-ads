from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from recovery.accuracy import AccuracyPolicy
from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.db.canonical import payload_sha256
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.domain import CampaignSpendObservation, SearchTermObservation, summarize_coverage
from recovery.evidence import EvidenceDisposition, WasteEvidenceEngine
from recovery.negative_keywords import (
    ExistingNegativeKeyword, NegativeMatchType, NegativeScope, PositiveKeyword, ProtectedQuery,
    SafeNegativeKeywordEngine, ScopeEvidenceBundle,
)
from recovery.search_intent import BusinessFitEvaluator, ConservativeLexicalInterpreter, normalize_query
from recovery.semantic_router import ProductionSemanticRouter, RouteSource

from .domain import PermanentWorkerError


def _search_row(p: dict[str, Any]) -> SearchTermObservation:
    return SearchTermObservation(
        customer_id=str(p["customer_id"]), campaign_id=str(p["campaign_id"]),
        campaign_name=str(p["campaign_name"]), ad_group_id=str(p["ad_group_id"]),
        ad_group_name=str(p["ad_group_name"]), search_term=str(p["search_term"]),
        date=date.fromisoformat(str(p["date"])), network=str(p["network"]),
        match_source=str(p["match_source"]), search_term_match_type=str(p["search_term_match_type"]),
        targeting_status=str(p["targeting_status"]), triggering_keyword=p.get("triggering_keyword"),
        triggering_keyword_match_type=p.get("triggering_keyword_match_type"),
        impressions=int(p["impressions"]), clicks=int(p["clicks"]), cost_micros=int(p["cost_micros"]),
        conversions=Decimal(str(p["conversions"])), conversions_value=Decimal(str(p["conversions_value"])),
        all_conversions=Decimal(str(p["all_conversions"])),
        all_conversions_value=Decimal(str(p["all_conversions_value"])),
        currency_code=str(p["currency_code"]),
    )


def _spend_row(p: dict[str, Any]) -> CampaignSpendObservation:
    return CampaignSpendObservation(
        customer_id=str(p["customer_id"]), campaign_id=str(p["campaign_id"]),
        campaign_name=str(p["campaign_name"]), date=date.fromisoformat(str(p["date"])),
        network=str(p["network"]), cost_micros=int(p["cost_micros"]),
        currency_code=str(p["currency_code"]),
    )


def _positive(p: dict[str, Any]) -> PositiveKeyword:
    return PositiveKeyword(
        text=str(p["text"]), match_type=str(p["match_type"]), customer_id=str(p["customer_id"]),
        campaign_id=str(p["campaign_id"]), ad_group_id=str(p["ad_group_id"]),
        status=str(p.get("status", "ENABLED")), resource_name=p.get("resource_name"),
    )


def _negative(p: dict[str, Any]) -> ExistingNegativeKeyword:
    return ExistingNegativeKeyword(
        text=str(p["text"]), match_type=NegativeMatchType(str(p["match_type"])),
        scope=NegativeScope(str(p["scope"])), customer_id=str(p["customer_id"]),
        campaign_id=str(p["campaign_id"]) if p.get("campaign_id") is not None else None,
        ad_group_id=str(p["ad_group_id"]) if p.get("ad_group_id") is not None else None,
        shared_set_id=str(p["shared_set_id"]) if p.get("shared_set_id") is not None else None,
        applied_campaign_ids=tuple(str(x) for x in p.get("applied_campaign_ids", ())),
        resource_name=p.get("resource_name"),
    )


class ConservativeAnalysisJobRunner:
    """Deterministic Phase-10 analysis orchestrator.

    It intentionally uses the conservative lexical interpreter from Phase 3. It does
    not pretend regex is the future production semantic AI; queries it cannot establish
    with high confidence remain UNKNOWN. A later evaluated model can replace the
    interpreter without changing financial/action safety layers.
    """

    def __init__(
        self,
        core: PostgresRecoveryRepository,
        *,
        semantic_router_factory: Callable[..., ProductionSemanticRouter] | None = None,
        semantic_production_store: Any | None = None,
    ) -> None:
        self.core = core
        self.semantic_router_factory = semantic_router_factory
        self.semantic_production_store = semantic_production_store

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            account_id = UUID(str(payload["account_id"]))
            sync_run_id = UUID(str(payload["sync_run_id"]))
            truth_snapshot_id = UUID(str(payload["truth_snapshot_id"]))
            as_of = date.fromisoformat(str(payload["as_of"]))
            conversion_lag_days = int(payload["conversion_lag_days"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PermanentWorkerError("invalid analysis job payload", code="BAD_ANALYSIS_PAYLOAD") from exc
        if conversion_lag_days < 0 or conversion_lag_days > 365:
            raise PermanentWorkerError("conversion_lag_days must be between 0 and 365", code="BAD_ACCURACY_POLICY")

        terms, spend, truth_payload, inventory_payload = self._load_inputs(
            tenant_id=tenant_id, account_id=account_id, sync_run_id=sync_run_id,
            truth_snapshot_id=truth_snapshot_id,
        )
        if any(row.date > as_of for row in terms):
            raise PermanentWorkerError("analysis as_of predates synced search-term observations", code="AS_OF_INVALID")
        if not terms and not spend:
            raise PermanentWorkerError("completed sync contains no Search spend evidence", code="EMPTY_SYNC")

        try:
            truth = parse_business_truth_payload(
                truth_payload,
                submitted_by=str(truth_payload["created_by"]),
                submitted_at=datetime.fromisoformat(str(truth_payload["created_at"]).replace("Z", "+00:00")),
            )
        except Exception as exc:
            raise PermanentWorkerError("stored Business Truth cannot be reconstructed", code="TRUTH_REPLAY_FAILED") from exc

        coverage = summarize_coverage(terms, spend)
        policy = AccuracyPolicy(conversion_lag_days=conversion_lag_days)
        interpreter = ConservativeLexicalInterpreter()
        fit_engine = BusinessFitEvaluator(minimum_confidence=policy.minimum_semantic_confidence)
        evidence_engine = WasteEvidenceEngine(policy)
        negative_engine = SafeNegativeKeywordEngine()
        positives = tuple(_positive(x) for x in inventory_payload.get("positive_keywords", ()))
        negatives = tuple(_negative(x) for x in inventory_payload.get("existing_negatives", ()))

        semantic_mode = "conservative-lexical"
        router = None
        if self.semantic_router_factory is not None:
            router = self.semantic_router_factory(
                tenant_id=tenant_id, account_id=account_id, fit_evaluator=fit_engine
            )
            semantic_mode = "phase14-production-router"

        analysis_run_id = self.core.begin_analysis_run(
            tenant_id=tenant_id, request_id=f"worker-job:{job_id}", account_id=account_id,
            sync_run_id=sync_run_id, truth_snapshot_id=truth_snapshot_id, as_of=as_of,
            engine_versions={
                "semantic_interpreter": semantic_mode if router else f"{interpreter.name}:{interpreter.version}",
                "business_fit": "phase3:1",
                "financial_evidence": "phase4:1",
                "negative_safety": "phase5:1",
                "conversion_lag_days": str(conversion_lag_days),
            },
        )

        groups: dict[tuple[str, str, str, str, str], list[SearchTermObservation]] = defaultdict(list)
        for row in terms:
            groups[(row.customer_id,row.campaign_id,row.ad_group_id,row.network.upper(),normalize_query(row.search_term))].append(row)

        route_by_query: dict[str, Any] = {}
        if router is not None:
            ordered_queries = tuple(dict.fromkeys(
                tuple(sorted(groups[key], key=lambda r: (r.date, r.search_term)))[0].search_term
                for key in sorted(groups)
            ))
            routed = router.route_many(queries=ordered_queries, truth=truth)
            route_by_query = {d.raw_query: d for d in routed}

        evidence_by_scope: dict[tuple[str,str,str,str], list[Any]] = defaultdict(list)
        counts = {"queries": 0, "irrelevant": 0, "potentially_avoidable": 0, "review_required": 0, "proposals": 0, "ai_routed": 0, "baseline_fallback": 0}
        potential_micros = 0

        for key in sorted(groups):
            observations = tuple(sorted(groups[key], key=lambda r: (r.date, r.search_term)))
            query = observations[0].search_term
            route_decision = route_by_query.get(query) if router is not None else None
            if route_decision is not None:
                assessment = route_decision.assessment
                fit = route_decision.fit
                if route_decision.route_source is RouteSource.RELEASED_AI:
                    counts["ai_routed"] += 1
                else:
                    counts["baseline_fallback"] += 1
            else:
                assessment = interpreter.interpret(query, truth)
                fit = fit_engine.evaluate(assessment, truth)
            evidence = evidence_engine.evaluate(
                assessment=assessment, fit=fit, truth_fingerprint=truth.fingerprint_sha256,
                observations=observations, coverage=coverage, as_of=as_of,
            )
            source_identity = payload_sha256({
                "customer": key[0], "campaign": key[1], "ad_group": key[2],
                "network": key[3], "query": key[4], "truth": truth.fingerprint_sha256,
            })
            external_seed = source_identity[:24]
            if route_decision is not None:
                self.core.save_analysis_artifact(
                    tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                    artifact_kind="semantic_route_decision", external_id=f"route:{external_seed}",
                    value=route_decision, truth_fingerprint=truth.fingerprint_sha256,
                )
                if self.semantic_production_store is not None:
                    self.semantic_production_store.record_decision(
                        tenant_id=tenant_id, account_id=account_id, analysis_run_id=analysis_run_id,
                        source_identity=source_identity, truth_fingerprint=truth.fingerprint_sha256,
                        decision=route_decision,
                        release_definition_id=(
                            UUID(route_decision.release_definition_id)
                            if route_decision.release_definition_id else None
                        ),
                    )
            self.core.save_analysis_artifact(
                tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                artifact_kind="semantic_assessment", external_id=f"sem:{external_seed}", value=assessment,
                truth_fingerprint=truth.fingerprint_sha256,
            )
            self.core.save_analysis_artifact(
                tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                artifact_kind="business_fit_decision", external_id=f"fit:{external_seed}", value=fit,
                truth_fingerprint=truth.fingerprint_sha256,
            )
            self.core.save_analysis_artifact(
                tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                artifact_kind="financial_finding", external_id=f"ev:{external_seed}", value=evidence,
                truth_fingerprint=truth.fingerprint_sha256, currency_code=evidence.currency_code,
                money_micros=evidence.potentially_avoidable_cost_micros,
            )
            counts["queries"] += 1
            if fit.disposition.value == "irrelevant": counts["irrelevant"] += 1
            if evidence.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE:
                counts["potentially_avoidable"] += 1
                potential_micros += evidence.potentially_avoidable_cost_micros
            elif evidence.disposition is EvidenceDisposition.REVIEW_REQUIRED:
                counts["review_required"] += 1
            evidence_by_scope[(key[0], key[1], key[2], key[4])].append(evidence)

        # Proposal bundles intentionally combine every network finding for the exact
        # customer/campaign/ad-group/query scope. This prevents cherry-picking SEARCH
        # while ignoring conflicting SEARCH_PARTNERS evidence.
        for scope, findings in sorted(evidence_by_scope.items()):
            if not any(x.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE for x in findings):
                continue
            snapshot_id = payload_sha256({
                "analysis_run_id": str(analysis_run_id), "scope": scope,
                "finding_ids": sorted(oid for x in findings for oid in x.observation_ids),
            })[:32]
            bundle = ScopeEvidenceBundle(findings=tuple(findings), complete_for_scope=True, snapshot_id=snapshot_id)
            protected=tuple(
                ProtectedQuery(
                    query=rule.query, customer_id=scope[0], campaign_id=scope[1], ad_group_id=None,
                    reason=rule.reason, source="business_truth_protected_query",
                )
                for rule in truth.confirmed_protected_queries()
            )
            proposal = negative_engine.propose_exact_from_evidence(
                bundle=bundle, existing_negatives=negatives, positive_keywords=positives, protected_queries=protected,
            )
            self.core.save_analysis_artifact(
                tenant_id=tenant_id, analysis_run_id=analysis_run_id,
                artifact_kind="negative_keyword_proposal", external_id=proposal.proposal_id,
                value=proposal, truth_fingerprint=truth.fingerprint_sha256,
                currency_code=proposal.currency_code,
                money_micros=proposal.potentially_avoidable_cost_micros,
            )
            counts["proposals"] += 1

        summary = {
            "analysis_run_id": str(analysis_run_id),
            **counts,
            "potentially_avoidable_observed_micros": potential_micros,
            "currency_code": coverage.currency_code,
            "visible_search_term_micros": coverage.visible_search_term_cost_micros,
            "unobserved_search_micros": coverage.unobserved_cost_micros,
            "coverage_band": coverage.band.value,
            "query_count": counts["queries"],
            "irrelevant_count": counts["irrelevant"],
            "review_required_count": counts["review_required"],
            "proposal_count": counts["proposals"],
            "ai_routed_count": counts["ai_routed"],
            "baseline_fallback_count": counts["baseline_fallback"],
            "semantic_interpreter": semantic_mode if router else f"{interpreter.name}:{interpreter.version}",
        }
        self.core.save_analysis_summary(
            tenant_id=tenant_id, account_id=account_id, analysis_run_id=analysis_run_id, summary=summary
        )
        self.core.complete_analysis_run(tenant_id=tenant_id, analysis_run_id=analysis_run_id)
        return summary

    def terminal_failure(self, job, exc: BaseException) -> None:
        self.core.fail_analysis_run_by_request(
            tenant_id=job.tenant_id, request_id=f"worker-job:{job.job_id}",
            failure_code=str(getattr(exc, "code", None) or type(exc).__name__)[:120],
            failure_detail=str(exc),
        )

    def _load_inputs(self, *, tenant_id: UUID, account_id: UUID, sync_run_id: UUID,
                     truth_snapshot_id: UUID):
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT status, account_id FROM recovery.sync_runs
                WHERE tenant_id=%s AND id=%s
                """, (tenant_id, sync_run_id),
            )
            sr=cur.fetchone()
            if sr is None or sr["account_id"] != account_id or sr["status"] != "completed":
                raise PermanentWorkerError("analysis requires the exact completed sync/account", code="SYNC_NOT_READY")
            cur.execute(
                """
                SELECT payload FROM recovery.business_truth_snapshots
                WHERE tenant_id=%s AND id=%s AND account_id=%s
                """, (tenant_id, truth_snapshot_id, account_id),
            )
            tr=cur.fetchone()
            if tr is None:
                raise PermanentWorkerError("Business Truth snapshot not found for account", code="TRUTH_NOT_FOUND")
            cur.execute(
                """
                SELECT v.payload
                FROM recovery.search_term_version_occurrences o
                JOIN recovery.search_term_observation_versions v
                  ON v.tenant_id=o.tenant_id AND v.id=o.version_id
                JOIN recovery.sync_chunks c
                  ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                WHERE o.tenant_id=%s AND c.sync_run_id=%s
                ORDER BY c.chunk_start, v.id
                """, (tenant_id, sync_run_id),
            )
            terms=tuple(_search_row(dict(r["payload"])) for r in cur.fetchall())
            cur.execute(
                """
                SELECT v.payload
                FROM recovery.campaign_spend_version_occurrences o
                JOIN recovery.campaign_spend_observation_versions v
                  ON v.tenant_id=o.tenant_id AND v.id=o.version_id
                JOIN recovery.sync_chunks c
                  ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                WHERE o.tenant_id=%s AND c.sync_run_id=%s
                ORDER BY c.chunk_start, v.id
                """, (tenant_id, sync_run_id),
            )
            spend=tuple(_spend_row(dict(r["payload"])) for r in cur.fetchall())
            cur.execute(
                "SELECT payload FROM recovery.keyword_inventory_snapshots WHERE tenant_id=%s AND sync_run_id=%s",
                (tenant_id, sync_run_id),
            )
            inv=cur.fetchone()
            if inv is None:
                raise PermanentWorkerError("completed sync lacks keyword inventory snapshot", code="INVENTORY_MISSING")
            return terms, spend, dict(tr["payload"]), dict(inv["payload"])
