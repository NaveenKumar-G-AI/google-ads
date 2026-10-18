from datetime import datetime,timezone
from uuid import uuid4
from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.repository import Membership
from recovery.api.policy import TenantRole

TENANT=uuid4(); USER=uuid4(); ALLOWED=uuid4(); DENIED=uuid4(); NOW=datetime.now(timezone.utc)
P=Principal(user_id=USER,subject=str(USER),email="user@example.test",issuer="i",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={"Authorization":"Bearer t"}

class Repo:
    def __init__(self,role=TenantRole.OWNER,mode="all_accounts",client=False): self.role=role;self.mode=mode;self.client=client
    def touch_user(self,**k): return True
    def membership(self,**k): return Membership(TENANT,self.role,"active",self.mode,self.client,frozenset({ALLOWED}) if self.mode=="selected_accounts" else frozenset({ALLOWED,DENIED}))
    def list_memberships(self,**k): return [{"tenant_id":TENANT,"tenant_name":"Agency","tenant_slug":"agency","role":self.role.value,"status":"active","account_access_mode":self.mode,"client_portal":self.client}]
    def list_accounts(self,*,tenant_id,user_id=None):
        rows=[{"id":ALLOWED,"customer_id":"1111111111","descriptive_name":"Allowed","currency_code":"USD","time_zone":"UTC","account_status":"ENABLED","test_account":False},{"id":DENIED,"customer_id":"2222222222","descriptive_name":"Denied","currency_code":"USD","time_zone":"UTC","account_status":"ENABLED","test_account":False}]
        return rows[:1] if self.mode=="selected_accounts" else rows
    def ensure_account(self,**k): return None
    def list_organization_members(self,**k): return [{"user_id":USER,"email":"user@example.test","role":self.role.value,"status":"active","account_access_mode":self.mode,"client_portal":self.client,"created_at":NOW,"updated_at":NOW,"accessible_account_count":1,"assignments":[]}]
    def list_organization_invites(self,**k): return []
    def create_organization_invite(self,**k): return {"id":uuid4(),"email":k["email"],"role":k["role"],"account_access_mode":k["account_access_mode"],"client_portal":k["client_portal"],"expires_at":NOW,"state":"pending","created_at":NOW,"token":"secret"}
    def search_intelligence_overview(self,**k): return {"account_id":k["account_id"],"currency_code":"USD","start":None,"end":None,"visible_search_term_micros":0,"comparable_search_campaign_micros":0,"unobserved_search_micros":0,"coverage_ratio":None,"coverage_band":"unknown","query_count":0,"clicks":0,"impressions":0,"conversions":"0","cost_micros":0,"candidate_query_count":0,"potentially_avoidable_observed_micros":0,"review_required_micros":0,"financial_window_supported":False,"source_analysis_run_id":None,"source_sync_run_id":None,"latest_observation_date":None}
    def list_report_generations(self,**k): return []

def client(role=TenantRole.OWNER,mode="all_accounts",client_portal=False): return TestClient(create_app(repository=Repo(role,mode,client_portal),verifier=StaticTokenVerifier({"t":P})))

def test_analyst_cannot_enter_team_admin_surface():
    r=client(TenantRole.ANALYST).get(f"/v1/tenants/{TENANT}/organization/members",headers=HEAD)
    assert r.status_code==403

def test_owner_can_read_team_and_create_invitation():
    c=client();assert c.get(f"/v1/tenants/{TENANT}/organization/members",headers=HEAD).status_code==200
    r=c.post(f"/v1/tenants/{TENANT}/organization/invites",headers=HEAD,json={"email":"new@example.com","role":"viewer","account_access_mode":"selected_accounts","client_portal":True,"expires_days":7})
    assert r.status_code==201 and r.json()["token"]=="secret"

def test_selected_account_viewer_cannot_enumerate_portfolios_or_denied_account():
    c=client(TenantRole.VIEWER,"selected_accounts",True)
    assert c.get(f"/v1/tenants/{TENANT}/portfolios",headers=HEAD).status_code==403
    r=c.get(f"/v1/tenants/{TENANT}/accounts/{DENIED}/search-intelligence/overview",headers=HEAD)
    assert r.status_code==403

def test_selected_account_viewer_must_filter_reports_to_accessible_account():
    c=client(TenantRole.VIEWER,"selected_accounts",True)
    assert c.get(f"/v1/tenants/{TENANT}/reports",headers=HEAD).status_code==403
    assert c.get(f"/v1/tenants/{TENANT}/reports?scope_kind=account&scope_id={ALLOWED}",headers=HEAD).status_code==200

def test_me_exposes_account_access_mode_and_client_portal_to_shell():
    r=client(TenantRole.VIEWER,"selected_accounts",True).get("/v1/me",headers=HEAD)
    assert r.status_code==200
    m=r.json()["memberships"][0]
    assert m["account_access_mode"]=="selected_accounts"
    assert m["client_portal"] is True
