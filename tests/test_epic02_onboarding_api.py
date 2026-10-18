from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.jobs import JobReceipt, JobStatus, JobType
from recovery.api.policy import TenantRole
from recovery.api.repository import Membership

TENANT=uuid4(); USER=uuid4(); ACCOUNT=uuid4(); CONNECTION=uuid4(); DISCOVERED=uuid4(); JOB=uuid4()
NOW=datetime(2026,10,15,tzinfo=timezone.utc)

class Repo:
    def __init__(self,role=TenantRole.ADMIN): self.role=role
    def touch_user(self,**kwargs): return True
    def list_memberships(self,**kwargs): return [{"tenant_id":TENANT,"tenant_name":"Acme","tenant_slug":"acme","role":self.role.value,"status":"active"}]
    def membership(self,*,user_id,tenant_id): return Membership(TENANT,self.role,"active") if user_id==USER and tenant_id==TENANT else None
    def list_accounts(self,*,tenant_id): return []

class Onboarding:
    def create_organization(self,**kwargs): return TENANT,False
    def status(self,**kwargs): return {"current_step":"google_ads","completed_steps":["organization"],"started_at":NOW,"updated_at":NOW,"completed_at":None,"connected_google_users":0,"selected_accounts":0,"truth_snapshots":0,"measurement_profiles":0,"completed_syncs":0,"completed_analyses":0,"proposal_count":0,"account_activation":[]}
    def begin_google_oauth(self,**kwargs): return "https://accounts.google.com/o/oauth2/v2/auth?state=safe"
    def complete_google_oauth(self,**kwargs): return TENANT,CONNECTION,JobReceipt(JOB,JobType.GOOGLE_ADS_ACCOUNT_DISCOVERY,JobStatus.QUEUED),"/onboarding"
    def discovered_accounts(self,**kwargs): return [{"id":DISCOVERED,"connection_id":CONNECTION,"customer_id":"1234567890","descriptive_name":"Acme Ads","currency_code":"USD","time_zone":"America/New_York","manager":False,"account_status":"ENABLED","test_account":False,"direct_access":True,"login_customer_id":None,"hierarchy_level":0,"selected_at":None}]
    def select_accounts(self,**kwargs): return [{"id":ACCOUNT,"customer_id":"1234567890","descriptive_name":"Acme Ads","currency_code":"USD","time_zone":"America/New_York","account_status":"ENABLED","test_account":False}]
    def guided_business_truth(self,**kwargs): return uuid4(),"a"*64,1,False
    def set_measurement(self,**kwargs): return {"conversion_lag_days":14,"configured_at":NOW,"updated_at":NOW}
    def measurement(self,**kwargs): return {"conversion_lag_days":14,"configured_at":NOW,"updated_at":NOW}
    def complete(self,**kwargs): return None

P=Principal(user_id=USER,subject=str(USER),email="owner@example.test",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={"Authorization":"Bearer token"}

def client(role=TenantRole.ADMIN):
    app=create_app(repository=Repo(role),verifier=StaticTokenVerifier({"token":P}),onboarding=Onboarding())
    return TestClient(app)


def test_guided_onboarding_status_and_oauth_start_are_authorized():
    c=client()
    assert c.get(f"/v1/tenants/{TENANT}/onboarding",headers=HEAD).status_code==200
    r=c.post(f"/v1/tenants/{TENANT}/onboarding/google-ads/oauth/start",headers=HEAD,json={"return_path":"/onboarding","login_hint":"owner@example.test"})
    assert r.status_code==200 and r.json()["authorization_url"].startswith("https://accounts.google.com/")


def test_viewer_cannot_manage_google_ads_onboarding():
    c=client(TenantRole.VIEWER)
    r=c.post(f"/v1/tenants/{TENANT}/onboarding/google-ads/oauth/start",headers=HEAD,json={"return_path":"/onboarding"})
    assert r.status_code==403


def test_oauth_callback_queues_discovery_and_never_requires_customer_id():
    c=client()
    r=c.post("/v1/onboarding/google-ads/oauth/callback",headers=HEAD,json={"code":"code-1","state":"state-token-123456"})
    assert r.status_code==200
    body=r.json()
    assert body["tenant_id"]==str(TENANT)
    assert body["discovery_job"]["job_type"]=="google_ads_account_discovery"


def test_discovered_accounts_are_selected_by_discovered_customer_id():
    c=client()
    listed=c.get(f"/v1/tenants/{TENANT}/onboarding/google-ads/accounts",headers=HEAD)
    assert listed.status_code==200 and listed.json()[0]["customer_id"]=="1234567890"
    selected=c.post(f"/v1/tenants/{TENANT}/onboarding/google-ads/accounts/select",headers=HEAD,json={"customer_ids":["1234567890"]})
    assert selected.status_code==200 and selected.json()[0]["id"]==str(ACCOUNT)
