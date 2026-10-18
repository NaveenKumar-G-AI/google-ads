from datetime import date
from decimal import Decimal

import pytest

from recovery.domain import (
    CampaignSpendObservation,
    CoverageBand,
    Money,
    SearchTermObservation,
    summarize_coverage,
)


def term(cost: int, network: str = "SEARCH") -> SearchTermObservation:
    return SearchTermObservation(
        customer_id="1",
        campaign_id="10",
        campaign_name="Search",
        ad_group_id="20",
        ad_group_name="Roofing",
        search_term="roof repair dallas",
        date=date(2026, 9, 1),
        network=network,
        match_source="ADVERTISER_PROVIDED_KEYWORD",
        search_term_match_type="BROAD",
        targeting_status="NONE",
        triggering_keyword="roof repair",
        triggering_keyword_match_type="BROAD",
        impressions=100,
        clicks=10,
        cost_micros=cost,
        conversions=Decimal("1"),
        conversions_value=Decimal("0"),
        all_conversions=Decimal("1"),
        all_conversions_value=Decimal("0"),
        currency_code="USD",
    )


def campaign(cost: int, network: str = "SEARCH") -> CampaignSpendObservation:
    return CampaignSpendObservation(
        customer_id="1",
        campaign_id="10",
        campaign_name="Search",
        date=date(2026, 9, 1),
        network=network,
        cost_micros=cost,
        currency_code="USD",
    )


def test_money_preserves_micros_without_float_error() -> None:
    money = Money(1_234_567, "usd")
    assert money.currency_code == "USD"
    assert money.units == Decimal("1.234567")
    assert money.format() == "USD 1.23"


def test_coverage_uses_search_and_search_partners_only() -> None:
    result = summarize_coverage(
        [term(800_000), term(100_000, "SEARCH_PARTNERS")],
        [campaign(1_000_000), campaign(200_000, "SEARCH_PARTNERS")],
    )
    assert result.ratio == Decimal("0.75")
    assert result.band == CoverageBand.MEDIUM
    assert result.unobserved_cost_micros == 300_000


def test_cross_currency_coverage_is_rejected() -> None:
    bad = campaign(1_000_000)
    object.__setattr__(bad, "currency_code", "INR")
    with pytest.raises(ValueError):
        summarize_coverage([term(500_000)], [bad])


def test_coverage_never_exposes_more_than_one() -> None:
    result = summarize_coverage([term(1_100_000)], [campaign(1_000_000)])
    assert result.ratio == Decimal("1")
