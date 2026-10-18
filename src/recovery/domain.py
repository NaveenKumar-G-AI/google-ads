from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Iterable

MICROS_PER_UNIT = Decimal("1000000")


class DataMaturity(str, Enum):
    MATURE = "mature"
    IMMATURE = "immature"


class CoverageBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class FindingConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class Money:
    """Money stored in integer micros to avoid floating-point currency errors."""

    micros: int
    currency_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.micros, int):
            raise TypeError("micros must be an int")
        code = self.currency_code.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency_code must be a 3-letter ISO-style code")
        object.__setattr__(self, "currency_code", code)

    @property
    def units(self) -> Decimal:
        return Decimal(self.micros) / MICROS_PER_UNIT

    def format(self, places: int = 2) -> str:
        q = Decimal(1).scaleb(-places)
        value = self.units.quantize(q, rounding=ROUND_HALF_UP)
        return f"{self.currency_code} {value}"

    def __add__(self, other: Money) -> Money:
        if self.currency_code != other.currency_code:
            raise ValueError("cannot add different currencies")
        return Money(self.micros + other.micros, self.currency_code)


@dataclass(frozen=True, slots=True)
class SearchTermObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    ad_group_id: str
    ad_group_name: str
    search_term: str
    date: date
    network: str
    match_source: str
    search_term_match_type: str
    targeting_status: str
    triggering_keyword: str | None
    triggering_keyword_match_type: str | None
    impressions: int
    clicks: int
    cost_micros: int
    conversions: Decimal
    conversions_value: Decimal
    all_conversions: Decimal
    all_conversions_value: Decimal
    currency_code: str

    def __post_init__(self) -> None:
        if self.cost_micros < 0 or self.clicks < 0 or self.impressions < 0:
            raise ValueError("Google Ads metrics cannot be negative")
        if self.clicks > self.impressions:
            # Defensive only: certain interaction metrics can differ, but clicks should not
            # exceed impressions in normal Search reporting. We reject surprising input
            # rather than silently corrupting an audit.
            raise ValueError("clicks cannot exceed impressions for Search observation")
        if not self.search_term.strip():
            raise ValueError("search_term cannot be blank")

    @property
    def cost(self) -> Money:
        return Money(self.cost_micros, self.currency_code)


@dataclass(frozen=True, slots=True)
class CampaignSpendObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    date: date
    network: str
    cost_micros: int
    currency_code: str

    def __post_init__(self) -> None:
        if self.cost_micros < 0:
            raise ValueError("cost_micros cannot be negative")


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    visible_search_term_cost_micros: int
    eligible_search_campaign_cost_micros: int
    currency_code: str

    @property
    def ratio(self) -> Decimal | None:
        total = self.eligible_search_campaign_cost_micros
        if total <= 0:
            return None
        ratio = Decimal(self.visible_search_term_cost_micros) / Decimal(total)
        # Privacy/reporting behavior can make source totals imperfectly aligned.
        # Never expose >100% as a meaningful coverage value.
        return min(ratio, Decimal("1"))

    @property
    def band(self) -> CoverageBand:
        ratio = self.ratio
        if ratio is None:
            return CoverageBand.UNKNOWN
        if ratio >= Decimal("0.80"):
            return CoverageBand.HIGH
        if ratio >= Decimal("0.50"):
            return CoverageBand.MEDIUM
        return CoverageBand.LOW

    @property
    def unobserved_cost_micros(self) -> int:
        return max(
            self.eligible_search_campaign_cost_micros
            - self.visible_search_term_cost_micros,
            0,
        )


def summarize_coverage(
    search_terms: Iterable[SearchTermObservation],
    campaign_spend: Iterable[CampaignSpendObservation],
) -> CoverageSummary:
    term_rows = list(search_terms)
    campaign_rows = list(campaign_spend)

    currency_codes = {
        *(r.currency_code.upper() for r in term_rows),
        *(r.currency_code.upper() for r in campaign_rows),
    }
    if len(currency_codes) != 1:
        raise ValueError("coverage must be calculated for exactly one currency")

    allowed_networks = {"SEARCH", "SEARCH_PARTNERS"}
    visible = sum(
        r.cost_micros for r in term_rows if r.network.upper() in allowed_networks
    )
    total = sum(
        r.cost_micros for r in campaign_rows if r.network.upper() in allowed_networks
    )

    return CoverageSummary(
        visible_search_term_cost_micros=visible,
        eligible_search_campaign_cost_micros=total,
        currency_code=next(iter(currency_codes)),
    )
