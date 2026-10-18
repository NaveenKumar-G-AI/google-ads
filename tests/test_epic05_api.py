from datetime import date,datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership

TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();SNAP=uuid4();SYNC=uuid4();TRUTH=uuid4();EVENT=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='viewer@example.test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={'Authorization':'Bearer t'}
RESOURCE='customers/123/conversionActions/1'

class Repo:
    def __init__(self,role=TenantRole.VIEWER): self.role=role
    def touch_user(self,**kwargs): return True
    def list_memberships(self,**kwargs): return []
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,'active') if user_id==USER and tenant_id==TENANT else None
    def ensure_account(self,*,tenant_id,account_id):
        if tenant_id!=TENANT or account_id!=ACCOUNT: raise RuntimeError('bad scope')
    def measurement_integrity_overview(self,**kwargs): return {'account_id':ACCOUNT,'measurement_snapshot_id':SNAP,'sync_run_id':SYNC,'sync_completed_at':NOW,'window_start':date(2026,10,1),'window_end':date(2026,10,15),'confidence':'constrained','enabled_actions':1,'primary_actions':1,'mapped_primary_actions':0,'conversion_dependent_claims_allowed':False,'recovery_verification_allowed':False,'configured_conversion_lag_days':7,'customer_goal_count':1,'campaign_goal_count':1,'campaign_specific_goal_config_count':0,'issues':[{'code':'primary_action_unmapped','severity':'warning','message':'map it','conversion_action_resource':RESOURCE,'campaign_id':None}],'available_outcomes':[{'outcome_id':'qualified','name':'Qualified lead','role':'primary_business_outcome','confirmed':True}],'note':'evidence state'}
    def measurement_conversion_actions(self,**kwargs): return [{'resource_name':RESOURCE,'action_id':'1','name':'Lead','status':'ENABLED','action_type':'WEBPAGE','category':'QUALIFIED_LEAD','origin':'WEBSITE','owner_customer':'customers/123','primary_for_goal':True,'account_default_goal_biddable':True,'counting_type':'ONE_PER_CLICK','click_through_lookback_days':30,'view_through_lookback_days':1,'attribution_model':'GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN','data_driven_model_status':'AVAILABLE','default_value':'1','default_currency_code':'INR','always_use_default_value':False,'all_conversions':'3','all_conversions_value':'3','last_conversion_date':date(2026,10,10),'last_received_request_at':'2026-10-10 12:00:00','mapped_outcome_id':None,'mapped_outcome_role':None,'mapping_confirmed':False,'mapping_is_current_truth':False,'mapping_status':None,'enhanced_conversions_status':'not_observable_from_conversion_action_resource'}]
    def measurement_goals(self,**kwargs): return {'customer_goals':[],'campaign_goals':[],'campaign_configs':[],'note':'separate'}
    def measurement_lag(self,**kwargs): return {'configured_conversion_lag_days':7,'rows':[],'note':'provider buckets'}
    def record_conversion_action_mapping(self,**kwargs): return {'id':EVENT,'conversion_action_resource':kwargs['conversion_action_resource'],'truth_snapshot_id':TRUTH,'outcome_id':kwargs['outcome_id'],'mapping_status':'mapped' if kwargs['outcome_id'] else 'cleared','created_at':NOW}

def client(role=TenantRole.VIEWER): return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P})))

def test_viewer_can_read_measurement_but_not_map():
    c=client()
    assert c.get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/measurement-integrity/overview',headers=HEAD).status_code==200
    r=c.post(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/measurement-integrity/mappings',headers=HEAD,json={'conversion_action_resource':RESOURCE,'outcome_id':'qualified'})
    assert r.status_code==403

def test_analyst_can_read_but_mapping_remains_admin_owner_only():
    assert Permission.MEASUREMENT_INTEGRITY_READ in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.MEASUREMENT_MAPPING_MANAGE not in ROLE_PERMISSIONS[TenantRole.ANALYST]

def test_admin_can_map_conversion_action_to_business_truth_outcome():
    r=client(TenantRole.ADMIN).post(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/measurement-integrity/mappings',headers=HEAD,json={'conversion_action_resource':RESOURCE,'outcome_id':'qualified'})
    assert r.status_code==201
    assert r.json()['outcome_id']=='qualified'

def test_measurement_overview_exposes_claim_gates_not_fake_score():
    data=client().get(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/measurement-integrity/overview',headers=HEAD).json()
    assert data['confidence']=='constrained'
    assert data['conversion_dependent_claims_allowed'] is False
    assert data['recovery_verification_allowed'] is False
    assert 'score' not in data
