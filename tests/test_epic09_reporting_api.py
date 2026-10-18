from datetime import date,datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.policy import TenantRole,Permission,ROLE_PERMISSIONS
from recovery.api.repository import Membership
from recovery.api.jobs import JobReceipt,JobType,JobStatus
TENANT=uuid4();USER=uuid4();GEN=uuid4();SHARE=uuid4();SCHED=uuid4();NOW=datetime(2026,10,16,tzinfo=timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email='u@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc));HEAD={'Authorization':'Bearer token'}
class Repo:
    def __init__(self,role): self.role=role
    def touch_user(self,**k): return True
    def list_memberships(self,**k): return [{'tenant_id':TENANT,'tenant_name':'T','role':self.role.value,'status':'active'}]
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,'active')
    def list_report_generations(self,**k): return [{'id':GEN,'report_type':'executive_recovery','template_version':'v','schema_version':'recovery-report.v1','scope_kind':'organization','scope_id':str(TENANT),'period_start':None,'period_end':None,'generated_by':USER,'source_job_id':None,'schedule_id':None,'snapshot_sha256':'a'*64,'generated_at':NOW,'artifacts':[{'format':'pdf','byte_size':12,'sha256':'b'*64}]}]
    def report_generation(self,**k): return {**self.list_report_generations()[0],'snapshot':{'schema_version':'recovery-report.v1'},'deliveries':[]}
    def report_artifact(self,**k): return {'content':b'%PDF-x','content_type':'application/pdf','byte_size':6,'artifact_sha256':'b'*64,'report_type':'executive_recovery','generated_at':NOW}
    def create_report_share(self,**k): return {'id':SHARE,'generation_id':GEN,'token':f'{TENANT}.secretsecretsecretsecretsecretsecretsecret','expires_at':NOW,'state':'active','created_at':NOW}
    def revoke_report_share(self,**k): return {'id':SHARE,'generation_id':GEN,'expires_at':NOW,'state':'revoked','created_at':NOW}
    def list_report_shares(self,**k): return []
    def list_report_schedules(self,**k): return []
    def record_report_schedule(self,**k): return {'id':uuid4(),'schedule_id':SCHED,'report_type':k['report_type'],'scope_kind':k['scope_kind'],'scope_id':k['scope_id'],'frequency':k['frequency'],'timezone_name':k['timezone_name'],'hour':k['hour'],'minute':k['minute'],'weekday':k['weekday'],'day_of_month':k['day_of_month'],'recipients':k['recipients'],'enabled':k['enabled'],'actor_user_id':USER,'occurred_at':NOW}
    def public_report(self,**k): return {'share':{'expires_at':NOW},'generation':{'id':str(GEN),'report_type':'executive_recovery','snapshot_sha256':'a'*64,'generated_at':NOW,'snapshot':{},'artifacts':[]}}
    def public_report_artifact(self,**k): return self.report_artifact()
    def enqueue_job(self,**k): return JobReceipt(uuid4(),JobType.REPORT_GENERATION,JobStatus.QUEUED)
    def ensure_account(self,**k): return None
    def portfolio_detail(self,**k): return {'id':uuid4(),'name':'P','description':None,'account_count':0,'created_at':NOW,'updated_at':NOW,'accounts':[]}
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'token':P})))


def test_viewer_reads_existing_reports_but_cannot_generate_or_share():
    c=client(TenantRole.VIEWER)
    assert c.get(f'/v1/tenants/{TENANT}/reports',headers=HEAD).status_code==200
    body={'report_type':'executive_recovery','scope_kind':'organization','scope_id':str(TENANT)}
    assert c.post(f'/v1/tenants/{TENANT}/reports/generate',headers={**HEAD,'Idempotency-Key':'x'},json=body).status_code==403
    assert c.post(f'/v1/tenants/{TENANT}/reports/{GEN}/shares',headers=HEAD,json={'expires_days':14}).status_code==403


def test_analyst_can_generate_share_and_schedule():
    c=client(TenantRole.ANALYST);body={'report_type':'executive_recovery','scope_kind':'organization','scope_id':str(TENANT)}
    assert c.post(f'/v1/tenants/{TENANT}/reports/generate',headers={**HEAD,'Idempotency-Key':'x'},json=body).status_code==202
    r=c.post(f'/v1/tenants/{TENANT}/reports/{GEN}/shares',headers=HEAD,json={'expires_days':14});assert r.status_code==201 and r.json()['token']
    sched={**body,'frequency':'weekly','timezone_name':'Asia/Kolkata','hour':8,'minute':0,'weekday':0,'day_of_month':1,'recipients':['client@example.com'],'enabled':True}
    assert c.post(f'/v1/tenants/{TENANT}/report-schedules',headers=HEAD,json=sched).status_code==201


def test_public_share_endpoint_does_not_require_bearer_auth():
    token=f'{TENANT}.secretsecretsecretsecretsecretsecretsecret'
    assert client(TenantRole.VIEWER).get(f'/v1/public/report-shares/{token}').status_code==200


def test_reporting_role_contract():
    assert Permission.REPORTING_READ in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.REPORT_GENERATE not in ROLE_PERMISSIONS[TenantRole.VIEWER]
    assert Permission.REPORT_GENERATE in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.REPORT_SHARE_MANAGE in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.REPORT_SCHEDULE_MANAGE in ROLE_PERMISSIONS[TenantRole.ANALYST]
