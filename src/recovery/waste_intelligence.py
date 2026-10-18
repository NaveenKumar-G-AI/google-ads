from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Sequence

from recovery.accuracy import AccuracyPolicy
from recovery.business_truth import BusinessTruthSnapshot, CustomerLocationRequirement, IntentCategory
from recovery.domain import DataMaturity


class LeakFamily(str, Enum):
    WRONG_SERVICE = "wrong_service"
    EMPLOYMENT = "employment"
    FREE = "free"
    DIY = "diy"
    SUPPORT = "support"
    TRAINING = "training"
    COMPETITOR = "competitor"
    INFORMATIONAL = "informational"
    SECOND_HAND = "second_hand"
    RENTAL = "rental"
    WHOLESALE = "wholesale"
    OTHER_DENIED_INTENT = "other_denied_intent"
    IRRELEVANT_INTENT = "irrelevant_intent"
    GEOGRAPHIC = "geographic"


_INTENT_FAMILY = {
    IntentCategory.EMPLOYMENT.value: LeakFamily.EMPLOYMENT,
    IntentCategory.FREE.value: LeakFamily.FREE,
    IntentCategory.DIY.value: LeakFamily.DIY,
    IntentCategory.SUPPORT.value: LeakFamily.SUPPORT,
    IntentCategory.TRAINING.value: LeakFamily.TRAINING,
    IntentCategory.COMPETITOR.value: LeakFamily.COMPETITOR,
    IntentCategory.INFORMATIONAL.value: LeakFamily.INFORMATIONAL,
    IntentCategory.RESEARCH.value: LeakFamily.INFORMATIONAL,
    IntentCategory.SECOND_HAND.value: LeakFamily.SECOND_HAND,
    IntentCategory.RENTAL.value: LeakFamily.RENTAL,
    IntentCategory.WHOLESALE.value: LeakFamily.WHOLESALE,
}


def query_leak_family(*, semantic: dict[str, Any] | None, fit: dict[str, Any] | None) -> LeakFamily | None:
    """Assign one primary, non-overlapping leak family to an irrelevant query.

    Financial totals use this *primary* family. Network/device/time remain dimensions
    so the same source spend can never be added twice under multiple leak labels.
    """
    if not fit or fit.get("disposition") != "irrelevant":
        return None
    if fit.get("decisive_non_offer_ids"):
        return LeakFamily.WRONG_SERVICE
    decisive = [str(x) for x in (fit.get("decisive_intents") or [])]
    for category in decisive:
        family = _INTENT_FAMILY.get(category)
        if family is not None:
            return family
    # A denied custom intent can still be a real mismatch even when it is not one of
    # the named V1 families. Keep it separate from generic semantic mismatch.
    if decisive:
        return LeakFamily.OTHER_DENIED_INTENT
    # Explicit non-offer / intent logic can evolve; do not invent a narrower family.
    return LeakFamily.IRRELEVANT_INTENT


@dataclass(frozen=True, slots=True)
class LeakFinding:
    family: LeakFamily
    disposition: str
    currency_code: str
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    already_addressed_observed_micros: int
    observation_ids: tuple[str, ...]


def summarize_query_leaks(findings: Sequence[LeakFinding]) -> dict[str, dict[str, int]]:
    seen: set[str] = set()
    output: dict[str, dict[str, int]] = {}
    for finding in findings:
        overlap = seen.intersection(finding.observation_ids)
        if overlap:
            raise ValueError("leak findings overlap source observations; financial totals would double count")
        seen.update(finding.observation_ids)
        bucket = output.setdefault(finding.family.value, {
            "potentially_avoidable_observed_micros": 0,
            "review_required_observed_micros": 0,
            "already_addressed_observed_micros": 0,
            "finding_count": 0,
        })
        bucket["potentially_avoidable_observed_micros"] += finding.potentially_avoidable_observed_micros
        bucket["review_required_observed_micros"] += finding.review_required_observed_micros
        bucket["already_addressed_observed_micros"] += finding.already_addressed_observed_micros
        bucket["finding_count"] += 1
    return output


@dataclass(frozen=True, slots=True)
class CampaignPerformanceSegmentObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    date: date
    network: str
    device: str
    day_of_week: str
    hour: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: Decimal
    conversions_value: Decimal
    all_conversions: Decimal
    all_conversions_value: Decimal
    currency_code: str

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ValueError("hour must be in 0..23")
        if min(self.impressions, self.clicks, self.cost_micros) < 0:
            raise ValueError("performance metrics cannot be negative")
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")


@dataclass(frozen=True, slots=True)
class UserLocationObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    date: date
    network: str
    targeting_location: bool
    country_criterion_id: str
    location_resource: str
    location_name: str | None
    canonical_name: str | None
    country_code: str | None
    target_type: str | None
    impressions: int
    clicks: int
    cost_micros: int
    conversions: Decimal
    conversions_value: Decimal
    all_conversions: Decimal
    all_conversions_value: Decimal
    currency_code: str

    def __post_init__(self) -> None:
        if min(self.impressions, self.clicks, self.cost_micros) < 0:
            raise ValueError("location metrics cannot be negative")
        if self.clicks > self.impressions:
            raise ValueError("clicks cannot exceed impressions")
        if not self.location_resource.strip():
            raise ValueError("location_resource is required")


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _canonical_parts(value: str | None) -> tuple[str, ...]:
    return tuple(_norm(x) for x in (value or "").split(",") if _norm(x))


def geo_location_fit(truth: BusinessTruthSnapshot, row: UserLocationObservation) -> tuple[str, str]:
    """Return relevant / irrelevant / unknown using confirmed physical-location truth.

    We never use campaign targeting configuration as proof of the user's physical
    location. Granularity must be sufficient to compare the reported location with the
    business's confirmed service-area definition.
    """
    policy = truth.geo_policy
    if policy is None or not policy.basis.is_confirmed:
        return "unknown", "No confirmed service-area truth is available."
    if policy.requirement is CustomerLocationRequirement.NO_RESTRICTION:
        return "relevant", "Business Truth has no customer-location restriction."
    if policy.requirement is CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA:
        return "unknown", "Physical user location cannot prove the requested job or destination is outside the service area."
    if policy.requirement in {CustomerLocationRequirement.UNKNOWN, CustomerLocationRequirement.CONDITIONAL}:
        return "unknown", "Business location requirement is unknown or conditional."
    if not policy.included_areas:
        return "unknown", "Service-area policy has no included areas."

    cc = (row.country_code or "").upper()
    parts = set(_canonical_parts(row.canonical_name))
    name = _norm(row.location_name)
    target_type = _norm(row.target_type)

    # Exact Google geo resource wins when the customer supplied one.
    for area in policy.included_areas:
        if area.google_geo_target_constant and area.google_geo_target_constant == row.location_resource:
            return "relevant", "Actual user location matches an included Google geo target."

    same_country = [a for a in policy.included_areas if a.country_code.upper() == cc] if cc else []
    if not same_country:
        if cc:
            return "irrelevant", "Actual user location is in a country outside the confirmed service area."
        return "unknown", "Google location metadata has no country code."

    # Country-only truth means every reported location in that country is included.
    if any(not a.region and not a.city and not a.postal_code for a in same_country):
        return "relevant", "Actual user location is inside an included country."

    for area in same_country:
        city = _norm(area.city)
        region = _norm(area.region)
        postal = _norm(area.postal_code)
        if postal and (postal == name or postal in parts):
            return "relevant", "Actual user location matches an included postal code."
        if city and (city == name or city in parts):
            return "relevant", "Actual user location matches an included city."
        if region and (region == name or region in parts):
            return "relevant", "Actual user location matches an included region."

    # A country-only reported row is not granular enough to prove the user is outside a
    # city/region/postal service area inside that same country.
    if target_type in {"country", ""}:
        return "unknown", "Reported user location is too coarse to compare with the configured service-area granularity."
    return "irrelevant", "Reported user location is specific and does not match any included area in the same country."


@dataclass(frozen=True, slots=True)
class GeoLeakAggregate:
    location_resource: str
    location_name: str
    canonical_name: str | None
    country_code: str | None
    target_type: str | None
    disposition: str
    reason: str
    mature_cost_micros: int
    immature_cost_micros: int
    potentially_avoidable_observed_micros: int
    review_required_observed_micros: int
    mature_conversions: Decimal
    row_count: int


def evaluate_geo_leaks(*, truth: BusinessTruthSnapshot, rows: Iterable[UserLocationObservation],
                       policy: AccuracyPolicy, as_of: date) -> tuple[GeoLeakAggregate, ...]:
    grouped: dict[str, list[UserLocationObservation]] = {}
    for row in rows:
        grouped.setdefault(row.location_resource, []).append(row)
    results: list[GeoLeakAggregate] = []
    for resource, items in grouped.items():
        fit, reason = geo_location_fit(truth, items[0])
        mature = [r for r in items if policy.maturity(r.date, as_of) is DataMaturity.MATURE]
        immature = [r for r in items if policy.maturity(r.date, as_of) is DataMaturity.IMMATURE]
        mature_cost = sum(r.cost_micros for r in mature)
        immature_cost = sum(r.cost_micros for r in immature)
        mature_conv = sum((r.conversions for r in mature), Decimal("0"))
        mature_all = sum((r.all_conversions for r in mature), Decimal("0"))
        potential = review = 0
        disposition = "not_supported"
        if fit == "irrelevant" and mature_cost > 0:
            if mature_conv != 0 or mature_all != 0:
                disposition = "review_required"
                review = mature_cost
            else:
                disposition = "potentially_avoidable"
                potential = mature_cost
        elif fit == "irrelevant" and immature_cost > 0:
            disposition = "review_required"
            review = immature_cost
        elif fit == "unknown":
            disposition = "review_required" if mature_cost + immature_cost > 0 else "not_supported"
            review = mature_cost + immature_cost
        results.append(GeoLeakAggregate(
            location_resource=resource,
            location_name=items[0].location_name or resource,
            canonical_name=items[0].canonical_name,
            country_code=items[0].country_code,
            target_type=items[0].target_type,
            disposition=disposition,
            reason=reason,
            mature_cost_micros=mature_cost,
            immature_cost_micros=immature_cost,
            potentially_avoidable_observed_micros=potential,
            review_required_observed_micros=review,
            mature_conversions=mature_conv,
            row_count=len(items),
        ))
    return tuple(sorted(results, key=lambda x:(x.potentially_avoidable_observed_micros+x.review_required_observed_micros, x.location_name), reverse=True))
