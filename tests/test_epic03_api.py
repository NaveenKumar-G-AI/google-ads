from datetime import date,datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole
from recovery.api.repository import Membership

TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();VIEW=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@example.test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={'Authorization':'Bearer t'}

class Repo:
    def __init__(self,role=TenantRole.ANALYST): self.role=role
    def touch_user(self,**kwargs): return True
    def list_memberships(self,**kwargs): return []
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,'active') if user_id==USER and tenant_id==TENANT else None
    def ensure_account(self,*,tenant_id,account_id):
        if tenant_id!=TENANT or account_id!=ACCOUNT: raise RuntimeError('bad scope')
    def search_intelligence_overview(self,**kwargs):
        return {'account_id':ACCOUNT,'currency_code':'USD','window':{'start':date(2026,10,1),'end':date(2026,10,7),'min_available':date(2026,9,1),'max_available':date(2026,10,15)},'distinct_queries':2,'impressions':100,'clicks':10,'cost_micros':20_000_000,'conversions':'1','conversions_value':'100','potentially_avoidable_observed_micros':5_000_000,'review_required_observed_micros':0,'latest_analysis_run_id':None,'latest_analysis_completed_at':None,'analysis_window_matches':True,'fit_counts':{'exclude':1},'evidence_counts':{'eligible':1},'coverage':{'currency_code':'USD','visible_search_term_micros':20_000_000,'comparable_search_campaign_micros':25_000_000,'unobserved_search_micros':5_000_000,'coverage_ratio':'0.8','coverage_band':'high','note':'No hidden-query extrapolation.'}}
    def list_search_saved_views(self,**kwargs): return []
    def create_search_saved_view(self,**kwargs): return {'id':VIEW,'account_id':ACCOUNT,'portfolio_id':None,'name':kwargs['name'],'filters':kwargs['filters'],'is_default':False,'created_at':NOW,'updated_at':NOW}
    def delete_search_saved_view(self,**kwargs): return None

def client(role=TenantRole.ANALYST): return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P})))

def test_viewer_can_read_search_intelligence_overview():
    r=client(TenantRole.VIEWER).get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/search-intelligence/overview',headers=HEAD)
    assert r.status_code==200 and r.json()['coverage']['unobserved_search_micros']==5_000_000

def test_viewer_cannot_create_saved_view_but_analyst_can():
    body={'name':'High spend','account_id':str(ACCOUNT),'filters':{'sort':'cost'}}
    assert client(TenantRole.VIEWER).post(f'/v1/tenants/{TENANT}/search-intelligence/saved-views',headers=HEAD,json=body).status_code==403
    r=client(TenantRole.ANALYST).post(f'/v1/tenants/{TENANT}/search-intelligence/saved-views',headers=HEAD,json=body)
    assert r.status_code==201 and r.json()['name']=='High spend'

def test_search_endpoint_rejects_partial_date_window_at_repository_boundary():
    class BadRepo(Repo):
        def search_intelligence_overview(self,**kwargs):
            if (kwargs['start'] is None)!=(kwargs['end'] is None): raise ValueError('start and end must be supplied together')
            return super().search_intelligence_overview(**kwargs)
    c=TestClient(create_app(repository=BadRepo(),verifier=StaticTokenVerifier({'t':P})))
    r=c.get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/search-intelligence/overview?start=2026-10-01',headers=HEAD)
    assert r.status_code==400 and r.json()['error']['code']=='INVALID_REQUEST'

def test_saved_view_requires_exactly_one_scope_at_validation_boundary():
    r=client(TenantRole.ANALYST).post(f'/v1/tenants/{TENANT}/search-intelligence/saved-views',headers=HEAD,json={'name':'bad','filters':{}})
    assert r.status_code==422 and r.json()['error']['code']=='VALIDATION_FAILED'
