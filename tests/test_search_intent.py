from datetime import datetime, timezone
from decimal import Decimal

import pytest

from recovery.business_truth import (
    BusinessTruthSnapshot,
    CatalogCompleteness,
    CommercialModel,
    EvidenceKind,
    EvidenceRef,
    ExplicitNonOffer,
    IntentCategory,
    IntentPolicy,
    Offer,
    OfferStatus,
    PolicyDisposition,
    TruthBasis,
    TruthStatus,
)
from recovery.search_intent import (
    AssessmentStatus,
    BusinessFitEvaluator,
    ConservativeLexicalInterpreter,
    FitDisposition,
    FitReasonCode,
    IntentHypothesis,
    NonOfferHypothesis,
    OfferHypothesis,
    SemanticAssessment,
    assessment_from_mapping,
    normalize_query,
    semantic_context_for_model,
)

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def confirmed(*evidence_ids: str) -> TruthBasis:
    return TruthBasis(
        status=TruthStatus.CONFIRMED,
        evidence_ids=tuple(evidence_ids),
        confirmed_by="owner@example.test",
        confirmed_at=NOW,
    )


def truth(*, policies=(), non_offers=()) -> BusinessTruthSnapshot:
    ev = EvidenceRef(
        evidence_id="owner",
        kind=EvidenceKind.OPERATOR,
        reference="Owner confirmation",
        captured_at=NOW,
    )
    offer = Offer(
        offer_id="roof-replacement",
        name="Roof replacement",
        aliases=("new roof",),
        description="Residential roof replacement",
        commercial_model=CommercialModel.QUOTE_BASED,
        offer_status=OfferStatus.ACTIVE,
        basis=confirmed("owner"),
    )
    return BusinessTruthSnapshot(
        business_id="biz",
        business_name="Accurate Roofing",
        version=1,
        created_at=NOW,
        created_by="owner@example.test",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(offer,),
        explicit_non_offers=tuple(non_offers),
        intent_policies=tuple(policies),
        evidence=(ev,),
    )


def assessment(**overrides) -> SemanticAssessment:
    data = dict(
        raw_query="roof replacement",
        normalized_query="roof replacement",
        status=AssessmentStatus.RESOLVED,
        language_code="en",
        intents=(),
        offer_candidates=(OfferHypothesis("roof-replacement", Decimal("0.99")),),
        non_offer_candidates=(),
        unresolved_signals=(),
        ambiguity_reason=None,
        interpreter="test",
        interpreter_version="1",
    )
    data.update(overrides)
    return SemanticAssessment(**data)


def test_normalization_is_nfkc_casefold_and_whitespace_only():
    assert normalize_query("  ＲＯＯＦ   Replacement  ") == "roof replacement"


def test_blank_query_rejected():
    with pytest.raises(ValueError, match="blank"):
        normalize_query("   ")


def test_semantic_assessment_rejects_normalization_drift():
    with pytest.raises(ValueError, match="normalized_query"):
        assessment(normalized_query="something else")


def test_ambiguous_requires_reason():
    with pytest.raises(ValueError, match="ambiguity_reason"):
        assessment(status=AssessmentStatus.AMBIGUOUS, ambiguity_reason=None)


def test_duplicate_intent_categories_rejected():
    with pytest.raises(ValueError, match="unique"):
        assessment(
            intents=(
                IntentHypothesis(IntentCategory.FREE, Decimal("0.9")),
                IntentHypothesis(IntentCategory.FREE, Decimal("0.8")),
            )
        )


def test_direct_confirmed_offer_is_relevant_when_no_unresolved_modifier():
    result = BusinessFitEvaluator().evaluate(assessment(), truth())
    assert result.disposition is FitDisposition.RELEVANT
    assert result.decisive_offer_ids == ("roof-replacement",)


def test_unknown_modifier_blocks_positive_decision():
    result = BusinessFitEvaluator().evaluate(
        assessment(unresolved_signals=("unknown qualifier: wholesale-like term",)),
        truth(),
    )
    assert result.disposition is FitDisposition.UNKNOWN
    assert result.reasons[0].code is FitReasonCode.UNRESOLVED_SIGNAL


def test_employment_deny_can_make_matching_offer_irrelevant():
    employment = IntentPolicy(
        policy_id="jobs",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="No recruiting through customer acquisition campaigns",
        basis=confirmed("owner"),
    )
    a = assessment(
        raw_query="roof replacement jobs",
        normalized_query="roof replacement jobs",
        intents=(IntentHypothesis(IntentCategory.EMPLOYMENT, Decimal("0.99")),),
    )
    result = BusinessFitEvaluator().evaluate(a, truth(policies=(employment,)))
    assert result.disposition is FitDisposition.IRRELEVANT
    assert result.decisive_intents == (IntentCategory.EMPLOYMENT,)


def test_missing_free_policy_is_unknown_not_bad():
    a = assessment(
        raw_query="free roof replacement",
        normalized_query="free roof replacement",
        intents=(IntentHypothesis(IntentCategory.FREE, Decimal("0.99")),),
    )
    result = BusinessFitEvaluator().evaluate(a, truth())
    assert result.disposition is FitDisposition.UNKNOWN
    assert any(x.code is FitReasonCode.MISSING_INTENT_POLICY for x in result.reasons)


def test_free_offer_specific_allow_can_keep_query_relevant():
    free = IntentPolicy(
        policy_id="free-roof",
        category=IntentCategory.FREE,
        disposition=PolicyDisposition.ALLOW,
        reason="Free roof inspection/estimate is an acquisition offer",
        basis=confirmed("owner"),
        offer_ids=("roof-replacement",),
    )
    a = assessment(
        raw_query="free roof replacement",
        normalized_query="free roof replacement",
        intents=(IntentHypothesis(IntentCategory.FREE, Decimal("0.99")),),
    )
    result = BusinessFitEvaluator().evaluate(a, truth(policies=(free,)))
    assert result.disposition is FitDisposition.RELEVANT


def test_conditional_intent_never_becomes_irrelevant_here():
    competitor = IntentPolicy(
        policy_id="competitor",
        category=IntentCategory.COMPETITOR,
        disposition=PolicyDisposition.CONDITIONAL,
        reason="Comparison traffic can be valuable",
        condition="Review competitor and campaign",
        basis=confirmed("owner"),
    )
    a = assessment(
        intents=(IntentHypothesis(IntentCategory.COMPETITOR, Decimal("0.99")),)
    )
    result = BusinessFitEvaluator().evaluate(a, truth(policies=(competitor,)))
    assert result.disposition is FitDisposition.CONDITIONAL


def test_low_confidence_semantics_stays_unknown():
    a = assessment(
        offer_candidates=(OfferHypothesis("roof-replacement", Decimal("0.81")),)
    )
    result = BusinessFitEvaluator().evaluate(a, truth())
    assert result.disposition is FitDisposition.UNKNOWN
    assert result.reasons[0].code is FitReasonCode.LOW_SEMANTIC_CONFIDENCE


def test_confirmed_explicit_non_offer_is_irrelevant():
    solar = ExplicitNonOffer(
        exclusion_id="solar",
        name="Solar installation",
        aliases=("solar panels",),
        reason="Business does not install solar",
        basis=confirmed("owner"),
    )
    a = assessment(
        raw_query="solar installation",
        normalized_query="solar installation",
        offer_candidates=(),
        non_offer_candidates=(NonOfferHypothesis("solar", Decimal("0.99")),),
    )
    result = BusinessFitEvaluator().evaluate(a, truth(non_offers=(solar,)))
    assert result.disposition is FitDisposition.IRRELEVANT
    assert result.can_support_exclusion_candidate is True


def test_unknown_model_business_id_is_rejected_at_boundary():
    payload = {
        "raw_query": "roof thing",
        "status": "resolved",
        "language_code": "en",
        "intents": [],
        "offer_candidates": [{"offer_id": "invented", "confidence": "0.99"}],
        "non_offer_candidates": [],
        "unresolved_signals": [],
        "interpreter": "future-model",
        "interpreter_version": "x",
    }
    with pytest.raises(ValueError, match="unknown business IDs"):
        assessment_from_mapping(payload, truth())


def test_mapping_rejects_unknown_intent_enum():
    payload = {
        "raw_query": "roof thing",
        "status": "resolved",
        "language_code": "en",
        "intents": [{"category": "made_up_intent", "confidence": "0.99"}],
        "offer_candidates": [],
        "non_offer_candidates": [],
        "unresolved_signals": [],
        "interpreter": "future-model",
        "interpreter_version": "x",
    }
    with pytest.raises(ValueError):
        assessment_from_mapping(payload, truth())


def test_context_for_model_contains_no_performance_data():
    context = semantic_context_for_model(truth())
    operational_context = {k: v for k, v in context.items() if k != "forbidden_inputs"}
    serialized = repr(operational_context).casefold()
    for forbidden in ("cost_micros", "conversion_value", "metrics", "cpa", "roas"):
        assert forbidden not in serialized
    assert set(context["forbidden_inputs"]) >= {"spend", "clicks", "conversions", "cpa", "roas"}


def test_lexical_baseline_detects_jobs_and_offer_without_financial_data():
    p = IntentPolicy(
        policy_id="jobs",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="Not recruiting",
        basis=confirmed("owner"),
    )
    t = truth(policies=(p,))
    a = ConservativeLexicalInterpreter().interpret("Roof replacement JOBS", t)
    assert a.status is AssessmentStatus.RESOLVED
    assert a.offer_candidates[0].offer_id == "roof-replacement"
    assert a.intents[0].category is IntentCategory.EMPLOYMENT
    assert BusinessFitEvaluator().evaluate(a, t).disposition is FitDisposition.IRRELEVANT


def test_lexical_baseline_refuses_to_guess_unknown_query():
    a = ConservativeLexicalInterpreter().interpret("best option near me", truth())
    assert a.status is AssessmentStatus.INSUFFICIENT
    result = BusinessFitEvaluator().evaluate(a, truth())
    assert result.disposition is FitDisposition.UNKNOWN


def test_irrelevance_is_semantic_candidate_not_negative_keyword_action():
    employment = IntentPolicy(
        policy_id="jobs",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="No recruiting",
        basis=confirmed("owner"),
    )
    a = assessment(
        raw_query="roof replacement jobs",
        normalized_query="roof replacement jobs",
        intents=(IntentHypothesis(IntentCategory.EMPLOYMENT, Decimal("0.99")),),
    )
    result = BusinessFitEvaluator().evaluate(a, truth(policies=(employment,)))
    assert result.can_support_exclusion_candidate is True
    # Phase 3 intentionally has no negative-keyword match type/scope/action field.
    assert not hasattr(result, "negative_keyword")
    assert not hasattr(result, "match_type")
