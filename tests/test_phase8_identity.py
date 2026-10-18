from datetime import date
from decimal import Decimal

from recovery.db.canonical import payload_sha256
from recovery.db.identity import campaign_spend_identity_sha256, stable_chunk_payload
from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.evidence import observation_identity_sha256


def term(*, conversions=Decimal("0"), cost=1000000):
    return SearchTermObservation(
        customer_id="123",
        campaign_id="10",
        campaign_name="Search",
        ad_group_id="20",
        ad_group_name="Roof",
        search_term="Roof Jobs",
        date=date(2026, 10, 1),
        network="SEARCH",
        match_source="BROAD",
        search_term_match_type="BROAD",
        targeting_status="NONE",
        triggering_keyword="roof repair",
        triggering_keyword_match_type="BROAD",
        impressions=10,
        clicks=2,
        cost_micros=cost,
        conversions=conversions,
        conversions_value=Decimal("0"),
        all_conversions=conversions,
        all_conversions_value=Decimal("0"),
        currency_code="USD",
    )


def spend(cost=2000000):
    return CampaignSpendObservation(
        customer_id="123",
        campaign_id="10",
        campaign_name="Search",
        date=date(2026, 10, 1),
        network="SEARCH",
        cost_micros=cost,
        currency_code="USD",
    )


def test_conversion_lag_keeps_logical_identity_but_creates_new_payload_version():
    earlier = term(conversions=Decimal("0"))
    later = term(conversions=Decimal("1"))
    assert observation_identity_sha256(earlier) == observation_identity_sha256(later)
    assert payload_sha256(earlier) != payload_sha256(later)


def test_campaign_metric_refresh_keeps_identity_but_changes_payload():
    earlier = spend(2000000)
    later = spend(2500000)
    assert campaign_spend_identity_sha256(earlier) == campaign_spend_identity_sha256(later)
    assert payload_sha256(earlier) != payload_sha256(later)


def test_chunk_checksum_is_order_independent():
    t1 = term(cost=1000000)
    t2 = SearchTermObservation(**{**t1.__dict__, "search_term": "roof careers"}) if hasattr(t1, '__dict__') else SearchTermObservation(
        customer_id="123", campaign_id="10", campaign_name="Search", ad_group_id="20",
        ad_group_name="Roof", search_term="roof careers", date=date(2026,10,1),
        network="SEARCH", match_source="BROAD", search_term_match_type="BROAD",
        targeting_status="NONE", triggering_keyword="roof repair",
        triggering_keyword_match_type="BROAD", impressions=8, clicks=1, cost_micros=500000,
        conversions=Decimal("0"), conversions_value=Decimal("0"), all_conversions=Decimal("0"),
        all_conversions_value=Decimal("0"), currency_code="USD"
    )
    s1 = spend(3000000)
    one = stable_chunk_payload(
        api_version="v26", sync_schema_version=1, chunk_start="2026-10-01", chunk_end="2026-10-01",
        search_terms=[t1, t2], campaign_spend=[s1], currency_code="USD"
    )
    two = stable_chunk_payload(
        api_version="v26", sync_schema_version=1, chunk_start="2026-10-01", chunk_end="2026-10-01",
        search_terms=[t2, t1], campaign_spend=[s1], currency_code="USD"
    )
    assert payload_sha256(one) == payload_sha256(two)


def test_chunk_rejects_visible_spend_above_denominator():
    import pytest
    with pytest.raises(ValueError, match="exceeds"):
        stable_chunk_payload(
            api_version="v26", sync_schema_version=1, chunk_start="2026-10-01", chunk_end="2026-10-01",
            search_terms=[term(cost=3000000)], campaign_spend=[spend(2000000)], currency_code="USD"
        )
