from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind, EvidenceRef,
    IntentCategory, IntentPolicy, Offer, OfferStatus, PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.semantic_ai import CandidateSemanticAI, SemanticAIConfig, SemanticModelResponse
from recovery.semantic_router import ActiveSemanticRelease, ProductionSemanticRouter

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def truth():
    confirmed = TruthBasis(TruthStatus.CONFIRMED, ("owner",), "owner", NOW)
    return BusinessTruthSnapshot(
        business_id="demo", business_name="Roof Co", version=1, created_at=NOW, created_by="owner",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(Offer("roof", "Roof replacement", ("new roof",), "Residential roofing",
                      CommercialModel.QUOTE_BASED, OfferStatus.ACTIVE, confirmed),),
        intent_policies=(IntentPolicy("jobs", IntentCategory.EMPLOYMENT, PolicyDisposition.DENY,
                                      "Recruitment is not customer acquisition", confirmed),),
        evidence=(EvidenceRef("owner", EvidenceKind.OPERATOR, "owner confirmation", NOW),),
    )


class DemoTransport:
    def classify(self, **kwargs):
        request = json.loads(kwargs["input_json"])
        results = []
        for q in request["queries"]:
            is_job = "jobs" in q["raw_query"].casefold()
            results.append({
                "item_id": q["item_id"], "raw_query": q["raw_query"], "status": "resolved",
                "language_code": "en",
                "intents": ([{"category": "employment", "confidence": 0.99, "evidence": ["jobs"]}]
                            if is_job else []),
                "offer_candidates": [{"offer_id": "roof", "confidence": 0.99, "evidence": ["roof"]}],
                "non_offer_candidates": [], "unresolved_signals": [], "ambiguity_reason": None,
                "declared_confidence": 0.99,
            })
        return SemanticModelResponse(
            {"schema_version": 1, "results": results}, "demo-provider", kwargs["model"], "demo-rev-1"
        )


class Resolver:
    def __init__(self, release): self.release = release
    def active_release(self): return self.release


candidate = CandidateSemanticAI(transport=DemoTransport(), config=SemanticAIConfig(maximum_attempts=1))
release = ActiveSemanticRelease(
    release_definition_id="11111111-1111-1111-1111-111111111111",
    release_fingerprint="a" * 64,
    provider="demo-provider", model=candidate.config.model, provider_model_version="demo-rev-1",
    thinking_level=candidate.config.thinking_level.value, prompt_version=candidate.prompt_version,
    candidate_contract_fingerprint=candidate.contract_fingerprint, semantic_schema_version=1,
    selected_confidence_threshold=Decimal("0.95"), approved_languages=("en",),
)
router = ProductionSemanticRouter(candidate=candidate, release_resolver=Resolver(release))

decision = router.route(query="roof replacement jobs", truth=truth())
print("route:", decision.route_source.value)
print("fit:", decision.fit.disposition.value)
print("release:", decision.release_fingerprint)
print("confidence:", decision.declared_confidence)
print("decision fingerprint:", decision.fingerprint_sha256)
