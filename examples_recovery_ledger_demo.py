from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from datetime import date, datetime, timezone
from decimal import Decimal

from recovery.accuracy import AccuracyPolicy
from recovery.domain import CoverageBand
from recovery.evidence import EvidenceDisposition, SearchTermEvidence, SearchTermEvidenceKey
from recovery.negative_keywords import ApprovalRecord, NegativeMatchType, SafeNegativeKeywordEngine, ScopeEvidenceBundle, build_mutation_plan
from recovery.recovery_ledger import ConfigurationVerification, ExperimentOutcomeMetric, ExperimentReport, RecoveryVerificationEngine

finding = SearchTermEvidence(
    key=SearchTermEvidenceKey("1", "10", "20", "roof replacement jobs", "SEARCH"),
    raw_query_examples=("roof replacement jobs",),
    truth_fingerprint="a" * 64,
    disposition=EvidenceDisposition.POTENTIALLY_AVOIDABLE,
    reasons=(), coverage_band=CoverageBand.HIGH,
    semantic_support=Decimal("0.99"), currency_code="USD",
    mature_cost_micros=8_500_000, immature_cost_micros=0,
    mature_clicks=12, immature_clicks=0,
    mature_conversions=Decimal("0"), mature_conversion_value=Decimal("0"),
    mature_all_conversions=Decimal("0"), mature_all_conversion_value=Decimal("0"),
    first_observation_date=date(2026, 9, 1), last_observation_date=date(2026, 9, 30),
    observation_ids=("obs-1",), targeting_statuses=("NONE",),
)
proposal = SafeNegativeKeywordEngine().propose_exact_from_evidence(
    bundle=ScopeEvidenceBundle((finding,), True, "snap-1")
)
approval = ApprovalRecord(
    proposal.proposal_id, proposal.fingerprint_sha256, "owner",
    datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
)
plan = build_mutation_plan(proposal, approval)
engine = RecoveryVerificationEngine(AccuracyPolicy(conversion_lag_days=7))
action = engine.record_applied_change(
    proposal=proposal, approval=approval, plan=plan,
    resource_name="customers/1/adGroupCriteria/20~123",
    applied_at=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
    applied_by="owner", validate_only_passed=True,
)
baseline = engine.build_baseline(
    proposal=proposal, window_start=date(2026, 9, 1), window_end=date(2026, 9, 30)
)
projection = engine.project_run_rate(
    baseline=baseline, action=action,
    projection_start=date(2026, 10, 2), projection_end=date(2026, 10, 11),
)
post = engine.observe_post_change(
    action=action, currency_code="USD",
    window_start=date(2026, 10, 2), window_end=date(2026, 10, 8), as_of=date(2026, 10, 15),
    exact_query_cost_micros=0, exact_query_clicks=0,
    scope_cost_micros=50_000_000, scope_clicks=500,
)
config = ConfigurationVerification(
    resource_name=action.resource_name,
    checked_at=datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc),
    exists=True, negative=True, keyword_text=action.keyword_text,
    match_type=NegativeMatchType.EXACT,
    customer_id="1", campaign_id="10", ad_group_id="20",
)

# This synthetic experiment passes the intentionally strict Phase-6 gates.
report = ExperimentReport(
    experiment_id="999", currency_code="USD",
    window_start=date(2026, 9, 1), window_end=date(2026, 9, 30),
    control_traffic_percent=Decimal("50"), treatment_traffic_percent=Decimal("50"),
    treatment_cost_micros=70_000_000, control_cost_micros=100_000_000,
    cost_change_point_estimate=Decimal("-0.30"), cost_change_margin_of_error=Decimal("0.10"), cost_p_value=Decimal("0.01"),
    treatment_conversions=Decimal("130"), control_conversions=Decimal("100"),
    conversions_absolute_change_point_estimate=Decimal("30"), conversions_absolute_change_margin_of_error=Decimal("10"), conversions_p_value=Decimal("0.01"),
    treatment_conversion_value_per_cost=Decimal("2.2"), control_conversion_value_per_cost=Decimal("1.5"),
    conversion_value_per_cost_change_point_estimate=Decimal("0.46"), conversion_value_per_cost_margin_of_error=Decimal("0.15"), conversion_value_per_cost_p_value=Decimal("0.01"),
)
causal = engine.verify_experiment(
    report=report, as_of=date(2026, 10, 15),
    business_outcome_quality_validated=True,
    outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
)
ledger = engine.summarize(
    baseline=baseline, action=action, configuration=config,
    projection=projection, post_change=post, causal=causal,
)

print("Historical candidate:", ledger.historical_candidate.format())
print("Projected prevented:", ledger.projected_prevented.format(), "(NOT verified recovery)")
print("Post-change exact query spend:", post.exact_query_cost.format())
print("Post-change status:", post.status.value)
print("Causal status:", causal.status.value)
print("Verified recovery headline:", ledger.verified_recovery.format())
print("Ledger fingerprint:", ledger.fingerprint_sha256)
