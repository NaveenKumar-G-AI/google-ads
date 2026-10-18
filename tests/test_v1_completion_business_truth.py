from datetime import date,datetime,timezone
from decimal import Decimal
import pytest
from recovery.onboarding import (
    build_guided_business_truth_payload,GuidedOfferInput,GuidedProtectedQueryInput,
    GuidedAudienceInput,GuidedGeoAreaInput,
)
from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.negative_keywords import SafeNegativeKeywordEngine,ScopeEvidenceBundle,ProposalDisposition,ProposalRisk,ProtectedQuery
from recovery.domain import CoverageBand
from recovery.evidence import SearchTermEvidence,SearchTermEvidenceKey,EvidenceDisposition


def test_guided_truth_round_trip_supports_richer_v1_business_truth():
    now=datetime(2026,10,16,tzinfo=timezone.utc)
    payload=build_guided_business_truth_payload(
        business_id='b1',business_name='Acme',version=2,actor='user:test',
        offers=(GuidedOfferInput('Roof repair','Residential roof repair',('leak repair',)),),
        non_offers=(),service_areas=(GuidedGeoAreaInput('Chennai','IN','Tamil Nadu','Chennai',None),),
        catalog_complete=True,employment_policy='deny',free_policy='conditional',diy_policy='deny',
        primary_outcomes=('Qualified lead',),supporting_outcomes=('Phone call',),invalid_outcomes=('Page view',),
        additional_intent_policies=(('competitor','conditional'),('support','allow')),
        audience_policies=(GuidedAudienceInput('Homeowners','allow','Residential buyer',('property owner',)),),
        protected_queries=(GuidedProtectedQueryInput('acme roofing','Brand query must remain eligible'),),
        now=now,
    )
    truth=parse_business_truth_payload(payload,submitted_by='user:test',submitted_at=now)
    assert truth.version==2 and truth.supersedes_version==1
    assert truth.confirmed_intent_policy(next(p.category for p in truth.intent_policies if p.category.value=='competitor')).disposition.value=='conditional'
    assert truth.audience_policies[0].name=='Homeowners'
    assert truth.confirmed_protected_queries()[0].query=='acme roofing'
    assert {x.role.value for x in truth.outcomes}=={'primary_business_outcome','supporting_signal','not_a_business_outcome'}


def test_duplicate_protected_query_is_rejected_semantically():
    now=datetime(2026,10,16,tzinfo=timezone.utc)
    with pytest.raises(ValueError,match='duplicate protected query'):
        build_guided_business_truth_payload(
            business_id='b1',business_name='Acme',version=1,actor='u',
            offers=(GuidedOfferInput('Repair','Repair service'),),non_offers=(),service_areas=(),catalog_complete=False,
            employment_policy='unknown',free_policy='unknown',diy_policy='unknown',primary_outcomes=('Sale',),
            protected_queries=(GuidedProtectedQueryInput('ACME','brand'),GuidedProtectedQueryInput('  acme  ','brand duplicate')),now=now,
        )


def test_business_truth_protected_query_blocks_negative_candidate():
    key=SearchTermEvidenceKey(customer_id='1',campaign_id='10',ad_group_id='20',normalized_query='acme roofing',network='SEARCH')
    finding=SearchTermEvidence(
        key=key,raw_query_examples=('acme roofing',),truth_fingerprint='a'*64,
        disposition=EvidenceDisposition.POTENTIALLY_AVOIDABLE,reasons=(),coverage_band=CoverageBand.HIGH,
        semantic_support=Decimal('0.99'),currency_code='USD',mature_cost_micros=1000000,
        immature_cost_micros=0,mature_clicks=2,immature_clicks=0,mature_conversions=Decimal('0'),
        mature_conversion_value=Decimal('0'),mature_all_conversions=Decimal('0'),mature_all_conversion_value=Decimal('0'),
        first_observation_date=date(2026,10,1),last_observation_date=date(2026,10,15),
        observation_ids=('o1',),targeting_statuses=('NONE',),
    )
    bundle=ScopeEvidenceBundle(findings=(finding,),complete_for_scope=True,snapshot_id='s1')
    protected=(ProtectedQuery(query='acme roofing',customer_id='1',campaign_id='10',ad_group_id=None,reason='Confirmed brand traffic',source='business_truth_protected_query'),)
    proposal=SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle,protected_queries=protected)
    assert proposal.disposition is ProposalDisposition.BLOCKED
    assert proposal.risk is ProposalRisk.BLOCKED
    assert proposal.protected_query_collisions[0].source=='business_truth_protected_query'
