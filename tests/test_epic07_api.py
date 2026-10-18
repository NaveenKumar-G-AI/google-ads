from datetime import date,datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership
TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();CASE=uuid4();MUT=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@example.test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc));HEAD={'Authorization':'Bearer t'}
class Repo:
    def __init__(self,role):self.role=role
    def touch_user(self,**kwargs):return True
    def list_memberships(self,**kwargs):return []
    def membership(self,*,user_id,tenant_id):return Membership(TENANT,self.role,'active') if user_id==USER and tenant_id==TENANT else None
    def recovery_center_overview(self,**kwargs):return {'scope_kind':'account','scope_id':str(ACCOUNT),'scope_name':'Acme','account_count':1,'money_by_currency':[{'currency_code':'INR','current_observed_candidate_micros':100,'current_unobserved_search_micros':10,'acted_on_historical_candidate_micros':80,'projected_prevented_micros':70,'observed_post_action_query_spend_micros':5,'observed_difference_vs_projection_micros':65,'verified_recovery_micros':0,'ledger_action_count':1,'verified_action_count':0,'inconclusive_action_count':0,'verification_pending_action_count':1}],'case_counts':{'total':1,'verified':0,'inconclusive':0,'verification_pending':1,'rolled_back':0},'generated_at':NOW,'financial_classes_are_non_additive':True,'verified_recovery_requires_causal_evidence':True,'note':'separate'}
    def recovery_center_cases(self,**kwargs):return [{'case_id':CASE,'account_id':ACCOUNT,'account_name':'Acme','query':'roof jobs','campaign_id':'1','campaign_name':'Search','leak_family':'employment','state':'verification_pending','currency_code':'INR','historical_candidate_micros':80,'projected_prevented_micros':70,'observed_post_action_query_spend_micros':5,'observed_difference_vs_projection_micros':65,'verified_recovery_micros':0,'causal_status':'not_evaluated','ledger_created_at':NOW,'mutation_event_id':MUT,'applied_at':NOW}]
    def recovery_center_breakdown(self,**kwargs):return {'dimension':kwargs['dimension'],'rows':[],'note':'safe'}
    def recovery_center_timeline(self,**kwargs):return {'rows':[{'date':date(2026,10,16),'currency_code':'INR','ledger_updates':1,'historical_candidate_micros':80,'projected_prevented_micros':70,'observed_post_action_query_spend_micros':5,'verified_recovery_micros':0}],'note':'deduped'}
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P})))

def test_viewer_has_recovery_center_read_permission():
    assert Permission.RECOVERY_CENTER_READ in ROLE_PERMISSIONS[TenantRole.VIEWER]
    r=client(TenantRole.VIEWER).get(f'/v1/tenants/{TENANT}/recovery-center?account_id={ACCOUNT}',headers=HEAD)
    assert r.status_code==200 and r.json()['financial_classes_are_non_additive'] is True

def test_recovery_center_case_proof_is_readable_and_not_called_verified_without_causal_evidence():
    r=client(TenantRole.VIEWER).get(f'/v1/tenants/{TENANT}/recovery-center/cases?account_id={ACCOUNT}',headers=HEAD)
    assert r.status_code==200
    row=r.json()[0];assert row['verified_recovery_micros']==0 and row['causal_status']=='not_evaluated'

def test_breakdown_dimension_is_api_validated():
    c=client(TenantRole.VIEWER)
    assert c.get(f'/v1/tenants/{TENANT}/recovery-center/breakdown?dimension=campaign&account_id={ACCOUNT}',headers=HEAD).status_code==200
    assert c.get(f'/v1/tenants/{TENANT}/recovery-center/breakdown?dimension=made_up&account_id={ACCOUNT}',headers=HEAD).status_code==422
