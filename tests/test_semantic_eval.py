from datetime import datetime, timezone
from decimal import Decimal

import pytest

from recovery.business_truth import (
    BusinessTruthSnapshot,
    CatalogCompleteness,
    CommercialModel,
    EvidenceKind,
    EvidenceRef,
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
    FitDisposition,
    IntentHypothesis,
    OfferHypothesis,
    SemanticAssessment,
)
from recovery.semantic_eval import (
    CandidatePrediction,
    DatasetSplit,
    GoldSemanticCase,
    LabelSource,
    ReleasePolicy,
    SemanticEvaluator,
    choose_threshold_from_calibration,
    dataset_fingerprint,
    gate_release,
    validate_split_isolation,
    wilson_upper,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)


def confirmed() -> TruthBasis:
    return TruthBasis(
        status=TruthStatus.CONFIRMED,
        evidence_ids=("owner",),
        confirmed_by="owner@test",
        confirmed_at=NOW,
    )


def make_truth() -> BusinessTruthSnapshot:
    ev = EvidenceRef("owner", EvidenceKind.OPERATOR, "owner confirmation", NOW)
    offer = Offer(
        "roof-replacement",
        "Roof replacement",
        ("new roof",),
        "Residential roof replacement",
        CommercialModel.QUOTE_BASED,
        OfferStatus.ACTIVE,
        confirmed(),
    )
    jobs = IntentPolicy(
        "jobs",
        IntentCategory.EMPLOYMENT,
        PolicyDisposition.DENY,
        "Recruitment traffic is not a customer-acquisition goal",
        confirmed(),
    )
    return BusinessTruthSnapshot(
        business_id="biz",
        business_name="Accurate Roofing",
        version=1,
        created_at=NOW,
        created_by="owner@test",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(offer,),
        intent_policies=(jobs,),
        evidence=(ev,),
    )


def case(case_id: str, query: str, truth: BusinessTruthSnapshot, expected: FitDisposition, *, split=DatasetSplit.TEST, lang="en", status=AssessmentStatus.RESOLVED, reviewers=2):
    return GoldSemanticCase(
        case_id=case_id,
        raw_query=query,
        truth_fingerprint=truth.fingerprint_sha256,
        expected_disposition=expected,
        expected_status=status,
        language_code=lang,
        split=split,
        label_source=LabelSource.DOUBLE_REVIEW,
        reviewer_count=reviewers,
    )


def pred(case_id: str, query: str, *, offer=True, employment=False, status=AssessmentStatus.RESOLVED, confidence="0.99", declared="0.99"):
    return CandidatePrediction(
        case_id,
        SemanticAssessment(
            raw_query=query,
            normalized_query=query.casefold(),
            status=status,
            language_code="en",
            intents=((IntentHypothesis(IntentCategory.EMPLOYMENT, Decimal(confidence)),) if employment else ()),
            offer_candidates=((OfferHypothesis("roof-replacement", Decimal(confidence)),) if offer else ()),
            non_offer_candidates=(),
            unresolved_signals=(),
            ambiguity_reason=None,
            interpreter="candidate",
            interpreter_version="1",
        ),
        Decimal(declared) if declared is not None else None,
    )


def test_irrelevant_gold_requires_two_reviewers():
    t = make_truth()
    with pytest.raises(ValueError, match="at least two"):
        case("x", "roof jobs", t, FitDisposition.IRRELEVANT, reviewers=1)


def test_dataset_fingerprint_order_independent():
    t = make_truth()
    a = case("a", "roof replacement", t, FitDisposition.RELEVANT)
    b = case("b", "roof replacement jobs", t, FitDisposition.IRRELEVANT)
    assert dataset_fingerprint([a, b]) == dataset_fingerprint([b, a])


def test_split_leakage_detected_by_query_and_truth_not_case_id():
    t = make_truth()
    a = case("a", "roof replacement", t, FitDisposition.RELEVANT, split=DatasetSplit.CALIBRATION)
    b = case("b", "roof replacement", t, FitDisposition.RELEVANT, split=DatasetSplit.TEST)
    with pytest.raises(ValueError, match="leakage"):
        validate_split_isolation([a, b])


def test_same_query_different_truth_fingerprint_can_exist_across_splits():
    t1 = make_truth()
    # Different truth version/fingerprint.
    t2 = BusinessTruthSnapshot(
        business_id=t1.business_id,
        business_name=t1.business_name,
        version=2,
        created_at=NOW,
        created_by=t1.created_by,
        offer_catalog_completeness=t1.offer_catalog_completeness,
        audience_catalog_completeness=t1.audience_catalog_completeness,
        offers=t1.offers,
        intent_policies=t1.intent_policies,
        evidence=t1.evidence,
        supersedes_version=1,
    )
    a = case("a", "roof replacement", t1, FitDisposition.RELEVANT, split=DatasetSplit.CALIBRATION)
    b = case("b", "roof replacement", t2, FitDisposition.RELEVANT, split=DatasetSplit.TEST)
    validate_split_isolation([a, b])


def test_unsafe_false_exclusion_is_counted_separately():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    # Employment causes business evaluator to mark irrelevant, making this a dangerous false exclusion.
    predictions = [pred("1", "roof replacement", employment=True)]
    report = SemanticEvaluator().evaluate(
        model_id="m", model_version="1", cases=gold, predictions=predictions,
        truths={t.fingerprint_sha256: t},
    )
    assert report.unsafe_false_exclusions == 1
    assert report.predicted_irrelevant == 1
    assert report.irrelevant_precision == Decimal(0)


def test_unknown_is_abstention_not_false_exclusion():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    predictions = [pred("1", "roof replacement", offer=False, status=AssessmentStatus.INSUFFICIENT, declared="0.4")]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    assert report.unsafe_false_exclusions == 0
    assert report.abstention_rate == Decimal(1)


def test_missing_prediction_is_rejected_not_silently_dropped():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    with pytest.raises(ValueError, match="missing predictions"):
        SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=[], truths={t.fingerprint_sha256: t})


def test_prediction_query_must_match_gold_exactly():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    with pytest.raises(ValueError, match="query mismatch"):
        SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=[pred("1", "different")], truths={t.fingerprint_sha256: t})


def test_missing_truth_snapshot_rejected():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    with pytest.raises(ValueError, match="missing Business Truth"):
        SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=[pred("1", "roof replacement")], truths={})


def test_language_slices_do_not_average_away_errors():
    t = make_truth()
    gold = [
        case("1", "roof replacement", t, FitDisposition.RELEVANT, lang="en"),
        case("2", "roof replacement jobs", t, FitDisposition.IRRELEVANT, lang="ta"),
    ]
    predictions = [pred("1", "roof replacement"), pred("2", "roof replacement jobs", employment=True)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    assert {x.name for x in report.language_slices} == {"en", "ta"}
    assert all(x.support == 1 for x in report.language_slices)


def test_confidence_calibration_computes_brier_and_ece():
    t = make_truth()
    gold = [
        case("1", "roof replacement", t, FitDisposition.RELEVANT),
        case("2", "roof replacement jobs", t, FitDisposition.IRRELEVANT),
    ]
    predictions = [pred("1", "roof replacement", declared="0.9"), pred("2", "roof replacement jobs", employment=True, declared="0.9")]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    assert report.calibration.support == 2
    assert report.calibration.brier_score == Decimal("0.01")
    assert report.calibration.expected_calibration_error == Decimal("0.1")


def test_no_confidence_does_not_fake_calibration():
    t = make_truth()
    gold = [case("1", "roof replacement", t, FitDisposition.RELEVANT)]
    predictions = [pred("1", "roof replacement", declared=None)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    assert report.calibration.support == 0
    assert report.calibration.expected_calibration_error is None


def test_wilson_upper_nonzero_even_with_zero_observed_errors():
    upper = wilson_upper(0, 10)
    assert upper is not None
    assert upper > 0
    assert upper > Decimal("0.2")


def test_wilson_upper_shrinks_with_more_support():
    assert wilson_upper(0, 1000) < wilson_upper(0, 100)


def test_choose_threshold_uses_safety_and_precision():
    t = make_truth()
    gold = []
    predictions = []
    # 30 correct irrelevant predictions at 0.95 and 5 false exclusions at 0.80.
    for i in range(30):
        q = f"roof replacement jobs {i}"
        gold.append(case(f"g{i}", q, t, FitDisposition.IRRELEVANT, split=DatasetSplit.CALIBRATION))
        predictions.append(pred(f"g{i}", q, employment=True, declared="0.95"))
    for i in range(5):
        q = f"roof replacement {i}"
        gold.append(case(f"b{i}", q, t, FitDisposition.RELEVANT, split=DatasetSplit.CALIBRATION))
        predictions.append(pred(f"b{i}", q, employment=True, declared="0.80"))
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t}, split=DatasetSplit.CALIBRATION)
    threshold = choose_threshold_from_calibration(report, minimum_negative_actions=25)
    assert threshold == Decimal("0.90")


def test_release_gate_fails_tiny_dataset_even_with_zero_errors():
    t = make_truth()
    gold = [case("1", "roof replacement jobs", t, FitDisposition.IRRELEVANT)]
    predictions = [pred("1", "roof replacement jobs", employment=True)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    result = gate_release(report, policy=ReleasePolicy(), selected_confidence_threshold=Decimal("0.95"))
    assert result.passed is False
    assert any(x.name == "test_support" and not x.passed for x in result.checks)


def test_release_gate_requires_language_support_when_configured():
    t = make_truth()
    gold = [case("1", "roof replacement jobs", t, FitDisposition.IRRELEVANT, lang="en")]
    predictions = [pred("1", "roof replacement jobs", employment=True)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    policy = ReleasePolicy(
        minimum_test_cases=1,
        minimum_safety_cases=1,
        minimum_calibration_support=1,
        maximum_ece=Decimal("1"),
        maximum_wilson_upper_unsafe_rate=Decimal("1"),
        minimum_irrelevant_precision=Decimal("0"),
        required_language_slices=("ta",),
        minimum_cases_per_required_language=1,
    )
    result = gate_release(report, policy=policy, selected_confidence_threshold=Decimal("0.95"))
    assert result.passed is False
    assert any(x.name == "language_support:ta" and not x.passed for x in result.checks)


def test_release_gate_requires_selected_threshold():
    t = make_truth()
    gold = [case("1", "roof replacement jobs", t, FitDisposition.IRRELEVANT)]
    predictions = [pred("1", "roof replacement jobs", employment=True)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    policy = ReleasePolicy(
        minimum_test_cases=1,
        minimum_safety_cases=1,
        minimum_calibration_support=1,
        maximum_ece=Decimal("1"),
        maximum_wilson_upper_unsafe_rate=Decimal("1"),
        minimum_irrelevant_precision=Decimal("0"),
    )
    result = gate_release(report, policy=policy, selected_confidence_threshold=None)
    assert result.passed is False
    assert any(x.name == "calibrated_threshold_selected" and not x.passed for x in result.checks)


def test_release_gate_uses_selected_threshold_not_low_confidence_false_exclusion():
    t = make_truth()
    gold = []
    predictions = []
    # High-confidence safe negatives.
    for i in range(25):
        q = f"roof replacement jobs safe {i}"
        gold.append(case(f"s{i}", q, t, FitDisposition.IRRELEVANT))
        predictions.append(pred(f"s{i}", q, employment=True, declared="0.99"))
    # Low-confidence false exclusion must be abstained by the selected 0.95 threshold.
    gold.append(case("bad", "roof replacement", t, FitDisposition.RELEVANT))
    predictions.append(pred("bad", "roof replacement", employment=True, declared="0.60"))
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    policy = ReleasePolicy(
        minimum_test_cases=1,
        minimum_safety_cases=25,
        minimum_calibration_support=1,
        maximum_ece=Decimal("1"),
        maximum_wilson_upper_unsafe_rate=Decimal("1"),
        minimum_irrelevant_precision=Decimal("0.99"),
    )
    result = gate_release(report, policy=policy, selected_confidence_threshold=Decimal("0.95"))
    assert result.passed is True


def test_required_tag_slice_is_enforced():
    t = make_truth()
    gold = [GoldSemanticCase(
        "1", "roof replacement jobs", t.fingerprint_sha256,
        FitDisposition.IRRELEVANT, AssessmentStatus.RESOLVED, "en",
        DatasetSplit.TEST, LabelSource.DOUBLE_REVIEW, 2,
        tags=("truth_counterfactual",),
    )]
    predictions = [pred("1", "roof replacement jobs", employment=True)]
    report = SemanticEvaluator().evaluate(model_id="m", model_version="1", cases=gold, predictions=predictions, truths={t.fingerprint_sha256: t})
    assert report.tag_slices[0].name == "truth_counterfactual"
    policy = ReleasePolicy(
        minimum_test_cases=1, minimum_safety_cases=1,
        minimum_calibration_support=1, maximum_ece=Decimal("1"),
        maximum_wilson_upper_unsafe_rate=Decimal("1"),
        minimum_irrelevant_precision=Decimal("0"),
        required_tag_slices=("truth_counterfactual",),
        minimum_cases_per_required_tag=2,
    )
    result = gate_release(report, policy=policy, selected_confidence_threshold=Decimal("0.95"))
    assert result.passed is False
    assert any(x.name == "tag_support:truth_counterfactual" and not x.passed for x in result.checks)


def test_gold_jsonl_round_trip_preserves_unicode_and_tags():
    from recovery.semantic_eval import gold_cases_from_jsonl, gold_cases_to_jsonl
    t = make_truth()
    original = [GoldSemanticCase(
        "ta1", "கூரை வேலை", t.fingerprint_sha256,
        FitDisposition.UNKNOWN, AssessmentStatus.INSUFFICIENT, "ta",
        DatasetSplit.TEST, LabelSource.ADJUDICATED, 2,
        notes="Tamil ambiguity", tags=("multilingual", "ambiguous"),
    )]
    encoded = gold_cases_to_jsonl(original)
    decoded = gold_cases_from_jsonl(encoded)
    assert decoded == tuple(original)


def test_gold_jsonl_rejects_split_leakage():
    from recovery.semantic_eval import gold_cases_from_jsonl, gold_cases_to_jsonl
    t = make_truth()
    a = case("a", "roof replacement", t, FitDisposition.RELEVANT, split=DatasetSplit.CALIBRATION)
    b = case("b", "roof replacement", t, FitDisposition.RELEVANT, split=DatasetSplit.TEST)
    with pytest.raises(ValueError, match="leakage"):
        gold_cases_from_jsonl(gold_cases_to_jsonl([a, b]))
