from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from decimal import Decimal

from recovery.accuracy import AccuracyPolicy
from recovery.business_truth import IntentCategory
from recovery.domain import CoverageSummary, SearchTermObservation
from recovery.evidence import WasteEvidenceEngine, summarize_recovery_evidence
from recovery.search_intent import (
    AssessmentStatus,
    BusinessFitDecision,
    FitDisposition,
    FitReason,
    FitReasonCode,
    IntentHypothesis,
    SemanticAssessment,
)

truth_hash = "a" * 64
assessment = SemanticAssessment(
    raw_query="roof replacement jobs",
    normalized_query="roof replacement jobs",
    status=AssessmentStatus.RESOLVED,
    language_code="en",
    intents=(IntentHypothesis(IntentCategory.EMPLOYMENT, Decimal("0.99")),),
    offer_candidates=(),
    non_offer_candidates=(),
    unresolved_signals=(),
    ambiguity_reason=None,
    interpreter="demo",
    interpreter_version="1",
)
fit = BusinessFitDecision(
    raw_query="roof replacement jobs",
    disposition=FitDisposition.IRRELEVANT,
    semantic_status=AssessmentStatus.RESOLVED,
    truth_fingerprint=truth_hash,
    reasons=(FitReason(FitReasonCode.DENIED_INTENT, "Employment intent denied", True),),
    decisive_intents=(IntentCategory.EMPLOYMENT,),
)
row = SearchTermObservation(
    customer_id="1",
    campaign_id="10",
    campaign_name="Roof Search",
    ad_group_id="20",
    ad_group_name="Replacement",
    search_term="roof replacement jobs",
    date=date(2026, 9, 1),
    network="SEARCH",
    match_source="ADVERTISER_PROVIDED_KEYWORD",
    search_term_match_type="BROAD",
    targeting_status="NONE",
    triggering_keyword="roof replacement",
    triggering_keyword_match_type="BROAD",
    impressions=100,
    clicks=14,
    cost_micros=8_500_000,
    conversions=Decimal("0"),
    conversions_value=Decimal("0"),
    all_conversions=Decimal("0"),
    all_conversions_value=Decimal("0"),
    currency_code="USD",
)
coverage = CoverageSummary(
    visible_search_term_cost_micros=80_000_000,
    eligible_search_campaign_cost_micros=100_000_000,
    currency_code="USD",
)
engine = WasteEvidenceEngine(AccuracyPolicy(conversion_lag_days=14))
finding = engine.evaluate(
    assessment=assessment,
    fit=fit,
    truth_fingerprint=truth_hash,
    observations=[row],
    coverage=coverage,
    as_of=date(2026, 10, 15),
)
summary = summarize_recovery_evidence([finding], coverage)

print("Disposition:", finding.disposition.value)
print("Observed candidate:", finding.mature_cost.format())
print("Unobserved search spend (NOT extrapolated):", summary.unobserved_search_cost.format())
print("Hidden-waste extrapolation:", summary.extrapolated_hidden_waste_micros)
