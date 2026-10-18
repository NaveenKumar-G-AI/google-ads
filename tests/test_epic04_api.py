from datetime import date,datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole
from recovery.api.repository import Membership

TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='viewer@example.test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={'Authorization':'Bearer t'}
W={'start':date(2026,10,1),'end':date(2026,10,7),'min_available':date(2026,9,1),'max_available':date(2026,10,15)}

class Repo:
    def __init__(self,role=TenantRole.VIEWER): self.role=role
    def touch_user(self,**kwargs): return True
    def list_memberships(self,**kwargs): return []
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,'active') if user_id==USER and tenant_id==TENANT else None
    def ensure_account(self,*,tenant_id,account_id):
        if tenant_id!=TENANT or account_id!=ACCOUNT: raise RuntimeError('bad scope')
    def waste_intelligence_overview(self,**kwargs): return {'account_id':ACCOUNT,'window':W,'currency_code':'INR','analysis_run_id':None,'analysis_window_matches':True,'query_potentially_avoidable_observed_micros':1_000_000,'query_review_required_observed_micros':0,'geo_potentially_avoidable_observed_micros':0,'geo_review_required_observed_micros':0,'families':[{'leak_family':'employment','query_count':1,'potentially_avoidable_observed_micros':1_000_000,'review_required_observed_micros':0,'already_addressed_observed_micros':0}],'dimension_data_ready':True,'geo_data_ready':False,'geo_evaluation_ready':False,'financial_note':'separate lenses'}
    def waste_intelligence_query_leaks(self,**kwargs): return {'window':W,'currency_code':'INR','analysis_run_id':None,'financial_evidence_in_window':True,'page':1,'page_size':50,'total':1,'rows':[{'normalized_query':'jobs','raw_query_example':'roofing jobs','leak_family':'employment','disposition':'potentially_avoidable','impressions':10,'clicks':2,'cost_micros':1_000_000,'conversions':'0','networks':['SEARCH'],'finding_count':1,'potentially_avoidable_observed_micros':1_000_000,'review_required_observed_micros':0,'already_addressed_observed_micros':0}]}
    def waste_intelligence_dimension(self,**kwargs): return {'window':W,'currency_code':'INR','dimension':kwargs['dimension'],'rows':[{'key':'MOBILE','query_count':0,'impressions':100,'clicks':10,'cost_micros':2_000_000,'conversions':'0','conversions_value':'0','potentially_avoidable_observed_micros':0,'review_required_observed_micros':0,'financial_claim_supported':False}],'note':'diagnostic only'}
    def waste_intelligence_geo(self,**kwargs): return {'window':W,'currency_code':'INR','evaluation_ready':False,'analysis_run_id':None,'truth_snapshot_id':None,'rows':[],'note':'no geo evidence'}

def client(role=TenantRole.VIEWER): return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P})))

def test_viewer_can_read_waste_overview_and_money_classes_are_separate():
    r=client().get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/waste-intelligence/overview',headers=HEAD)
    assert r.status_code==200
    data=r.json()
    assert data['query_potentially_avoidable_observed_micros']==1_000_000
    assert data['geo_potentially_avoidable_observed_micros']==0

def test_waste_query_api_exposes_primary_family_and_evidence_state():
    r=client().get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/waste-intelligence/queries?family=employment',headers=HEAD)
    assert r.status_code==200
    assert r.json()['rows'][0]['leak_family']=='employment'
    assert r.json()['rows'][0]['disposition']=='potentially_avoidable'

def test_dimension_endpoint_rejects_unknown_dimension_at_validation_boundary():
    r=client().get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/waste-intelligence/dimension?dimension=browser',headers=HEAD)
    assert r.status_code==422

def test_device_dimension_explicitly_has_no_financial_claim():
    r=client().get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/waste-intelligence/dimension?dimension=device',headers=HEAD)
    assert r.status_code==200
    assert r.json()['rows'][0]['financial_claim_supported'] is False
    assert r.json()['rows'][0]['potentially_avoidable_observed_micros']==0
