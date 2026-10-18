from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
import hashlib
import json
from typing import Sequence

from .accuracy import AccuracyPolicy
from .domain import Money
from .negative_keywords import (
    ApprovalRecord,
    NegativeKeywordProposal,
    NegativeMatchType,
    NegativeMutationPlan,
    NegativeScope,
    ProposalDisposition,
)

RECOVERY_LEDGER_SCHEMA_VERSION = 1


class PostChangeStatus(str, Enum):
    PENDING_MATURITY = "pending_maturity"
    SCOPE_INACTIVE = "scope_inactive"
    QUERY_SPEND_OBSERVED = "query_spend_observed"
    NO_OBSERVED_QUERY_SPEND = "no_observed_query_spend"


class CausalVerificationStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    INELIGIBLE = "ineligible"
    INCONCLUSIVE = "inconclusive"
    VERIFIED = "verified"


class ExperimentOutcomeMetric(str, Enum):
    CONVERSIONS = "conversions"
    CONVERSION_VALUE_PER_COST = "conversion_value_per_cost"


@dataclass(frozen=True, slots=True)
class AppliedNegativeChange:
    """Receipt for an actual Google Ads mutation.

    This is intentionally separate from the approved proposal. An approved proposal is
    not evidence that Google accepted or retained the change.
    """

    proposal_id: str
    proposal_fingerprint: str
    customer_id: str
    campaign_id: str
    ad_group_id: str
    keyword_text: str
    match_type: NegativeMatchType
    resource_name: str
    applied_at: datetime
    applied_by: str
    validate_only_passed: bool
    api_request_id: str | None = None

    def __post_init__(self) -> None:
        if self.applied_at.tzinfo is None or self.applied_at.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")
        if not self.resource_name.strip():
            raise ValueError("resource_name is required")
        if not self.applied_by.strip():
            raise ValueError("applied_by is required")
        if not self.validate_only_passed:
            raise ValueError("V1 requires validate_only to pass before live mutation")


@dataclass(frozen=True, slots=True)
class ConfigurationVerification:
    """Direct configuration read-back for the resource created by our action."""

    resource_name: str
    checked_at: datetime
    exists: bool
    negative: bool | None
    keyword_text: str | None
    match_type: NegativeMatchType | None
    customer_id: str
    campaign_id: str
    ad_group_id: str

    def __post_init__(self) -> None:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

    def matches(self, action: AppliedNegativeChange) -> bool:
        return bool(
            self.exists
            and self.resource_name == action.resource_name
            and self.negative is True
            and self.keyword_text == action.keyword_text
            and self.match_type is action.match_type
            and self.customer_id == action.customer_id
            and self.campaign_id == action.campaign_id
            and self.ad_group_id == action.ad_group_id
            and self.checked_at >= action.applied_at
        )


@dataclass(frozen=True, slots=True)
class HistoricalBaseline:
    proposal_id: str
    proposal_fingerprint: str
    customer_id: str
    campaign_id: str
    ad_group_id: str
    keyword_text: str
    currency_code: str
    window_start: date
    window_end: date
    potentially_avoidable_cost_micros: int
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.window_start > self.window_end:
            raise ValueError("baseline start must be <= end")
        if self.potentially_avoidable_cost_micros < 0:
            raise ValueError("baseline cost cannot be negative")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("baseline observation_ids must be unique")
        Money(0, self.currency_code)

    @property
    def window_days(self) -> int:
        return (self.window_end - self.window_start).days + 1

    @property
    def historical_candidate(self) -> Money:
        return Money(self.potentially_avoidable_cost_micros, self.currency_code)

    @property
    def average_daily_candidate_micros(self) -> Decimal:
        return Decimal(self.potentially_avoidable_cost_micros) / Decimal(self.window_days)


@dataclass(frozen=True, slots=True)
class RunRateProjection:
    proposal_id: str
    currency_code: str
    projection_start: date
    projection_end: date
    projected_prevented_cost_micros: int
    basis_window_start: date
    basis_window_end: date
    method: str = "historical_observed_run_rate"

    def __post_init__(self) -> None:
        if self.projection_start > self.projection_end:
            raise ValueError("projection start must be <= end")
        if self.projected_prevented_cost_micros < 0:
            raise ValueError("projection cannot be negative")
        Money(0, self.currency_code)

    @property
    def projected_prevented_cost(self) -> Money:
        return Money(self.projected_prevented_cost_micros, self.currency_code)

    @property
    def claim_label(self) -> str:
        return "projected spend prevented (not verified recovery)"


@dataclass(frozen=True, slots=True)
class PostChangeObservation:
    proposal_id: str
    currency_code: str
    window_start: date
    window_end: date
    as_of: date
    exact_query_cost_micros: int
    exact_query_clicks: int
    scope_cost_micros: int
    scope_clicks: int
    status: PostChangeStatus

    def __post_init__(self) -> None:
        if self.window_start > self.window_end:
            raise ValueError("post-change start must be <= end")
        if min(self.exact_query_cost_micros, self.exact_query_clicks, self.scope_cost_micros, self.scope_clicks) < 0:
            raise ValueError("post-change metrics cannot be negative")
        if self.exact_query_cost_micros > self.scope_cost_micros:
            raise ValueError("query cost cannot exceed target-scope cost")
        if self.exact_query_clicks > self.scope_clicks:
            raise ValueError("query clicks cannot exceed target-scope clicks")
        Money(0, self.currency_code)

    @property
    def exact_query_cost(self) -> Money:
        return Money(self.exact_query_cost_micros, self.currency_code)

    @property
    def recovered_micros(self) -> int:
        """Never infer recovery from post-change absence/reduction alone."""
        return 0


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    """Metrics copied from Google Ads direct experiment reporting.

    Treatment metrics use the normal metric fields; control metrics are the corresponding
    `control_*` values. Relative point estimates are treatment/control - 1.
    """

    experiment_id: str
    currency_code: str
    window_start: date
    window_end: date
    control_traffic_percent: Decimal
    treatment_traffic_percent: Decimal
    treatment_cost_micros: int
    control_cost_micros: int
    cost_change_point_estimate: Decimal
    cost_change_margin_of_error: Decimal
    cost_p_value: Decimal
    treatment_conversions: Decimal
    control_conversions: Decimal
    conversions_absolute_change_point_estimate: Decimal
    conversions_absolute_change_margin_of_error: Decimal
    conversions_p_value: Decimal
    treatment_conversion_value_per_cost: Decimal
    control_conversion_value_per_cost: Decimal
    conversion_value_per_cost_change_point_estimate: Decimal
    conversion_value_per_cost_margin_of_error: Decimal
    conversion_value_per_cost_p_value: Decimal
    automated_bidding_used: bool = False
    ramp_up_days_excluded: int = 0

    def __post_init__(self) -> None:
        if self.window_start > self.window_end:
            raise ValueError("experiment start must be <= end")
        if self.treatment_cost_micros < 0 or self.control_cost_micros < 0:
            raise ValueError("experiment cost cannot be negative")
        for x in (self.cost_p_value, self.conversions_p_value, self.conversion_value_per_cost_p_value):
            if not (Decimal("0") <= x <= Decimal("1")):
                raise ValueError("experiment p-values must be in [0, 1]")
        if self.cost_change_margin_of_error < 0 or self.conversions_absolute_change_margin_of_error < 0 or self.conversion_value_per_cost_margin_of_error < 0:
            raise ValueError("experiment margins of error cannot be negative")
        if self.ramp_up_days_excluded < 0:
            raise ValueError("ramp_up_days_excluded cannot be negative")
        if self.control_traffic_percent + self.treatment_traffic_percent != Decimal("100"):
            raise ValueError("control+treatment traffic must equal 100%")
        if self.control_traffic_percent <= 0 or self.treatment_traffic_percent <= 0:
            raise ValueError("experiment traffic shares must be positive")
        Money(0, self.currency_code)

    @property
    def duration_days(self) -> int:
        return (self.window_end - self.window_start).days + 1


@dataclass(frozen=True, slots=True)
class CausalRecoveryResult:
    experiment_id: str
    status: CausalVerificationStatus
    currency_code: str
    verified_recovery_micros: int
    reasons: tuple[str, ...]

    @property
    def verified_recovery(self) -> Money:
        return Money(self.verified_recovery_micros, self.currency_code)


@dataclass(frozen=True, slots=True)
class RecoveryLedgerSummary:
    currency_code: str
    historical_candidate_micros: int
    projected_prevented_micros: int
    observed_post_action_query_spend_micros: int
    verified_recovery_micros: int
    action_configuration_verified: bool
    causal_status: CausalVerificationStatus
    schema_version: int = RECOVERY_LEDGER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECOVERY_LEDGER_SCHEMA_VERSION:
            raise ValueError("unsupported recovery ledger schema version")
        for value in (
            self.historical_candidate_micros,
            self.projected_prevented_micros,
            self.observed_post_action_query_spend_micros,
            self.verified_recovery_micros,
        ):
            if value < 0:
                raise ValueError("recovery ledger money values cannot be negative")
        Money(0, self.currency_code)
        if self.verified_recovery_micros > 0:
            if self.causal_status is not CausalVerificationStatus.VERIFIED:
                raise ValueError("non-zero verified recovery requires VERIFIED causal status")
            if not self.action_configuration_verified:
                raise ValueError("non-zero verified recovery requires verified live configuration")
        if self.causal_status is not CausalVerificationStatus.VERIFIED and self.verified_recovery_micros != 0:
            raise ValueError("unverified causal status must have zero verified recovery")

    @property
    def historical_candidate(self) -> Money:
        return Money(self.historical_candidate_micros, self.currency_code)

    @property
    def projected_prevented(self) -> Money:
        return Money(self.projected_prevented_micros, self.currency_code)

    @property
    def verified_recovery(self) -> Money:
        return Money(self.verified_recovery_micros, self.currency_code)

    @property
    def headline_recovered_micros(self) -> int:
        """Only causally verified recovery may feed a 'recovered' headline."""
        return self.verified_recovery_micros

    @property
    def fingerprint_sha256(self) -> str:
        payload = {
            "currency": self.currency_code,
            "historical": self.historical_candidate_micros,
            "projected": self.projected_prevented_micros,
            "observed_post_query_spend": self.observed_post_action_query_spend_micros,
            "verified": self.verified_recovery_micros,
            "config_verified": self.action_configuration_verified,
            "causal_status": self.causal_status.value,
            "schema": self.schema_version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class RecoveryVerificationEngine:
    def __init__(
        self,
        accuracy_policy: AccuracyPolicy,
        *,
        max_experiment_p_value: Decimal = Decimal("0.05"),
        minimum_experiment_days: int = 28,
    ) -> None:
        self.accuracy_policy = accuracy_policy
        self.max_experiment_p_value = max_experiment_p_value
        self.minimum_experiment_days = minimum_experiment_days
        if not (Decimal("0") < max_experiment_p_value < Decimal("1")):
            raise ValueError("max_experiment_p_value must be in (0, 1)")
        if minimum_experiment_days <= 0:
            raise ValueError("minimum_experiment_days must be positive")

    def record_applied_change(
        self,
        *,
        proposal: NegativeKeywordProposal,
        approval: ApprovalRecord,
        plan: NegativeMutationPlan,
        resource_name: str,
        applied_at: datetime,
        applied_by: str,
        api_request_id: str | None = None,
        validate_only_passed: bool,
    ) -> AppliedNegativeChange:
        if proposal.disposition is not ProposalDisposition.READY_FOR_APPROVAL:
            raise ValueError("only READY_FOR_APPROVAL proposals can be recorded as applied")
        if applied_at < approval.approved_at:
            raise ValueError("applied_at cannot be before human approval")
        if not plan.validate_only_first:
            raise ValueError("V1 mutation plan must require validate_only first")
        if approval.proposal_id != proposal.proposal_id or plan.proposal_id != proposal.proposal_id:
            raise ValueError("proposal/approval/mutation plan IDs do not match")
        if approval.proposal_fingerprint != proposal.fingerprint_sha256:
            raise ValueError("proposal changed after approval")
        if proposal.candidate.scope is not NegativeScope.AD_GROUP:
            raise ValueError("Phase 6 V1 only records ad-group negative actions")
        if plan.keyword_text != proposal.candidate.text or plan.match_type is not proposal.candidate.match_type:
            raise ValueError("mutation plan does not match approved candidate")
        return AppliedNegativeChange(
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint_sha256,
            customer_id=proposal.candidate.customer_id,
            campaign_id=proposal.candidate.campaign_id or "",
            ad_group_id=proposal.candidate.ad_group_id or "",
            keyword_text=proposal.candidate.text,
            match_type=proposal.candidate.match_type,
            resource_name=resource_name,
            applied_at=applied_at,
            applied_by=applied_by,
            validate_only_passed=validate_only_passed,
            api_request_id=api_request_id,
        )

    def build_baseline(
        self,
        *,
        proposal: NegativeKeywordProposal,
        window_start: date,
        window_end: date,
    ) -> HistoricalBaseline:
        if proposal.disposition is not ProposalDisposition.READY_FOR_APPROVAL:
            raise ValueError("baseline requires an eligible approved-action proposal")
        if proposal.candidate.scope is not NegativeScope.AD_GROUP:
            raise ValueError("V1 baseline only supports ad-group actions")
        return HistoricalBaseline(
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint_sha256,
            customer_id=proposal.candidate.customer_id,
            campaign_id=proposal.candidate.campaign_id or "",
            ad_group_id=proposal.candidate.ad_group_id or "",
            keyword_text=proposal.candidate.text,
            currency_code=proposal.currency_code,
            window_start=window_start,
            window_end=window_end,
            potentially_avoidable_cost_micros=proposal.potentially_avoidable_cost_micros,
            observation_ids=proposal.evidence_observation_ids,
        )

    def project_run_rate(
        self,
        *,
        baseline: HistoricalBaseline,
        action: AppliedNegativeChange,
        projection_start: date,
        projection_end: date,
    ) -> RunRateProjection:
        if baseline.proposal_id != action.proposal_id or baseline.proposal_fingerprint != action.proposal_fingerprint:
            raise ValueError("baseline and applied action do not share the same approved proposal")
        if baseline.window_end >= action.applied_at.date():
            raise ValueError("baseline must end before the action application date")
        if projection_start <= action.applied_at.date():
            raise ValueError("projection must start after the mixed application day")
        if projection_start > projection_end:
            raise ValueError("projection start must be <= end")
        days = (projection_end - projection_start).days + 1
        if days > baseline.window_days:
            raise ValueError("V1 projection horizon cannot exceed its historical baseline window")
        projected = int(
            (baseline.average_daily_candidate_micros * Decimal(days)).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        return RunRateProjection(
            proposal_id=baseline.proposal_id,
            currency_code=baseline.currency_code,
            projection_start=projection_start,
            projection_end=projection_end,
            projected_prevented_cost_micros=projected,
            basis_window_start=baseline.window_start,
            basis_window_end=baseline.window_end,
        )

    def observe_post_change(
        self,
        *,
        action: AppliedNegativeChange,
        currency_code: str,
        window_start: date,
        window_end: date,
        as_of: date,
        exact_query_cost_micros: int,
        exact_query_clicks: int,
        scope_cost_micros: int,
        scope_clicks: int,
    ) -> PostChangeObservation:
        if window_start <= action.applied_at.date():
            raise ValueError("post-change window must begin after the mixed application day")
        if window_start > window_end or window_end > as_of:
            raise ValueError("invalid post-change observation window")

        maturity_cutoff = as_of - timedelta(days=self.accuracy_policy.conversion_lag_days)
        if window_end > maturity_cutoff:
            status = PostChangeStatus.PENDING_MATURITY
        elif scope_cost_micros == 0 and scope_clicks == 0:
            status = PostChangeStatus.SCOPE_INACTIVE
        elif exact_query_cost_micros > 0 or exact_query_clicks > 0:
            status = PostChangeStatus.QUERY_SPEND_OBSERVED
        else:
            status = PostChangeStatus.NO_OBSERVED_QUERY_SPEND

        return PostChangeObservation(
            proposal_id=action.proposal_id,
            currency_code=currency_code,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            exact_query_cost_micros=exact_query_cost_micros,
            exact_query_clicks=exact_query_clicks,
            scope_cost_micros=scope_cost_micros,
            scope_clicks=scope_clicks,
            status=status,
        )

    def verify_experiment(
        self,
        *,
        report: ExperimentReport,
        as_of: date,
        business_outcome_quality_validated: bool,
        outcome_metric: ExperimentOutcomeMetric,
    ) -> CausalRecoveryResult:
        reasons: list[str] = []

        if report.window_end > as_of - timedelta(days=self.accuracy_policy.conversion_lag_days):
            reasons.append("Experiment outcome window is still inside the configured conversion-lag period.")
        if report.duration_days < self.minimum_experiment_days:
            reasons.append("Experiment has not run for the minimum verification duration.")
        if report.control_traffic_percent != Decimal("50") or report.treatment_traffic_percent != Decimal("50"):
            reasons.append("V1 monetary recovery verification requires a 50/50 experiment split.")
        if report.automated_bidding_used and report.ramp_up_days_excluded < 7:
            reasons.append("Automated-bidding experiment did not exclude at least 7 ramp-up days from verification.")
        if not business_outcome_quality_validated:
            reasons.append("The experiment's conversion/outcome definition has not been independently validated as a real business outcome.")

        cost_upper_bound = report.cost_change_point_estimate + report.cost_change_margin_of_error
        cost_significantly_lower = (
            report.cost_p_value <= self.max_experiment_p_value and cost_upper_bound < 0
        )
        if not cost_significantly_lower:
            reasons.append("Treatment cost is not significantly lower than control at the configured threshold.")

        if outcome_metric is ExperimentOutcomeMetric.CONVERSIONS:
            outcome_lower_bound = (
                report.conversions_absolute_change_point_estimate
                - report.conversions_absolute_change_margin_of_error
            )
            outcome_supported = (
                report.conversions_p_value <= self.max_experiment_p_value
                and outcome_lower_bound > 0
            )
            if not outcome_supported:
                reasons.append("Treatment does not show a statistically significant positive conversion lift.")
        else:
            outcome_lower_bound = (
                report.conversion_value_per_cost_change_point_estimate
                - report.conversion_value_per_cost_margin_of_error
            )
            outcome_supported = (
                report.conversion_value_per_cost_p_value <= self.max_experiment_p_value
                and outcome_lower_bound > 0
            )
            if not outcome_supported:
                reasons.append("Treatment does not show a statistically significant positive conversion-value-per-cost lift.")

        if reasons:
            hard_ineligible = any(
                text.startswith("V1 monetary")
                or text.startswith("The experiment's conversion")
                or text.startswith("Experiment outcome window")
                or text.startswith("Experiment has not")
                or text.startswith("Automated-bidding experiment")
                for text in reasons
            )
            return CausalRecoveryResult(
                experiment_id=report.experiment_id,
                status=(
                    CausalVerificationStatus.INELIGIBLE
                    if hard_ineligible
                    else CausalVerificationStatus.INCONCLUSIVE
                ),
                currency_code=report.currency_code,
                verified_recovery_micros=0,
                reasons=tuple(reasons),
            )

        observed_difference = max(report.control_cost_micros - report.treatment_cost_micros, 0)
        if observed_difference <= 0:
            return CausalRecoveryResult(
                experiment_id=report.experiment_id,
                status=CausalVerificationStatus.INCONCLUSIVE,
                currency_code=report.currency_code,
                verified_recovery_micros=0,
                reasons=("Raw 50/50 control cost is not greater than treatment cost.",),
            )

        return CausalRecoveryResult(
            experiment_id=report.experiment_id,
            status=CausalVerificationStatus.VERIFIED,
            currency_code=report.currency_code,
            verified_recovery_micros=observed_difference,
            reasons=(
                "50/50 Google Ads experiment shows significantly lower treatment cost and a significantly improved validated business-outcome metric.",
            ),
        )

    def summarize(
        self,
        *,
        baseline: HistoricalBaseline,
        action: AppliedNegativeChange,
        configuration: ConfigurationVerification,
        projection: RunRateProjection | None = None,
        post_change: PostChangeObservation | None = None,
        causal: CausalRecoveryResult | None = None,
    ) -> RecoveryLedgerSummary:
        if baseline.proposal_id != action.proposal_id:
            raise ValueError("ledger items do not share the same proposal")
        if baseline.proposal_fingerprint != action.proposal_fingerprint:
            raise ValueError("ledger baseline/action fingerprint mismatch")

        currencies = {baseline.currency_code}
        if projection:
            currencies.add(projection.currency_code)
        if post_change:
            currencies.add(post_change.currency_code)
        if causal:
            currencies.add(causal.currency_code)
        if len(currencies) != 1:
            raise ValueError("ledger cannot mix currencies")

        config_verified = configuration.matches(action)
        verified = 0
        causal_status = CausalVerificationStatus.NOT_EVALUATED
        if causal:
            causal_status = causal.status
            # A causal result cannot be displayed as recovered if the live resource no
            # longer matches the applied action we are attributing it to.
            if config_verified and causal.status is CausalVerificationStatus.VERIFIED:
                verified = causal.verified_recovery_micros

        return RecoveryLedgerSummary(
            currency_code=baseline.currency_code,
            historical_candidate_micros=baseline.potentially_avoidable_cost_micros,
            projected_prevented_micros=(projection.projected_prevented_cost_micros if projection else 0),
            observed_post_action_query_spend_micros=(post_change.exact_query_cost_micros if post_change else 0),
            verified_recovery_micros=verified,
            action_configuration_verified=config_verified,
            causal_status=causal_status,
        )
