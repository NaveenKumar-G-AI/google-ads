from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from recovery.accuracy import AccuracyPolicy
from recovery.domain import CoverageBand
from recovery.evidence import EvidenceDisposition, SearchTermEvidence, SearchTermEvidenceKey
from recovery.negative_keywords import (
    ApprovalRecord,
    NegativeMatchType,
    ProposalDisposition,
    SafeNegativeKeywordEngine,
    ScopeEvidenceBundle,
    build_mutation_plan,
)
from recovery.recovery_ledger import (
    CausalVerificationStatus,
    ConfigurationVerification,
    ExperimentOutcomeMetric,
    ExperimentReport,
    PostChangeStatus,
    RecoveryVerificationEngine,
)


def finding():
    return SearchTermEvidence(
        key=SearchTermEvidenceKey("1", "10", "20", "roof replacement jobs", "SEARCH"),
        raw_query_examples=("roof replacement jobs",),
        truth_fingerprint="a" * 64,
        disposition=EvidenceDisposition.POTENTIALLY_AVOIDABLE,
        reasons=(),
        coverage_band=CoverageBand.HIGH,
        semantic_support=Decimal("0.99"),
        currency_code="USD",
        mature_cost_micros=8_500_000,
        immature_cost_micros=0,
        mature_clicks=12,
        immature_clicks=0,
        mature_conversions=Decimal("0"),
        mature_conversion_value=Decimal("0"),
        mature_all_conversions=Decimal("0"),
        mature_all_conversion_value=Decimal("0"),
        first_observation_date=date(2026, 9, 1),
        last_observation_date=date(2026, 9, 30),
        observation_ids=("obs-1",),
        targeting_statuses=("NONE",),
    )


def action_setup():
    proposal = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=ScopeEvidenceBundle((finding(),), True, "snap-1")
    )
    assert proposal.disposition is ProposalDisposition.READY_FOR_APPROVAL
    approval = ApprovalRecord(
        proposal_id=proposal.proposal_id,
        proposal_fingerprint=proposal.fingerprint_sha256,
        approved_by="owner",
        approved_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    plan = build_mutation_plan(proposal, approval)
    engine = RecoveryVerificationEngine(AccuracyPolicy(conversion_lag_days=7))
    action = engine.record_applied_change(
        proposal=proposal,
        approval=approval,
        plan=plan,
        resource_name="customers/1/adGroupCriteria/20~123",
        applied_at=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
        applied_by="owner",
        validate_only_passed=True,
        api_request_id="req-1",
    )
    baseline = engine.build_baseline(
        proposal=proposal,
        window_start=date(2026, 9, 1),
        window_end=date(2026, 9, 30),
    )
    config = ConfigurationVerification(
        resource_name=action.resource_name,
        checked_at=datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        exists=True,
        negative=True,
        keyword_text="roof replacement jobs",
        match_type=NegativeMatchType.EXACT,
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    return engine, proposal, approval, plan, action, baseline, config


def experiment(**overrides):
    data = dict(
        experiment_id="999",
        currency_code="USD",
        window_start=date(2026, 9, 1),
        window_end=date(2026, 9, 30),
        control_traffic_percent=Decimal("50"),
        treatment_traffic_percent=Decimal("50"),
        treatment_cost_micros=70_000_000,
        control_cost_micros=100_000_000,
        cost_change_point_estimate=Decimal("-0.30"),
        cost_change_margin_of_error=Decimal("0.10"),
        cost_p_value=Decimal("0.01"),
        treatment_conversions=Decimal("130"),
        control_conversions=Decimal("100"),
        conversions_absolute_change_point_estimate=Decimal("30"),
        conversions_absolute_change_margin_of_error=Decimal("10"),
        conversions_p_value=Decimal("0.01"),
        treatment_conversion_value_per_cost=Decimal("2.2"),
        control_conversion_value_per_cost=Decimal("1.5"),
        conversion_value_per_cost_change_point_estimate=Decimal("0.46"),
        conversion_value_per_cost_margin_of_error=Decimal("0.15"),
        conversion_value_per_cost_p_value=Decimal("0.01"),
    )
    data.update(overrides)
    return ExperimentReport(**data)


def test_applied_change_requires_validate_only_passed():
    engine, proposal, approval, plan, *_ = action_setup()
    with pytest.raises(ValueError, match="validate_only"):
        engine.record_applied_change(
            proposal=proposal,
            approval=approval,
            plan=plan,
            resource_name="customers/1/adGroupCriteria/20~1",
            applied_at=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            applied_by="owner",
            validate_only_passed=False,
        )


def test_baseline_is_historical_candidate_not_recovered_money():
    _, _, _, _, _, baseline, _ = action_setup()
    assert baseline.historical_candidate.micros == 8_500_000
    assert baseline.window_days == 30


def test_run_rate_projection_is_labeled_projection_and_floored():
    engine, _, _, _, action, baseline, _ = action_setup()
    p = engine.project_run_rate(
        baseline=baseline,
        action=action,
        projection_start=date(2026, 10, 2),
        projection_end=date(2026, 10, 11),
    )
    assert p.projected_prevented_cost_micros == 2_833_333
    assert "not verified recovery" in p.claim_label


def test_projection_cannot_exceed_baseline_duration():
    engine, _, _, _, action, baseline, _ = action_setup()
    with pytest.raises(ValueError, match="cannot exceed"):
        engine.project_run_rate(
            baseline=baseline,
            action=action,
            projection_start=date(2026, 10, 2),
            projection_end=date(2026, 11, 15),
        )


def test_post_change_zero_query_spend_never_becomes_recovery():
    engine, _, _, _, action, _, _ = action_setup()
    post = engine.observe_post_change(
        action=action,
        currency_code="USD",
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 8),
        as_of=date(2026, 10, 15),
        exact_query_cost_micros=0,
        exact_query_clicks=0,
        scope_cost_micros=50_000_000,
        scope_clicks=500,
    )
    assert post.status is PostChangeStatus.NO_OBSERVED_QUERY_SPEND
    assert post.recovered_micros == 0


def test_post_change_scope_inactivity_is_not_success():
    engine, _, _, _, action, _, _ = action_setup()
    post = engine.observe_post_change(
        action=action,
        currency_code="USD",
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 8),
        as_of=date(2026, 10, 15),
        exact_query_cost_micros=0,
        exact_query_clicks=0,
        scope_cost_micros=0,
        scope_clicks=0,
    )
    assert post.status is PostChangeStatus.SCOPE_INACTIVE


def test_post_change_inside_lag_is_pending_maturity():
    engine, _, _, _, action, _, _ = action_setup()
    post = engine.observe_post_change(
        action=action,
        currency_code="USD",
        window_start=date(2026, 10, 9),
        window_end=date(2026, 10, 12),
        as_of=date(2026, 10, 15),
        exact_query_cost_micros=0,
        exact_query_clicks=0,
        scope_cost_micros=5_000_000,
        scope_clicks=50,
    )
    assert post.status is PostChangeStatus.PENDING_MATURITY


def test_query_spend_after_action_is_detected():
    engine, _, _, _, action, _, _ = action_setup()
    post = engine.observe_post_change(
        action=action,
        currency_code="USD",
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 8),
        as_of=date(2026, 10, 15),
        exact_query_cost_micros=900_000,
        exact_query_clicks=2,
        scope_cost_micros=5_000_000,
        scope_clicks=50,
    )
    assert post.status is PostChangeStatus.QUERY_SPEND_OBSERVED


def test_configuration_must_match_exact_applied_resource():
    _, _, _, _, action, _, config = action_setup()
    assert config.matches(action)
    bad = ConfigurationVerification(
        resource_name=action.resource_name,
        checked_at=config.checked_at,
        exists=True,
        negative=True,
        keyword_text="jobs",
        match_type=NegativeMatchType.EXACT,
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    assert not bad.matches(action)


def test_verified_experiment_requires_validated_business_outcome():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=False,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.INELIGIBLE
    assert result.verified_recovery_micros == 0


def test_verified_experiment_requires_50_50_split():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(control_traffic_percent=Decimal("60"), treatment_traffic_percent=Decimal("40")),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.INELIGIBLE


def test_verified_experiment_requires_mature_window():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(window_start=date(2026, 9, 10), window_end=date(2026, 10, 10)),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.INELIGIBLE


def test_cost_reduction_without_outcome_lift_is_not_verified():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(conversions_absolute_change_point_estimate=Decimal("1"), conversions_absolute_change_margin_of_error=Decimal("5")),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.INCONCLUSIVE
    assert result.verified_recovery_micros == 0


def test_conversions_experiment_can_verify_recovery_under_strict_gates():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.VERIFIED
    assert result.verified_recovery_micros == 30_000_000


def test_value_per_cost_experiment_can_verify_recovery_under_strict_gates():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSION_VALUE_PER_COST,
    )
    assert result.status is CausalVerificationStatus.VERIFIED


def test_ledger_headline_excludes_historical_and_projected_amounts():
    engine, _, _, _, action, baseline, config = action_setup()
    projection = engine.project_run_rate(
        baseline=baseline,
        action=action,
        projection_start=date(2026, 10, 2),
        projection_end=date(2026, 10, 11),
    )
    post = engine.observe_post_change(
        action=action,
        currency_code="USD",
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 8),
        as_of=date(2026, 10, 15),
        exact_query_cost_micros=0,
        exact_query_clicks=0,
        scope_cost_micros=50_000_000,
        scope_clicks=500,
    )
    ledger = engine.summarize(
        baseline=baseline,
        action=action,
        configuration=config,
        projection=projection,
        post_change=post,
    )
    assert ledger.historical_candidate_micros == 8_500_000
    assert ledger.projected_prevented_micros > 0
    assert ledger.headline_recovered_micros == 0


def test_verified_recovery_requires_configuration_still_matches_action():
    engine, _, _, _, action, baseline, config = action_setup()
    causal = engine.verify_experiment(
        report=experiment(),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    bad_config = ConfigurationVerification(
        resource_name=config.resource_name,
        checked_at=config.checked_at,
        exists=False,
        negative=None,
        keyword_text=None,
        match_type=None,
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    ledger = engine.summarize(
        baseline=baseline,
        action=action,
        configuration=bad_config,
        causal=causal,
    )
    assert causal.status is CausalVerificationStatus.VERIFIED
    assert ledger.verified_recovery_micros == 0
    assert not ledger.action_configuration_verified


def test_verified_recovery_enters_headline_only_after_all_gates():
    engine, _, _, _, action, baseline, config = action_setup()
    causal = engine.verify_experiment(
        report=experiment(),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    ledger = engine.summarize(
        baseline=baseline,
        action=action,
        configuration=config,
        causal=causal,
    )
    assert ledger.verified_recovery_micros == 30_000_000
    assert ledger.headline_recovered_micros == 30_000_000
    assert len(ledger.fingerprint_sha256) == 64


def test_automated_bidding_experiment_requires_ramp_up_exclusion():
    engine, *_ = action_setup()
    result = engine.verify_experiment(
        report=experiment(automated_bidding_used=True, ramp_up_days_excluded=0),
        as_of=date(2026, 10, 15),
        business_outcome_quality_validated=True,
        outcome_metric=ExperimentOutcomeMetric.CONVERSIONS,
    )
    assert result.status is CausalVerificationStatus.INELIGIBLE


def test_configuration_check_before_action_does_not_verify_action():
    _, _, _, _, action, _, _ = action_setup()
    config = ConfigurationVerification(
        resource_name=action.resource_name,
        checked_at=datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc),
        exists=True,
        negative=True,
        keyword_text=action.keyword_text,
        match_type=NegativeMatchType.EXACT,
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    assert not config.matches(action)
