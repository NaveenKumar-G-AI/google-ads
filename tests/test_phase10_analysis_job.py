from datetime import date
from decimal import Decimal
from recovery.db.canonical import canonical_payload
from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.worker.analysis_job import _search_row, _spend_row


def test_search_observation_roundtrip_preserves_decimal_and_date():
    row=SearchTermObservation(
        customer_id="1234567890",campaign_id="1",campaign_name="C",ad_group_id="2",ad_group_name="A",
        search_term="roof jobs",date=date(2026,10,1),network="SEARCH",match_source="AD_GROUP",
        search_term_match_type="BROAD",targeting_status="NONE",triggering_keyword="roof",triggering_keyword_match_type="BROAD",
        impressions=10,clicks=2,cost_micros=1234,conversions=Decimal("0.5"),conversions_value=Decimal("10.25"),
        all_conversions=Decimal("0.5"),all_conversions_value=Decimal("10.25"),currency_code="USD",
    )
    assert _search_row(canonical_payload(row))==row


def test_campaign_spend_roundtrip():
    row=CampaignSpendObservation("1234567890","1","C",date(2026,10,1),"SEARCH",9000,"USD")
    assert _spend_row(canonical_payload(row))==row
