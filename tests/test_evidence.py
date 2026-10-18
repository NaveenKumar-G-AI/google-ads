from datetime import date
from decimal import Decimal

import pytest

from recovery.accuracy import AccuracyPolicy
from recovery.domain import CoverageSummary, SearchTermObservation
from recovery.evidence import (
    EvidenceDisposition,
    EvidenceReasonCode,
    WasteEvidenceEngine,
    summarize_recovery_evidence,
)
from recovery.search_intent import (
    AssessmentStatus,
    BusinessFitDecision,
    FitDisposition,
    FitReason,
    FitReasonCode,
    IntentHypothesis,
    SemanticAssessment,
)
from recovery.business_truth import IntentCategory


TRUTH_HASH = "a" * 64
AS_OF = date(2026, 10, 15)


def assessment(query: str = "roof replacement jobs", confidence: str = "0.99") -> SemanticAssessment:
    return SemanticAssessment(
        raw_query=query,
        normalized_query=query.casefold(),
        status=AssessmentStatus.RESOLVED,
        language_code="en",
        intents=(IntentHypothesis(IntentCategory.EMPLOYMENT, Decimal(confidence)),),
        offer_candidates=(),
        non_offer_candidates=(),
        unresolved_signals=(),
        ambiguity_reason=None,
        interpreter="test",
        interpreter_version="1",
    )


def fit(query: str = "roof replacement jobs", disposition: FitDisposition = FitDisposition.IRRELEVANT) -> BusinessFitDecision:
    return BusinessFitDecision(
        raw_query=query,
        disposition=disposition,
        semantic_status=AssessmentStatus.RESOLVED,
        truth_fingerprint=TRUTH_HASH,
        reasons=(
            FitReason(FitReasonCode.DENIED_INTENT, "Employment denied", True),
        ),
        decisive_intents=(IntentCategory.EMPLOYMENT,) if disposition is FitDisposition.IRRELEVANT else (),
    )


def row(
    *,
    day: date = date(2026, 9, 1),
    cost: int = 5_000_000,
    clicks: int = 10,
    conversions: str = "0",
    all_conversions: str = "0",
    conversion_value: str = "0",
    all_conversion_value: str = "0",
    status: str = "NONE",
    query: str = "roof replacement jobs",
    campaign_id: str = "10",
    ad_group_id: str = "20",
    network: str = "SEARCH",
) -> SearchTermObservation:
    return SearchTermObservation(
        customer_id="1",
        campaign_id=campaign_id,
        campaign_name="Search",
        ad_group_id=ad_group_id,
        ad_group_name="Roofing",
        search_term=query,
        date=day,
        network=network,
        match_source="ADVERTISER_PROVIDED_KEYWORD",
        search_term_match_type="BROAD",
        targeting_status=status,
        triggering_keyword="roof replacement",
        triggering_keyword_match_type="BROAD",
        impressions=max(clicks, 20),
        clicks=clicks,
        cost_micros=cost,
        conversions=Decimal(conversions),
        conversions_value=Decimal(conversion_value),
        all_conversions=Decimal(all_conversions),
        all_conversions_value=Decimal(all_conversion_value),
        currency_code="USD",
    )


def coverage(visible: int = 80_000_000, total: int = 100_000_000) -> CoverageSummary:
    return CoverageSummary(visible, total, "USD")


def engine(lag_days: int = 14) -> WasteEvidenceEngine:
    return WasteEvidenceEngine(AccuracyPolicy(conversion_lag_days=lag_days))


def evaluate(rows, *, a=None, f=None, c=None):
    return engine().evaluate(
        assessment=a or assessment(),
        fit=f or fit(),
        truth_fingerprint=TRUTH_HASH,
        observations=rows,
        coverage=c or coverage(),
        as_of=AS_OF,
    )


def test_mature_semantic_mismatch_without_conversion_signal_is_candidate():
    result = evaluate([row(cost=7_000_000)])
    assert result.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE
    assert result.potentially_avoidable_cost_micros == 7_000_000
    assert result.mature_cost_micros == 7_000_000


def test_immature_spend_is_not_in_candidate_amount():
    result = evaluate(
        [
            row(day=date(2026, 9, 1), cost=7_000_000),
            row(day=date(2026, 10, 10), cost=3_000_000),
        ]
    )
    assert result.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE
    assert result.potentially_avoidable_cost_micros == 7_000_000
    assert result.immature_cost_micros == 3_000_000
    assert any(r.code is EvidenceReasonCode.IMMATURE_SPEND_PRESENT for r in result.reasons)


def test_only_immature_spend_routes_to_review():
    result = evaluate([row(day=date(2026, 10, 10), cost=3_000_000)])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED
    assert result.potentially_avoidable_cost_micros == 0


def test_primary_conversion_signal_blocks_automatic_money_claim():
    result = evaluate([row(conversions="1")])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED
    assert any(r.code is EvidenceReasonCode.CONVERSION_SIGNAL_PRESENT for r in result.reasons)


def test_secondary_all_conversion_signal_also_blocks_until_quality_is_known():
    result = evaluate([row(all_conversions="1")])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED


def test_conversion_value_signal_blocks_even_if_count_is_zero():
    result = evaluate([row(conversion_value="100")])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED


def test_currently_excluded_is_historical_not_new_recovery():
    result = evaluate([row(status="EXCLUDED")])
    assert result.disposition is EvidenceDisposition.ALREADY_ADDRESSED
    assert result.potentially_avoidable_cost_micros == 0
    assert result.observed_mismatch_cost_micros == 5_000_000


def test_unknown_targeting_status_routes_to_review():
    result = evaluate([row(status="UNKNOWN")])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED


def test_relevant_query_cannot_become_waste_from_bad_performance():
    relevant = fit(disposition=FitDisposition.RELEVANT)
    result = evaluate([row(cost=100_000_000)], f=relevant)
    assert result.disposition is EvidenceDisposition.NOT_SUPPORTED
    assert result.potentially_avoidable_cost_micros == 0


def test_low_semantic_support_routes_to_review_not_money_claim():
    low = assessment(confidence="0.90")
    result = evaluate([row()], a=low)
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED
    assert any(r.code is EvidenceReasonCode.LOW_SEMANTIC_SUPPORT for r in result.reasons)


def test_query_mismatch_is_rejected_not_silently_merged():
    with pytest.raises(ValueError, match="assessed query"):
        evaluate([row(query="roof replacement salary")])


def test_cross_ad_group_rows_must_not_be_aggregated_together():
    with pytest.raises(ValueError, match="one customer/campaign/ad-group/network"):
        evaluate([row(ad_group_id="20"), row(day=date(2026, 9, 2), ad_group_id="21")])


def test_duplicate_source_rows_are_rejected_to_prevent_double_counting():
    r = row()
    with pytest.raises(ValueError, match="double-count"):
        evaluate([r, r])


def test_future_observation_is_rejected():
    with pytest.raises(ValueError, match="after as_of"):
        evaluate([row(day=date(2026, 10, 16))])


def test_summary_never_extrapolates_unobserved_spend():
    finding = evaluate([row(cost=8_000_000)])
    c = coverage(visible=80_000_000, total=100_000_000)
    result = summarize_recovery_evidence([finding], c)
    assert result.potentially_avoidable_observed_cost_micros == 8_000_000
    assert result.unobserved_search_cost_micros == 20_000_000
    assert result.extrapolated_hidden_waste_micros == 0
    assert "observed" in result.account_claim


def test_low_coverage_does_not_inflate_individual_observed_amount():
    c = coverage(visible=30_000_000, total=100_000_000)
    finding = evaluate([row(cost=4_000_000)], c=c)
    result = summarize_recovery_evidence([finding], c)
    assert result.potentially_avoidable_observed_cost_micros == 4_000_000
    assert result.unobserved_search_cost_micros == 70_000_000
    assert result.extrapolated_hidden_waste_micros == 0


def test_summary_rejects_overlapping_findings_to_prevent_double_counting():
    finding = evaluate([row(cost=8_000_000)])
    with pytest.raises(ValueError, match="overlap"):
        summarize_recovery_evidence([finding, finding], coverage())


def test_zero_cost_mismatch_is_not_presented_as_recoverable_money():
    result = evaluate([row(cost=0, clicks=0)])
    assert result.disposition is EvidenceDisposition.NOT_SUPPORTED
    assert result.potentially_avoidable_cost_micros == 0


def test_truth_snapshot_mismatch_is_rejected():
    with pytest.raises(ValueError, match="different truth snapshot"):
        engine().evaluate(
            assessment=assessment(),
            fit=fit(),
            truth_fingerprint="b" * 64,
            observations=[row()],
            coverage=coverage(),
            as_of=AS_OF,
        )


def test_summary_rejects_evidence_window_that_exceeds_visible_coverage():
    finding = evaluate([row(cost=8_000_000)])
    too_small = coverage(visible=7_000_000, total=10_000_000)
    # Re-evaluate with same coverage band so the window mismatch is caught by spend.
    finding = evaluate([row(cost=8_000_000)], c=too_small)
    with pytest.raises(ValueError, match="exceeds visible"):
        summarize_recovery_evidence([finding], too_small)


def test_negative_conversion_adjustment_signal_also_blocks_automatic_claim():
    result = evaluate([row(conversions="-1")])
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED


def test_mixed_targeting_statuses_route_to_review():
    result = evaluate(
        [
            row(day=date(2026, 9, 1), status="NONE"),
            row(day=date(2026, 9, 2), status="EXCLUDED"),
        ]
    )
    assert result.disposition is EvidenceDisposition.REVIEW_REQUIRED
    assert any(r.code is EvidenceReasonCode.TARGETING_STATUS_UNCERTAIN for r in result.reasons)
