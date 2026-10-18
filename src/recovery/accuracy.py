from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .domain import CoverageBand, DataMaturity, FindingConfidence


@dataclass(frozen=True, slots=True)
class AccuracyPolicy:
    """Conservative rules that prevent unsupported 'waste' claims.

    `conversion_lag_days` is intentionally configurable. Google documents conversion
    lag but there is no universal fixed safe delay for every advertiser/conversion.
    V1 must obtain this value from account/operator policy rather than presenting a
    global constant as truth.
    """

    conversion_lag_days: int
    minimum_semantic_confidence: Decimal = Decimal("0.95")

    def __post_init__(self) -> None:
        if self.conversion_lag_days < 0:
            raise ValueError("conversion_lag_days cannot be negative")
        if not (Decimal("0") <= self.minimum_semantic_confidence <= Decimal("1")):
            raise ValueError("minimum_semantic_confidence must be in [0, 1]")

    def maturity(self, observation_date: date, as_of: date) -> DataMaturity:
        cutoff = as_of - timedelta(days=self.conversion_lag_days)
        return (
            DataMaturity.MATURE
            if observation_date <= cutoff
            else DataMaturity.IMMATURE
        )

    def confidence_for_semantic_mismatch(
        self,
        *,
        semantic_confidence: Decimal,
        business_context_confirmed: bool,
        coverage_band: CoverageBand,
        already_excluded: bool,
    ) -> FindingConfidence:
        """Confidence for *semantic irrelevance*, not performance under-delivery.

        A high-confidence exclusion requires confirmed business context and a very
        strong semantic mismatch. Existing exclusions are not new opportunities.
        Coverage does not make an individual observed query false, but low coverage
        limits account-level claims, so it caps confidence at MEDIUM.
        """

        if already_excluded or not business_context_confirmed:
            return FindingConfidence.INSUFFICIENT
        if semantic_confidence < self.minimum_semantic_confidence:
            return FindingConfidence.LOW
        if coverage_band in {CoverageBand.LOW, CoverageBand.UNKNOWN}:
            return FindingConfidence.MEDIUM
        return FindingConfidence.HIGH

    def can_use_zero_conversion_as_waste_proof(
        self,
        *,
        observation_date: date,
        as_of: date,
    ) -> bool:
        """Always false by design.

        Zero conversions can support a broader inference after maturity, sample-size
        checks and business context, but it is never standalone proof of waste.
        """

        _ = self.maturity(observation_date, as_of)
        return False
