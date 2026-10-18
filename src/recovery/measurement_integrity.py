from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping, Sequence


class MeasurementConfidence(str, Enum):
    STRONG = "strong"
    CONSTRAINED = "constrained"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class MeasurementSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class ConversionActionObservation:
    customer_id: str
    resource_name: str
    action_id: str
    name: str
    status: str
    action_type: str
    category: str
    origin: str
    owner_customer: str | None
    primary_for_goal: bool
    counting_type: str
    click_through_lookback_days: int
    view_through_lookback_days: int
    attribution_model: str
    data_driven_model_status: str
    default_value: Decimal
    default_currency_code: str | None
    always_use_default_value: bool
    all_conversions: Decimal
    all_conversions_value: Decimal
    last_conversion_date: date | None
    last_received_request_at: str | None

    def __post_init__(self) -> None:
        if not self.customer_id.isdigit():
            raise ValueError("conversion action customer_id must be digits")
        if not self.resource_name.startswith("customers/"):
            raise ValueError("conversion action resource_name is invalid")
        if not self.action_id.isdigit():
            raise ValueError("conversion action id must be digits")
        if self.click_through_lookback_days < 0 or self.view_through_lookback_days < 0:
            raise ValueError("conversion lookback windows cannot be negative")
        if self.all_conversions < 0:
            raise ValueError("all_conversions cannot be negative")


@dataclass(frozen=True, slots=True)
class CustomerConversionGoalObservation:
    customer_id: str
    resource_name: str
    category: str
    origin: str
    biddable: bool


@dataclass(frozen=True, slots=True)
class CampaignConversionGoalObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    campaign_status: str
    resource_name: str
    category: str
    origin: str
    biddable: bool


@dataclass(frozen=True, slots=True)
class CampaignGoalConfigObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    campaign_status: str
    resource_name: str
    goal_config_level: str
    custom_conversion_goal: str | None


@dataclass(frozen=True, slots=True)
class ConversionLagObservation:
    customer_id: str
    conversion_action_resource: str
    conversion_action_name: str
    category: str
    lag_bucket: str
    conversions: Decimal
    all_conversions: Decimal
    conversions_value: Decimal
    all_conversions_value: Decimal

    def __post_init__(self) -> None:
        if self.conversions < 0 or self.all_conversions < 0:
            raise ValueError("conversion lag metrics cannot be negative")


@dataclass(frozen=True, slots=True)
class MeasurementMapping:
    conversion_action_resource: str
    truth_snapshot_id: str
    outcome_id: str | None
    outcome_role: str | None
    outcome_confirmed: bool


@dataclass(frozen=True, slots=True)
class MeasurementIssue:
    code: str
    severity: MeasurementSeverity
    message: str
    conversion_action_resource: str | None = None
    campaign_id: str | None = None


@dataclass(frozen=True, slots=True)
class MeasurementAssessment:
    confidence: MeasurementConfidence
    issues: tuple[MeasurementIssue, ...]
    enabled_actions: int
    primary_actions: int
    mapped_primary_actions: int
    conversion_dependent_claims_allowed: bool
    recovery_verification_allowed: bool


_LAG_MAX_DAYS: dict[str, int | None] = {
    "LESS_THAN_ONE_DAY": 1,
    "ONE_TO_TWO_DAYS": 2,
    "TWO_TO_THREE_DAYS": 3,
    "THREE_TO_FOUR_DAYS": 4,
    "FOUR_TO_FIVE_DAYS": 5,
    "FIVE_TO_SIX_DAYS": 6,
    "SIX_TO_SEVEN_DAYS": 7,
    "SEVEN_TO_EIGHT_DAYS": 8,
    "EIGHT_TO_NINE_DAYS": 9,
    "NINE_TO_TEN_DAYS": 10,
    "TEN_TO_ELEVEN_DAYS": 11,
    "ELEVEN_TO_TWELVE_DAYS": 12,
    "TWELVE_TO_THIRTEEN_DAYS": 13,
    "THIRTEEN_TO_FOURTEEN_DAYS": 14,
    "FOURTEEN_TO_TWENTY_ONE_DAYS": 21,
    "TWENTY_ONE_TO_THIRTY_DAYS": 30,
    "THIRTY_TO_FORTY_FIVE_DAYS": 45,
    "FORTY_FIVE_TO_SIXTY_DAYS": 60,
    "SIXTY_TO_NINETY_DAYS": 90,
    "UNKNOWN": None,
    "UNSPECIFIED": None,
}


def lag_bucket_max_days(bucket: str) -> int | None:
    return _LAG_MAX_DAYS.get(bucket.strip().upper())


def assess_measurement_integrity(
    *,
    actions: Sequence[ConversionActionObservation],
    customer_goals: Sequence[CustomerConversionGoalObservation],
    campaign_goals: Sequence[CampaignConversionGoalObservation],
    campaign_configs: Sequence[CampaignGoalConfigObservation],
    lag_observations: Sequence[ConversionLagObservation],
    mappings: Mapping[str, MeasurementMapping],
    configured_conversion_lag_days: int | None,
) -> MeasurementAssessment:
    """Deterministic confidence assessment.

    This deliberately avoids a fake 0-100 score. It only escalates confidence when
    provider configuration and confirmed Business Truth mappings support it.
    """
    issues: list[MeasurementIssue] = []
    if not actions:
        issues.append(MeasurementIssue(
            "no_measurement_snapshot", MeasurementSeverity.BLOCKER,
            "No conversion-action inventory is available from a completed Google Ads sync.",
        ))
        return MeasurementAssessment(
            MeasurementConfidence.UNKNOWN, tuple(issues), 0, 0, 0, False, False
        )

    enabled=[a for a in actions if a.status.upper()=="ENABLED"]
    if not enabled:
        issues.append(MeasurementIssue(
            "no_enabled_conversion_actions", MeasurementSeverity.BLOCKER,
            "Google Ads exposes conversion actions, but none are enabled.",
        ))

    primary=[a for a in enabled if a.primary_for_goal]
    mapped_primary=0
    for action in primary:
        mapping=mappings.get(action.resource_name)
        if mapping is None or not mapping.outcome_id:
            issues.append(MeasurementIssue(
                "primary_action_unmapped", MeasurementSeverity.WARNING,
                "A Google primary conversion action has not been mapped to confirmed Business Truth.",
                conversion_action_resource=action.resource_name,
            ))
            continue
        if not mapping.outcome_confirmed:
            issues.append(MeasurementIssue(
                "primary_action_mapping_unconfirmed", MeasurementSeverity.WARNING,
                "A Google primary conversion action maps to a Business Truth outcome that is not confirmed.",
                conversion_action_resource=action.resource_name,
            ))
            continue
        role=(mapping.outcome_role or "unknown").lower()
        if role == "not_a_business_outcome":
            issues.append(MeasurementIssue(
                "primary_action_is_not_business_outcome", MeasurementSeverity.BLOCKER,
                "Google is treating an action as primary even though confirmed Business Truth says it is not a business outcome.",
                conversion_action_resource=action.resource_name,
            ))
            continue
        if role == "supporting_signal":
            issues.append(MeasurementIssue(
                "primary_action_is_supporting_signal", MeasurementSeverity.WARNING,
                "Google is treating a supporting signal as a primary conversion action.",
                conversion_action_resource=action.resource_name,
            ))
            mapped_primary += 1
            continue
        if role == "primary_business_outcome":
            mapped_primary += 1
        else:
            issues.append(MeasurementIssue(
                "primary_action_mapping_unknown_role", MeasurementSeverity.WARNING,
                "The mapped Business Truth outcome role is unknown.",
                conversion_action_resource=action.resource_name,
            ))

    if not primary:
        issues.append(MeasurementIssue(
            "no_enabled_primary_actions", MeasurementSeverity.WARNING,
            "No enabled conversion action is marked primary_for_goal. Custom goals can override this, so Recovery OS will not assume conversions are unusable, but standard bidding/reporting intent is unclear.",
        ))

    # Important business outcomes that Google treats only as secondary deserve review.
    for action in enabled:
        if action.primary_for_goal:
            continue
        mapping=mappings.get(action.resource_name)
        if mapping and mapping.outcome_confirmed and (mapping.outcome_role or "").lower()=="primary_business_outcome":
            issues.append(MeasurementIssue(
                "business_outcome_is_secondary", MeasurementSeverity.WARNING,
                "A confirmed primary business outcome is configured as a secondary Google conversion action. A custom goal may intentionally override this, so review campaign goal configuration.",
                conversion_action_resource=action.resource_name,
            ))

    # Google account-default goal categories can be biddable even when mappings are incomplete.
    enabled_pairs={(a.category.upper(),a.origin.upper()) for a in enabled if a.primary_for_goal}
    for goal in customer_goals:
        if goal.biddable and (goal.category.upper(),goal.origin.upper()) not in enabled_pairs:
            issues.append(MeasurementIssue(
                "biddable_customer_goal_without_enabled_primary_action", MeasurementSeverity.WARNING,
                "An account-default conversion goal is biddable but no enabled primary action with the same category/origin was observed.",
            ))

    for cfg in campaign_configs:
        if cfg.goal_config_level.upper()=="CAMPAIGN" or cfg.custom_conversion_goal:
            issues.append(MeasurementIssue(
                "campaign_specific_goal_configuration", MeasurementSeverity.INFO,
                "A campaign uses campaign-level or custom conversion-goal configuration; account-level assumptions do not fully describe bidding behavior.",
                campaign_id=cfg.campaign_id,
            ))

    # A configured maturity window shorter than observed conversions is directly contradictory.
    if configured_conversion_lag_days is None:
        issues.append(MeasurementIssue(
            "conversion_lag_policy_missing", MeasurementSeverity.WARNING,
            "No account conversion-lag maturity policy is configured.",
        ))
    else:
        late_actions=set()
        for row in lag_observations:
            if row.all_conversions <= 0:
                continue
            upper=lag_bucket_max_days(row.lag_bucket)
            if upper is not None and upper > configured_conversion_lag_days:
                late_actions.add(row.conversion_action_resource)
        for resource in sorted(late_actions):
            issues.append(MeasurementIssue(
                "configured_lag_shorter_than_observed", MeasurementSeverity.WARNING,
                "Observed conversions arrive later than the configured maturity window, so recent zero-conversion evidence may be premature.",
                conversion_action_resource=resource,
            ))

    blockers=any(i.severity is MeasurementSeverity.BLOCKER for i in issues)
    warnings=any(i.severity is MeasurementSeverity.WARNING for i in issues)
    if blockers:
        confidence=MeasurementConfidence.BLOCKED
    elif warnings:
        confidence=MeasurementConfidence.CONSTRAINED
    else:
        confidence=MeasurementConfidence.STRONG

    # Conversion-dependent claims and recovery verification need at least one confirmed
    # primary business outcome mapping and no blocker. Semantic/business-truth-only
    # waste claims can remain possible elsewhere without depending on this flag.
    claim_allowed=(not blockers and mapped_primary>0)
    return MeasurementAssessment(
        confidence=confidence,
        issues=tuple(issues),
        enabled_actions=len(enabled),
        primary_actions=len(primary),
        mapped_primary_actions=mapped_primary,
        conversion_dependent_claims_allowed=claim_allowed,
        recovery_verification_allowed=claim_allowed,
    )
