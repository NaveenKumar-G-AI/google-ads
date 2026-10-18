from datetime import datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership
from recovery.api.jobs import JobReceipt,JobType,JobStatus
TENANT=uuid4();USER=uuid4();ACCOUNT=uuid4();ALERT=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={'Authorization':'Bearer token'}
class Repo:
    def __init__(self,role): self.role=role
    def touch_user(self,**k): return True
    def list_memberships(self,**k): return [{'tenant_id':TENANT,'tenant_name':'T','role':self.role.value,'status':'active'}]
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,'active')
    def ensure_account(self,**k): return None
    def alert(self): return {'id':ALERT,'account_id':ACCOUNT,'monitor_type':'data_freshness','source_key':'account-sync','alert_fingerprint':'a'*64,'generation':1,'initial_severity':'warning','title':'Data delayed','first_evidence':{},'latest_evidence':{},'opened_at':NOW,'state':'open','severity':'warning','assigned_to':None,'last_seen_at':NOW,'occurrence_count':1}
    def monitoring_overview(self,**k): return {'account_id':ACCOUNT,'counts':{'open':1},'active_by_monitor_type':[{'monitor_type':'data_freshness','count':1}],'recent_alerts':[self.alert()],'generated_at':NOW,'note':'diagnostic'}
    def monitoring_alerts(self,**k): return [self.alert()]
    def monitoring_alert_detail(self,**k): return {**self.alert(),'events':[{'id':uuid4(),'event_type':'opened','severity':'warning','actor':'system','payload':{},'occurred_at':NOW}]}
    def monitoring_alert_event(self,**k): return {**self.monitoring_alert_detail(),'state':'acknowledged'}
    def monitoring_policies(self,**k): return [{'monitor_type':'data_freshness','enabled':True,'severity_override':None,'config':{},'scope':'organization_default','updated_at':None}]
    def monitoring_policy_event(self,**k): return {'monitor_type':k['monitor_type'],'enabled':k['enabled'],'severity_override':k['severity_override'],'config':k['config'],'scope':'account_override' if k.get('account_id') else 'organization_default','updated_at':NOW}
    def enqueue_job(self,**k): return JobReceipt(uuid4(),JobType.MONITORING_EVALUATION,JobStatus.QUEUED)
def client(role): return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'token':P})))


def test_viewer_can_read_but_not_manage_alert():
    c=client(TenantRole.VIEWER)
    assert c.get(f'/v1/tenants/{TENANT}/monitoring?account_id={ACCOUNT}',headers=HEAD).status_code==200
    assert c.post(f'/v1/tenants/{TENANT}/monitoring/alerts/{ALERT}/events',headers=HEAD,json={'event_type':'acknowledged','payload':{}}).status_code==403


def test_analyst_can_ack_and_queue_evaluation_but_not_edit_policy():
    c=client(TenantRole.ANALYST)
    assert c.post(f'/v1/tenants/{TENANT}/monitoring/alerts/{ALERT}/events',headers=HEAD,json={'event_type':'acknowledged','payload':{}}).status_code==200
    assert c.post(f'/v1/tenants/{TENANT}/accounts/{ACCOUNT}/monitoring/evaluate',headers={**HEAD,'Idempotency-Key':'abc'},json={}).status_code==202
    assert c.post(f'/v1/tenants/{TENANT}/monitoring/policies',headers=HEAD,json={'account_id':str(ACCOUNT),'monitor_type':'data_freshness','enabled':True,'config':{}}).status_code==403


def test_admin_can_manage_policy():
    c=client(TenantRole.ADMIN)
    assert c.post(f'/v1/tenants/{TENANT}/monitoring/policies',headers=HEAD,json={'account_id':str(ACCOUNT),'monitor_type':'data_freshness','enabled':False,'config':{}}).status_code==201


def test_role_contract():
    assert Permission.MONITORING_READ in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.ALERT_MANAGE in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.MONITOR_POLICY_MANAGE not in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.MONITORING_EVALUATE in ROLE_PERMISSIONS[TenantRole.ANALYST]
