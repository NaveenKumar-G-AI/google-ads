from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind,
    EvidenceRef, IntentCategory, IntentPolicy, Offer, OfferStatus, PolicyDisposition,
    TruthBasis, TruthStatus,
)
from recovery.search_intent import AssessmentStatus, FitDisposition
from recovery.semantic_ai import (
    CandidateBenchmarkRunner, CandidateSemanticAI, ModelUsage, SemanticAIConfig,
    SemanticAIContractError, SemanticModelResponse, ThinkingLevel,
)
from recovery.semantic_eval import DatasetSplit, GoldSemanticCase, LabelSource, ReleasePolicy
from recovery.semantic_release import (
    BlindHumanReview, GoldAdjudicationError, ReleaseEventType, ReleaseStateMachine,
    SemanticReleaseEvent, ShadowInput, ShadowSemanticRunner, adjudicate_gold_case,
    build_release_definition,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)


def confirmed():
    return TruthBasis(TruthStatus.CONFIRMED, ("owner",), "owner@test", NOW)


def truth():
    ev = EvidenceRef("owner", EvidenceKind.OPERATOR, "owner confirmation", NOW)
    return BusinessTruthSnapshot(
        business_id="biz", business_name="Accurate Roofing", version=1,
        created_at=NOW, created_by="owner@test",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(Offer(
            "roof-replacement", "Roof replacement", ("new roof",),
            "Residential roof replacement", CommercialModel.QUOTE_BASED,
            OfferStatus.ACTIVE, confirmed(),
        ),),
        intent_policies=(IntentPolicy(
            "jobs", IntentCategory.EMPLOYMENT, PolicyDisposition.DENY,
            "Recruitment is not acquisition", confirmed(),
        ),),
        evidence=(ev,),
    )


def response_item(item_id: str, query: str):
    employment = "jobs" in query.casefold()
    return {
        "item_id": item_id, "raw_query": query, "status": "resolved", "language_code": "en",
        "intents": ([{"category": "employment", "confidence": 0.99, "evidence": ["jobs"]}]
                    if employment else []),
        "offer_candidates": [{"offer_id": "roof-replacement", "confidence": 0.99, "evidence": ["roof"]}],
        "non_offer_candidates": [], "unresolved_signals": [], "ambiguity_reason": None,
        "declared_confidence": 0.99,
    }


class FakeTransport:
    provider = "fake-provider"
    def __init__(self, versions=("provider-v1",)):
        self.versions = list(versions)
        self.calls = 0
    def classify(self, **kwargs):
        p = json.loads(kwargs["input_json"])
        version = self.versions[min(self.calls, len(self.versions)-1)]
        self.calls += 1
        return SemanticModelResponse(
            {"schema_version": 1, "results": [response_item(x["item_id"], x["raw_query"]) for x in p["queries"]]},
            self.provider, kwargs["model"], version, f"req-{self.calls}", ModelUsage(total_tokens=20),
        )


def candidate(*, batch=8, versions=("provider-v1",), thinking=ThinkingLevel.LOW):
    return CandidateSemanticAI(
        transport=FakeTransport(versions),
        config=SemanticAIConfig(maximum_attempts=1, maximum_batch_queries=batch, thinking_level=thinking),
    )


def test_candidate_contract_fingerprint_is_stable_and_semantic_config_sensitive():
    a = candidate(batch=8)
    b = candidate(batch=8)
    c = candidate(batch=4)
    d = candidate(batch=8, thinking=ThinkingLevel.MEDIUM)
    assert a.contract_fingerprint == b.contract_fingerprint
    assert a.contract_fingerprint != c.contract_fingerprint
    assert a.contract_fingerprint != d.contract_fingerprint
    assert len(a.contract_fingerprint) == 64


def test_shadow_predictions_cannot_authorize_production_effects():
    t = truth(); c = candidate()
    src = ShadowInput.create(
        raw_query="roof replacement jobs", customer_id="1234567890", campaign_id="10",
        ad_group_id="20", network="SEARCH", observation_ids=("obs-1",),
        truth_fingerprint=t.fingerprint_sha256,
    )
    out = ShadowSemanticRunner(c).run(inputs=(src,), truth=t)
    assert out.prediction_count == 1
    p = out.predictions[0]
    assert p.candidate_fit.disposition is FitDisposition.IRRELEVANT
    assert p.production_effect_allowed is False
    assert p.candidate_contract_fingerprint == c.contract_fingerprint
    assert len(p.fingerprint_sha256) == 64


def test_shadow_run_rejects_mixed_provider_revisions():
    t = truth(); c = candidate(batch=1, versions=("provider-v1", "provider-v2"))
    inputs = tuple(
        ShadowInput.create(
            raw_query=q, customer_id="1234567890", campaign_id="10", ad_group_id="20",
            network="SEARCH", observation_ids=(f"obs-{i}",), truth_fingerprint=t.fingerprint_sha256,
        )
        for i, q in enumerate(("roof replacement jobs", "roof replacement"), start=1)
    )
    with pytest.raises(SemanticAIContractError, match="mixed provider/model/contract"):
        ShadowSemanticRunner(c).run(inputs=inputs, truth=t)


def review(*, reviewer="r1", disposition=FitDisposition.IRRELEVANT, status=AssessmentStatus.RESOLVED,
           blinded=True, adjudicator=False, language="en", tags=("employment",)):
    t = truth()
    return BlindHumanReview(
        raw_query="roof replacement jobs", truth_fingerprint=t.fingerprint_sha256,
        reviewer_id=reviewer, expected_disposition=disposition, expected_status=status,
        language_code=language, submitted_at=NOW, blinded_to_candidate=blinded,
        adjudicator=adjudicator, tags=tags,
    )


def test_gold_adjudication_requires_blinded_independent_review():
    with pytest.raises(GoldAdjudicationError, match="blinded"):
        adjudicate_gold_case((review(reviewer="r1"), review(reviewer="r2", blinded=False)), dataset_salt="secret")
    with pytest.raises(GoldAdjudicationError, match="adjudicator"):
        adjudicate_gold_case((
            review(reviewer="r1", disposition=FitDisposition.IRRELEVANT),
            review(reviewer="r2", disposition=FitDisposition.RELEVANT),
        ), dataset_salt="secret")


def test_gold_adjudication_is_stable_and_supports_blinded_adjudicator():
    reviews = (
        review(reviewer="r1", disposition=FitDisposition.IRRELEVANT),
        review(reviewer="r2", disposition=FitDisposition.RELEVANT),
        review(reviewer="r3", disposition=FitDisposition.IRRELEVANT, adjudicator=True),
    )
    a = adjudicate_gold_case(reviews, dataset_salt="split-secret")
    b = adjudicate_gold_case(tuple(reversed(reviews)), dataset_salt="split-secret")
    assert a.expected_disposition is FitDisposition.IRRELEVANT
    assert a.label_source is LabelSource.ADJUDICATED
    assert a.split is b.split
    assert a.case_id == b.case_id
    assert a.reviewer_count == 3


def gold(case_id, query, t, split):
    return GoldSemanticCase(
        case_id, query, t.fingerprint_sha256, FitDisposition.IRRELEVANT,
        AssessmentStatus.RESOLVED, "en", split, LabelSource.DOUBLE_REVIEW, 2,
    )


def passing_evaluation():
    t = truth(); c = candidate(batch=8)
    cases = [gold(f"c{i}", f"roof replacement jobs cal {i}", t, DatasetSplit.CALIBRATION) for i in range(30)]
    cases += [gold(f"t{i}", f"roof replacement jobs test {i}", t, DatasetSplit.TEST) for i in range(30)]
    policy = ReleasePolicy(
        minimum_test_cases=20, minimum_safety_cases=20, minimum_calibration_support=20,
        required_language_slices=("en",), minimum_cases_per_required_language=20,
        maximum_wilson_upper_unsafe_rate=Decimal("0.2"),
    )
    evaluation = CandidateBenchmarkRunner(c).run(
        cases=cases, truths={t.fingerprint_sha256: t}, policy=policy,
    )
    assert evaluation.gate_result.passed
    return evaluation, policy


def test_release_definition_is_pinned_to_exact_evaluated_candidate_and_language_gate():
    evaluation, policy = passing_evaluation()
    release = build_release_definition(
        evaluation, policy=policy, approved_languages=("en",), created_by="release-admin", created_at=NOW,
    )
    assert release.candidate.provider_model_version == "provider-v1"
    assert release.candidate.candidate_contract_fingerprint == evaluation.candidate_contract_fingerprint
    assert release.selected_confidence_threshold == evaluation.selected_confidence_threshold
    assert release.approved_languages == ("en",)
    assert len(release.release_fingerprint) == 64
    with pytest.raises(ValueError, match="required_language_slice"):
        build_release_definition(
            evaluation, policy=policy, approved_languages=("ta",), created_by="release-admin", created_at=NOW,
        )


def test_release_state_machine_requires_explicit_activation_and_revocation_is_terminal():
    evaluation, policy = passing_evaluation()
    definition = build_release_definition(
        evaluation, policy=policy, approved_languages=("en",), created_by="release-admin", created_at=NOW,
    )
    state = ReleaseStateMachine(definition)
    assert not state.active
    activate = SemanticReleaseEvent(definition.release_fingerprint, ReleaseEventType.ACTIVATE, "admin", NOW)
    state.apply(activate)
    assert state.permits_candidate_for_language("en")
    assert not state.permits_candidate_for_language("ta")
    revoke = SemanticReleaseEvent(
        definition.release_fingerprint, ReleaseEventType.REVOKE, "admin", NOW, reason="safety regression"
    )
    state.apply(revoke)
    assert not state.active
    with pytest.raises(ValueError, match="revoked"):
        state.apply(SemanticReleaseEvent(definition.release_fingerprint, ReleaseEventType.ACTIVATE, "admin", NOW))
