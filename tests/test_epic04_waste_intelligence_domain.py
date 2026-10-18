from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from recovery.accuracy import AccuracyPolicy
from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CustomerLocationRequirement,
    EvidenceKind, EvidenceRef, GeoArea, GeoPolicy, TruthBasis, TruthStatus,
)
from recovery.waste_intelligence import (
    CampaignPerformanceSegmentObservation, LeakFamily, LeakFinding,
    UserLocationObservation, evaluate_geo_leaks, geo_location_fit,
    query_leak_family, summarize_query_leaks,
)

NOW=datetime(2026,10,16,tzinfo=timezone.utc)

def truth(requirement=CustomerLocationRequirement.CUSTOMER_MUST_BE_IN_SERVICE_AREA, areas=None):
    ev=EvidenceRef(evidence_id="owner-geo",kind=EvidenceKind.OPERATOR,reference="Owner confirmed service area",captured_at=NOW)
    basis=TruthBasis(status=TruthStatus.CONFIRMED,evidence_ids=("owner-geo",),confirmed_by="owner@example.test",confirmed_at=NOW)
    if areas is None: areas=(GeoArea("chennai","Chennai, Tamil Nadu","IN",region="Tamil Nadu",city="Chennai",google_geo_target_constant="geoTargetConstants/1007796"),)
    geo=GeoPolicy(requirement=requirement,included_areas=tuple(areas),excluded_areas=(),basis=basis)
    return BusinessTruthSnapshot(business_id="b",business_name="Business",version=1,created_at=NOW,created_by="owner@example.test",offer_catalog_completeness=CatalogCompleteness.COMPLETE,audience_catalog_completeness=CatalogCompleteness.UNKNOWN,offers=(),geo_policy=geo,evidence=(ev,))

def loc(*, resource="geoTargetConstants/1023191", name="Bengaluru", canonical="Bengaluru, Karnataka, India", country="IN", target_type="City", when=date(2026,9,1), cost=1_000_000, conversions="0", all_conversions="0"):
    return UserLocationObservation(customer_id="123",campaign_id="1",campaign_name="Search",date=when,network="SEARCH",targeting_location=False,country_criterion_id="2356",location_resource=resource,location_name=name,canonical_name=canonical,country_code=country,target_type=target_type,impressions=100,clicks=10,cost_micros=cost,conversions=Decimal(conversions),conversions_value=Decimal("0"),all_conversions=Decimal(all_conversions),all_conversions_value=Decimal("0"),currency_code="INR")

def test_query_leak_family_is_one_primary_business_reason():
    assert query_leak_family(semantic=None,fit={"disposition":"relevant"}) is None
    assert query_leak_family(semantic=None,fit={"disposition":"irrelevant","decisive_non_offer_ids":["solar"],"decisive_intents":["employment"]}) is LeakFamily.WRONG_SERVICE
    assert query_leak_family(semantic=None,fit={"disposition":"irrelevant","decisive_intents":["employment","free"]}) is LeakFamily.EMPLOYMENT
    assert query_leak_family(semantic=None,fit={"disposition":"irrelevant","decisive_intents":["custom-denied"]}) is LeakFamily.OTHER_DENIED_INTENT
    assert query_leak_family(semantic=None,fit={"disposition":"irrelevant"}) is LeakFamily.IRRELEVANT_INTENT

def test_query_leak_totals_refuse_overlapping_source_observations():
    a=LeakFinding(LeakFamily.EMPLOYMENT,"candidate","INR",100,0,0,("obs-1",))
    b=LeakFinding(LeakFamily.FREE,"candidate","INR",200,0,0,("obs-1",))
    with pytest.raises(ValueError,match="double count"):
        summarize_query_leaks((a,b))

def test_physical_location_can_evaluate_customer_presence_policy():
    fit,reason=geo_location_fit(truth(),loc())
    assert fit=="irrelevant" and "does not match" in reason
    fit,_=geo_location_fit(truth(),loc(resource="geoTargetConstants/1007796",name="Chennai",canonical="Chennai, Tamil Nadu, India"))
    assert fit=="relevant"

def test_country_level_user_location_is_too_coarse_for_city_service_area():
    fit,reason=geo_location_fit(truth(),loc(resource="geoTargetConstants/2356",name="India",canonical="India",target_type="Country"))
    assert fit=="unknown" and "too coarse" in reason

def test_physical_user_location_cannot_prove_job_destination_leakage():
    t=truth(CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA)
    fit,reason=geo_location_fit(t,loc(country="US",name="New York",canonical="New York, United States"))
    assert fit=="unknown"
    assert "job or destination" in reason

def test_geo_mismatch_needs_mature_evidence_and_conversion_conflicts_route_to_review():
    p=AccuracyPolicy(conversion_lag_days=7)
    t=truth()
    candidate=evaluate_geo_leaks(truth=t,rows=[loc()],policy=p,as_of=date(2026,10,16))[0]
    assert candidate.disposition=="potentially_avoidable"
    assert candidate.potentially_avoidable_observed_micros==1_000_000
    converted=evaluate_geo_leaks(truth=t,rows=[loc(conversions="1")],policy=p,as_of=date(2026,10,16))[0]
    assert converted.disposition=="review_required" and converted.review_required_observed_micros==1_000_000
    immature=evaluate_geo_leaks(truth=t,rows=[loc(when=date(2026,10,15))],policy=p,as_of=date(2026,10,16))[0]
    assert immature.disposition=="review_required" and immature.potentially_avoidable_observed_micros==0

def test_dimension_observation_rejects_impossible_metrics():
    with pytest.raises(ValueError,match="clicks cannot exceed impressions"):
        CampaignPerformanceSegmentObservation(customer_id="123",campaign_id="1",campaign_name="x",date=date(2026,10,1),network="SEARCH",device="MOBILE",day_of_week="MONDAY",hour=8,impressions=3,clicks=4,cost_micros=1,conversions=Decimal(0),conversions_value=Decimal(0),all_conversions=Decimal(0),all_conversions_value=Decimal(0),currency_code="INR")
