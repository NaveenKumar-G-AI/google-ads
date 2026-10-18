from datetime import datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership
TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();CASE=uuid4();RUN=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@example.test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc));HEAD={'Authorization':'Bearer t'}
SUMMARY={'case_id':CASE,'account_id':ACCOUNT,'account_name':'Acme','analysis_run_id':RUN,'proposal_fingerprint':'a'*64,'proposal_id':'p1','query':'jobs','match_type':'EXACT','scope':'ad_group','campaign_id':'1','ad_group_id':'2','risk':'low','disposition':'ready_for_approval','currency_code':'INR','candidate_exposure_micros':1000000,'collision_count':0,'state':'ready_for_review','stale':False,'stale_reasons':[],'execution_allowed':False,'rollback_allowed':False,'verification_status':'not_evaluated','assigned_to':None,'closed':False,'created_at':NOW}
class Repo:
    def __init__(self,role):self.role=role
    def touch_user(self,**kwargs):return True
    def list_memberships(self,**kwargs):return []
    def membership(self,*,user_id,tenant_id):return Membership(TENANT,self.role,'active') if user_id==USER and tenant_id==TENANT else None
    def list_recovery_cases(self,**kwargs):return [SUMMARY]
    def recovery_case_detail(self,**kwargs):return {**SUMMARY,'proposal':{'truth_fingerprint':'a'*64},'financial_findings':[],'decision_events':[],'mutation_events':[],'recovery_ledger':[],'case_events':[],'latest_truth_fingerprint':'a'*64,'latest_analysis_run_id':RUN,'analysis_truth_fingerprint':'a'*64}
    def append_recovery_case_event(self,**kwargs):return {'id':uuid4(),'event_type':kwargs['event_type'],'actor':kwargs['actor'],'occurred_at':NOW,'payload':{'note':kwargs.get('note')} if kwargs.get('note') else {}}
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P})))

def test_viewer_can_read_cases_but_cannot_manage_case_events():
    c=client(TenantRole.VIEWER);assert c.get(f'/v1/tenants/{TENANT}/recovery-cases?account_id={ACCOUNT}',headers=HEAD).status_code==200
    assert c.post(f'/v1/tenants/{TENANT}/recovery-cases/{CASE}/events',headers=HEAD,json={'event_type':'commented','note':'x','assigned_to':None}).status_code==403

def test_analyst_can_manage_collaboration_but_not_decide_or_execute():
    assert Permission.RECOVERY_CASE_MANAGE in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.PROPOSAL_DECIDE not in ROLE_PERMISSIONS[TenantRole.ANALYST]
    r=client(TenantRole.ANALYST).post(f'/v1/tenants/{TENANT}/recovery-cases/{CASE}/events',headers=HEAD,json={'event_type':'commented','note':'reviewed','assigned_to':None})
    assert r.status_code==201

def test_case_detail_is_available_to_read_roles():
    r=client(TenantRole.VIEWER).get(f'/v1/tenants/{TENANT}/recovery-cases/{CASE}',headers=HEAD)
    assert r.status_code==200 and r.json()['state']=='ready_for_review'
