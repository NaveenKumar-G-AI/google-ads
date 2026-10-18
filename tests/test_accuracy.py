from datetime import date
from decimal import Decimal

from recovery.accuracy import AccuracyPolicy
from recovery.domain import CoverageBand, DataMaturity, FindingConfidence


def test_recent_observation_is_immature() -> None:
    policy = AccuracyPolicy(conversion_lag_days=7)
    assert (
        policy.maturity(date(2026, 10, 12), date(2026, 10, 15))
        == DataMaturity.IMMATURE
    )
    assert (
        policy.maturity(date(2026, 10, 8), date(2026, 10, 15))
        == DataMaturity.MATURE
    )


def test_zero_conversion_is_never_standalone_waste_proof() -> None:
    policy = AccuracyPolicy(conversion_lag_days=7)
    assert not policy.can_use_zero_conversion_as_waste_proof(
        observation_date=date(2026, 9, 1), as_of=date(2026, 10, 15)
    )


def test_high_semantic_confidence_requires_confirmed_business_context() -> None:
    policy = AccuracyPolicy(conversion_lag_days=7)
    result = policy.confidence_for_semantic_mismatch(
        semantic_confidence=Decimal("0.99"),
        business_context_confirmed=False,
        coverage_band=CoverageBand.HIGH,
        already_excluded=False,
    )
    assert result == FindingConfidence.INSUFFICIENT


def test_low_account_coverage_caps_finding_confidence() -> None:
    policy = AccuracyPolicy(conversion_lag_days=7)
    result = policy.confidence_for_semantic_mismatch(
        semantic_confidence=Decimal("0.99"),
        business_context_confirmed=True,
        coverage_band=CoverageBand.LOW,
        already_excluded=False,
    )
    assert result == FindingConfidence.MEDIUM
