from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import hashlib
from typing import Iterable, Sequence

from .accuracy import AccuracyPolicy
from .domain import CoverageBand, CoverageSummary, DataMaturity, Money, SearchTermObservation
from .search_intent import (
    BusinessFitDecision,
    FitDisposition,
    SemanticAssessment,
    normalize_query,
)

EVIDENCE_SCHEMA_VERSION = 1


class EvidenceDisposition(str, Enum):
    """Financial-evidence conclusion for one observed search-term scope.

    This is deliberately not an action recommendation. Phase 5 decides whether a
    negative keyword is safe and how it should be scoped/matched.
    """

    POTENTIALLY_AVOIDABLE = "potentially_avoidable"
    REVIEW_REQUIRED = "review_required"
    ALREADY_ADDRESSED = "already_addressed"
    NOT_SUPPORTED = "not_supported"


class EvidenceReasonCode(str, Enum):
    SEMANTIC_MISMATCH_CONFIRMED = "semantic_mismatch_confirmed"
    SEMANTIC_MISMATCH_NOT_ESTABLISHED = "semantic_mismatch_not_established"
    TRUTH_SNAPSHOT_MISMATCH = "truth_snapshot_mismatch"
    QUERY_MISMATCH = "query_mismatch"
    NO_OBSERVATIONS = "no_observations"
    NO_FINANCIAL_IMPACT = "no_financial_impact"
    IMMATURE_SPEND_PRESENT = "immature_spend_present"
    NO_MATURE_SPEND = "no_mature_spend"
    CONVERSION_SIGNAL_PRESENT = "conversion_signal_present"
    CURRENTLY_EXCLUDED = "currently_excluded"
    TARGETING_STATUS_UNCERTAIN = "targeting_status_uncertain"
    LOW_SEMANTIC_SUPPORT = "low_semantic_support"
    OBSERVED_ONLY_NO_EXTRAPOLATION = "observed_only_no_extrapolation"


@dataclass(frozen=True, slots=True)
class EvidenceReason:
    code: EvidenceReasonCode
    message: str
    decisive: bool


@dataclass(frozen=True, slots=True)
class SearchTermEvidenceKey:
    customer_id: str
    campaign_id: str
    ad_group_id: str
    normalized_query: str
    network: str


@dataclass(frozen=True, slots=True)
class SearchTermEvidence:
    key: SearchTermEvidenceKey
    raw_query_examples: tuple[str, ...]
    truth_fingerprint: str
    disposition: EvidenceDisposition
    reasons: tuple[EvidenceReason, ...]
    coverage_band: CoverageBand
    semantic_support: Decimal
    currency_code: str
    mature_cost_micros: int
    immature_cost_micros: int
    mature_clicks: int
    immature_clicks: int
    mature_conversions: Decimal
    mature_conversion_value: Decimal
    mature_all_conversions: Decimal
    mature_all_conversion_value: Decimal
    first_observation_date: date
    last_observation_date: date
    observation_ids: tuple[str, ...]
    targeting_statuses: tuple[str, ...]
    schema_version: int = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError(f"unsupported evidence schema version: {self.schema_version}")
        if self.mature_cost_micros < 0 or self.immature_cost_micros < 0:
            raise ValueError("evidence spend cannot be negative")
        if self.mature_clicks < 0 or self.immature_clicks < 0:
            raise ValueError("evidence clicks cannot be negative")
        if not (Decimal("0") <= self.semantic_support <= Decimal("1")):
            raise ValueError("semantic_support must be in [0, 1]")
        if self.first_observation_date > self.last_observation_date:
            raise ValueError("first_observation_date cannot be after last_observation_date")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("observation_ids must be unique")

    @property
    def mature_cost(self) -> Money:
        return Money(self.mature_cost_micros, self.currency_code)

    @property
    def immature_cost(self) -> Money:
        return Money(self.immature_cost_micros, self.currency_code)

    @property
    def observed_mismatch_cost_micros(self) -> int:
        """Observed spend only; never an estimate of hidden search terms."""
        if self.disposition in {
            EvidenceDisposition.POTENTIALLY_AVOIDABLE,
            EvidenceDisposition.REVIEW_REQUIRED,
            EvidenceDisposition.ALREADY_ADDRESSED,
        }:
            return self.mature_cost_micros + self.immature_cost_micros
        return 0

    @property
    def potentially_avoidable_cost_micros(self) -> int:
        """Conservative candidate amount: mature observed spend only."""
        if self.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE:
            return self.mature_cost_micros
        return 0


@dataclass(frozen=True, slots=True)
class RecoveryEvidenceSummary:
    currency_code: str
    coverage_ratio: Decimal | None
    coverage_band: CoverageBand
    visible_search_term_cost_micros: int
    unobserved_search_cost_micros: int
    potentially_avoidable_observed_cost_micros: int
    review_required_observed_mismatch_cost_micros: int
    already_addressed_observed_mismatch_cost_micros: int
    finding_count: int
    review_required_count: int
    already_addressed_count: int

    @property
    def potentially_avoidable_observed_cost(self) -> Money:
        return Money(self.potentially_avoidable_observed_cost_micros, self.currency_code)

    @property
    def unobserved_search_cost(self) -> Money:
        return Money(self.unobserved_search_cost_micros, self.currency_code)

    @property
    def account_claim(self) -> str:
        return "potentially avoidable observed spend identified"

    @property
    def extrapolated_hidden_waste_micros(self) -> int:
        """Always zero by contract: privacy-hidden search terms are never extrapolated."""
        return 0


def observation_identity_sha256(row: SearchTermObservation) -> str:
    """Stable identity for a reporting row independent of mutable conversion metrics.

    Conversion counts can legitimately change when the same date range is refreshed
    because of conversion lag. Metrics therefore must not be part of source-row identity.
    """

    parts = (
        row.customer_id,
        row.campaign_id,
        row.ad_group_id,
        normalize_query(row.search_term),
        row.date.isoformat(),
        row.network.upper(),
        row.match_source.upper(),
        row.search_term_match_type.upper(),
        row.targeting_status.upper(),
        (row.triggering_keyword or "").casefold(),
        (row.triggering_keyword_match_type or "").upper(),
    )
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# Backward-compatible internal alias used by older Phase-4 code/tests.
_observation_identity = observation_identity_sha256

def _semantic_support(
    assessment: SemanticAssessment, decision: BusinessFitDecision
) -> Decimal:
    """Minimum confidence among the semantic hypotheses that actually decided fit."""

    values: list[Decimal] = []
    decisive_intents = set(decision.decisive_intents)
    decisive_offers = {x.casefold() for x in decision.decisive_offer_ids}
    decisive_nonoffers = {x.casefold() for x in decision.decisive_non_offer_ids}

    values.extend(x.confidence for x in assessment.intents if x.category in decisive_intents)
    values.extend(
        x.confidence
        for x in assessment.offer_candidates
        if x.offer_id.casefold() in decisive_offers
    )
    values.extend(
        x.confidence
        for x in assessment.non_offer_candidates
        if x.exclusion_id.casefold() in decisive_nonoffers
    )
    return min(values) if values else Decimal("0")


class WasteEvidenceEngine:
    """Turn a semantic mismatch into a conservative, auditable money claim.

    Rules:
    - only semantically IRRELEVANT queries are eligible;
    - only conversion-mature spend can enter the potential-avoidability amount;
    - any mature conversion signal blocks automatic financial classification and
      routes the finding to review;
    - current exclusion status means historical spend may be informative but is not a
      new recovery opportunity;
    - privacy-hidden/unobserved spend is never extrapolated.
    """

    def __init__(self, accuracy_policy: AccuracyPolicy) -> None:
        self.accuracy_policy = accuracy_policy

    def evaluate(
        self,
        *,
        assessment: SemanticAssessment,
        fit: BusinessFitDecision,
        truth_fingerprint: str,
        observations: Sequence[SearchTermObservation],
        coverage: CoverageSummary,
        as_of: date,
    ) -> SearchTermEvidence:
        if not observations:
            raise ValueError("at least one search-term observation is required")
        if any(row.date > as_of for row in observations):
            raise ValueError("observation date cannot be after as_of")

        normalized = normalize_query(assessment.raw_query)
        if normalize_query(fit.raw_query) != normalized:
            raise ValueError("assessment and fit refer to different queries")
        if fit.truth_fingerprint != truth_fingerprint:
            raise ValueError("fit decision was produced from a different truth snapshot")
        if any(normalize_query(row.search_term) != normalized for row in observations):
            raise ValueError("all observations must refer to the assessed query")

        key_fields = {
            (row.customer_id, row.campaign_id, row.ad_group_id, row.network.upper())
            for row in observations
        }
        if len(key_fields) != 1:
            raise ValueError(
                "evidence must be scoped to one customer/campaign/ad-group/network"
            )

        currency_codes = {row.currency_code.upper() for row in observations}
        if len(currency_codes) != 1:
            raise ValueError("evidence rows must use exactly one currency")
        currency_code = next(iter(currency_codes))
        if currency_code != coverage.currency_code.upper():
            raise ValueError("coverage and evidence currency must match")

        observation_ids = tuple(observation_identity_sha256(row) for row in observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("duplicate source observations would double-count spend")

        mature_rows: list[SearchTermObservation] = []
        immature_rows: list[SearchTermObservation] = []
        for row in observations:
            maturity = self.accuracy_policy.maturity(row.date, as_of)
            if maturity is DataMaturity.MATURE:
                mature_rows.append(row)
            else:
                immature_rows.append(row)

        mature_cost = sum(row.cost_micros for row in mature_rows)
        immature_cost = sum(row.cost_micros for row in immature_rows)
        mature_clicks = sum(row.clicks for row in mature_rows)
        immature_clicks = sum(row.clicks for row in immature_rows)
        mature_conversions = sum((row.conversions for row in mature_rows), Decimal("0"))
        mature_conversion_value = sum(
            (row.conversions_value for row in mature_rows), Decimal("0")
        )
        mature_all_conversions = sum(
            (row.all_conversions for row in mature_rows), Decimal("0")
        )
        mature_all_conversion_value = sum(
            (row.all_conversions_value for row in mature_rows), Decimal("0")
        )

        statuses = tuple(sorted({row.targeting_status.upper() for row in observations}))
        semantic_support = _semantic_support(assessment, fit)
        reasons: list[EvidenceReason] = []

        disposition = EvidenceDisposition.NOT_SUPPORTED

        if fit.disposition is not FitDisposition.IRRELEVANT:
            reasons.append(
                EvidenceReason(
                    EvidenceReasonCode.SEMANTIC_MISMATCH_NOT_ESTABLISHED,
                    "Phase 3 did not establish a confirmed semantic mismatch.",
                    True,
                )
            )
        elif semantic_support < self.accuracy_policy.minimum_semantic_confidence:
            disposition = EvidenceDisposition.REVIEW_REQUIRED
            reasons.extend(
                [
                    EvidenceReason(
                        EvidenceReasonCode.SEMANTIC_MISMATCH_CONFIRMED,
                        "Business-fit evaluation classified the query as irrelevant.",
                        False,
                    ),
                    EvidenceReason(
                        EvidenceReasonCode.LOW_SEMANTIC_SUPPORT,
                        "Decisive semantic evidence is below the financial-claim threshold.",
                        True,
                    ),
                ]
            )
        else:
            reasons.append(
                EvidenceReason(
                    EvidenceReasonCode.SEMANTIC_MISMATCH_CONFIRMED,
                    "Confirmed business truth and Phase 3 semantics establish irrelevance.",
                    True,
                )
            )

            if mature_cost + immature_cost == 0:
                reasons.append(
                    EvidenceReason(
                        EvidenceReasonCode.NO_FINANCIAL_IMPACT,
                        "The observed mismatch has no recorded spend in this evidence scope.",
                        True,
                    )
                )
                disposition = EvidenceDisposition.NOT_SUPPORTED
            elif len(statuses) != 1:
                reasons.append(
                    EvidenceReason(
                        EvidenceReasonCode.TARGETING_STATUS_UNCERTAIN,
                        "Multiple current targeting statuses were observed for the same evidence scope; classification is withheld.",
                        True,
                    )
                )
                disposition = EvidenceDisposition.REVIEW_REQUIRED
            elif statuses[0] in {"EXCLUDED", "ADDED_EXCLUDED"}:
                reasons.append(
                    EvidenceReason(
                        EvidenceReasonCode.CURRENTLY_EXCLUDED,
                        "Google reports the term as currently excluded; historical spend is not treated as a new recovery opportunity.",
                        True,
                    )
                )
                disposition = EvidenceDisposition.ALREADY_ADDRESSED
            elif statuses[0] in {"UNKNOWN", "UNSPECIFIED"}:
                reasons.append(
                    EvidenceReason(
                        EvidenceReasonCode.TARGETING_STATUS_UNCERTAIN,
                        "Current search-term targeting status is unknown/unspecified.",
                        True,
                    )
                )
                disposition = EvidenceDisposition.REVIEW_REQUIRED
            elif mature_cost <= 0:
                reasons.extend(
                    [
                        EvidenceReason(
                            EvidenceReasonCode.NO_MATURE_SPEND,
                            "All observed spend is still inside the configured conversion-lag window.",
                            True,
                        ),
                        EvidenceReason(
                            EvidenceReasonCode.IMMATURE_SPEND_PRESENT,
                            "Recent spend is retained for review but excluded from the recoverable amount.",
                            False,
                        ),
                    ]
                )
                disposition = EvidenceDisposition.REVIEW_REQUIRED
            elif (
                mature_conversions != 0
                or mature_conversion_value != 0
                or mature_all_conversions != 0
                or mature_all_conversion_value != 0
            ):
                reasons.append(
                    EvidenceReason(
                        EvidenceReasonCode.CONVERSION_SIGNAL_PRESENT,
                        "Mature Google Ads conversion signal exists. Until conversion-action quality is independently validated, the spend cannot be classified as potentially avoidable automatically.",
                        True,
                    )
                )
                disposition = EvidenceDisposition.REVIEW_REQUIRED
            else:
                disposition = EvidenceDisposition.POTENTIALLY_AVOIDABLE
                if immature_cost > 0:
                    reasons.append(
                        EvidenceReason(
                            EvidenceReasonCode.IMMATURE_SPEND_PRESENT,
                            "Only mature spend enters the candidate amount; recent spend remains excluded pending conversion maturity.",
                            False,
                        )
                    )

        reasons.append(
            EvidenceReason(
                EvidenceReasonCode.OBSERVED_ONLY_NO_EXTRAPOLATION,
                "Amount is limited to observed search-term spend. Unobserved privacy-hidden traffic is never extrapolated.",
                False,
            )
        )

        customer_id, campaign_id, ad_group_id, network = next(iter(key_fields))
        raw_examples = tuple(dict.fromkeys(row.search_term for row in observations))

        return SearchTermEvidence(
            key=SearchTermEvidenceKey(
                customer_id=customer_id,
                campaign_id=campaign_id,
                ad_group_id=ad_group_id,
                normalized_query=normalized,
                network=network,
            ),
            raw_query_examples=raw_examples,
            truth_fingerprint=truth_fingerprint,
            disposition=disposition,
            reasons=tuple(reasons),
            coverage_band=coverage.band,
            semantic_support=semantic_support,
            currency_code=currency_code,
            mature_cost_micros=mature_cost,
            immature_cost_micros=immature_cost,
            mature_clicks=mature_clicks,
            immature_clicks=immature_clicks,
            mature_conversions=mature_conversions,
            mature_conversion_value=mature_conversion_value,
            mature_all_conversions=mature_all_conversions,
            mature_all_conversion_value=mature_all_conversion_value,
            first_observation_date=min(row.date for row in observations),
            last_observation_date=max(row.date for row in observations),
            observation_ids=observation_ids,
            targeting_statuses=statuses,
        )


def summarize_recovery_evidence(
    findings: Iterable[SearchTermEvidence], coverage: CoverageSummary
) -> RecoveryEvidenceSummary:
    items = list(findings)
    if items:
        currencies = {x.currency_code for x in items}
        if currencies != {coverage.currency_code.upper()}:
            raise ValueError("all findings and coverage must use the same currency")
        if any(x.coverage_band is not coverage.band for x in items):
            raise ValueError("finding coverage band does not match summary coverage")

    # Prevent accidental double counting when callers submit overlapping findings.
    all_ids: list[str] = [oid for item in items for oid in item.observation_ids]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("findings overlap source observations; summary would double-count spend")

    potential = sum(x.potentially_avoidable_cost_micros for x in items)
    review = sum(
        x.observed_mismatch_cost_micros
        for x in items
        if x.disposition is EvidenceDisposition.REVIEW_REQUIRED
    )
    addressed = sum(
        x.observed_mismatch_cost_micros
        for x in items
        if x.disposition is EvidenceDisposition.ALREADY_ADDRESSED
    )
    if potential + review + addressed > coverage.visible_search_term_cost_micros:
        raise ValueError(
            "evidence spend exceeds visible search-term spend; coverage/evidence windows likely differ"
        )

    return RecoveryEvidenceSummary(
        currency_code=coverage.currency_code.upper(),
        coverage_ratio=coverage.ratio,
        coverage_band=coverage.band,
        visible_search_term_cost_micros=coverage.visible_search_term_cost_micros,
        unobserved_search_cost_micros=coverage.unobserved_cost_micros,
        potentially_avoidable_observed_cost_micros=potential,
        review_required_observed_mismatch_cost_micros=review,
        already_addressed_observed_mismatch_cost_micros=addressed,
        finding_count=sum(
            1 for x in items if x.disposition is EvidenceDisposition.POTENTIALLY_AVOIDABLE
        ),
        review_required_count=sum(
            1 for x in items if x.disposition is EvidenceDisposition.REVIEW_REQUIRED
        ),
        already_addressed_count=sum(
            1 for x in items if x.disposition is EvidenceDisposition.ALREADY_ADDRESSED
        ),
    )
