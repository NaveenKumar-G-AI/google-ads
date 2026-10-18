from datetime import date
from pathlib import Path
from recovery.google_ads.gaql import campaign_performance_segments_query,user_location_performance_query,geo_target_constants_query

ROOT=Path(__file__).resolve().parents[1]

def test_device_daypart_network_source_is_search_campaign_performance_not_search_term_projection():
    q=campaign_performance_segments_query(date(2026,10,1),date(2026,10,7))
    assert "FROM campaign" in q
    for f in ("segments.device","segments.day_of_week","segments.hour","segments.ad_network_type","metrics.cost_micros","metrics.conversions"):
        assert f in q
    assert "campaign.advertising_channel_type = 'SEARCH'" in q

def test_geo_source_uses_physical_user_location_view_not_location_target_view():
    q=user_location_performance_query(date(2026,10,1),date(2026,10,7))
    assert "FROM user_location_view" in q
    assert "user_location_view.country_criterion_id" in q
    assert "segments.geo_target_most_specific_location" in q
    assert "FROM location_view" not in q

def test_geo_metadata_query_is_resource_bounded_and_validated():
    q=geo_target_constants_query(("geoTargetConstants/1007796",))
    assert "geo_target_constant.canonical_name" in q and "geo_target_constant.country_code" in q
    assert "geoTargetConstants/1007796" in q

def test_dimension_commit_happens_before_core_chunk_completion():
    src=(ROOT/'src/recovery/google_ads/sync.py').read_text()
    assert src.index('commit_dimensions(chunk=chunk') < src.index('store.commit_chunk(chunk=chunk')

def test_device_and_daypart_api_are_diagnostic_not_derived_waste_money():
    src=(ROOT/'src/recovery/api/repository.py').read_text()
    assert 'financial_claim_supported' in src
    assert 'Observed performance only. Device/daypart zero conversions or weak ratios are not, by themselves, proof of waste.' in src
    assert '"financial_claim_supported":False' in src

def test_query_and_geo_money_are_not_added_into_one_overview_total():
    src=(ROOT/'src/recovery/api/repository.py').read_text()
    assert 'query_potentially_avoidable_observed_micros' in src
    assert 'geo_potentially_avoidable_observed_micros' in src
    assert 'query_candidate+geo_candidate' not in src.replace(' ','')
