from datetime import datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
TENANT=uuid4();USER=uuid4();JOB=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='ops@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc));HEAD={'Authorization':'Bearer token'}
class Repo:
    def __init__(self,role):self.role=role
    def touch_user(self,**k):return True
    def list_memberships(self,**k):return []
    def platform_operator_role(self,**k):return self.role
    def list_internal_tenants(self,**k):return [{'tenant_id':TENANT,'slug':'acme','display_name':'Acme','first_seen_at':NOW,'account_count':1,'active_member_count':2,'active_job_count':1}]
    def internal_tenant_diagnostics(self,**k):return {'tenant':{'id':TENANT,'display_name':'Acme'},'accounts':[],'members':[],'job_counts':{},'reconciliation':[],'billing':None,'latest_sync':None,'latest_analysis':None,'semantic_releases':[],'feature_controls':[]}
    def internal_jobs(self,**k):return [{'id':JOB,'job_type':'google_ads_sync','status':'failed','attempts':1,'max_attempts':3,'requested_by':USER,'endpoint':'x','operation_key':None,'failure_code':'X','created_at':NOW,'started_at':NOW,'completed_at':NOW}]
    def internal_retry_job(self,**k):return {'source_job_id':JOB,'new_job_id':uuid4(),'job_type':'google_ads_sync','status':'queued'}
    def internal_support_cases(self,**k):return []
    def create_internal_support_case(self,**k):return {'id':uuid4(),'title':k['title'],'category':k['category'],'severity':k['severity'],'latest_event':'opened'}
    def internal_support_case_event(self,**k):return {'id':uuid4(),'case_id':k['case_id'],'event_type':k['event_type'],'payload':k['payload'],'occurred_at':NOW}
    def internal_feature_controls(self,**k):return [{'feature_key':'google_ads_mutations','enabled':True,'reason':'default enabled','occurred_at':None,'actor_user_id':None}]
    def set_internal_feature_control(self,**k):return {'feature_key':k['feature_key'],'enabled':k['enabled'],'reason':k['reason'],'occurred_at':NOW,'actor_user_id':USER}
    def internal_platform_incidents(self,**k):return []
    def create_internal_platform_incident_event(self,**k):return {'id':uuid4(),'incident_id':k['incident_id'] or uuid4(),'event_type':k['event_type'],'severity':k['severity'],'title':k['title'],'payload':k['payload'],'occurred_at':NOW,'actor_user_id':USER}
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'token':P})))


def test_non_operator_cannot_enter_internal_surface():
    assert client(None).get('/v1/internal/me',headers=HEAD).status_code==403


def test_support_viewer_reads_but_cannot_remediate():
    c=client('support_viewer')
    assert c.get('/v1/internal/tenants',headers=HEAD).status_code==200
    assert c.post(f'/v1/internal/tenants/{TENANT}/jobs/{JOB}/retry',headers=HEAD,json={'reason':'verified safe retry reason'}).status_code==403


def test_support_engineer_can_safe_retry_but_not_feature_control():
    c=client('support_engineer')
    assert c.post(f'/v1/internal/tenants/{TENANT}/jobs/{JOB}/retry',headers=HEAD,json={'reason':'verified safe retry reason'}).status_code==201
    assert c.post(f'/v1/internal/tenants/{TENANT}/feature-controls/google_ads_mutations',headers=HEAD,json={'enabled':False,'reason':'emergency provider incident'}).status_code==403


def test_platform_admin_can_change_operational_control():
    c=client('platform_admin')
    r=c.post(f'/v1/internal/tenants/{TENANT}/feature-controls/google_ads_mutations',headers=HEAD,json={'enabled':False,'reason':'emergency provider incident'})
    assert r.status_code==200 and r.json()['enabled'] is False


def test_security_auditor_is_read_only():
    c=client('security_auditor')
    assert c.get(f'/v1/internal/tenants/{TENANT}/diagnostics',headers=HEAD).status_code==200
    assert c.post('/v1/internal/incidents/events',headers=HEAD,json={'event_type':'opened','severity':'high','title':'X','payload':{}}).status_code==403
