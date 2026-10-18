from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.policy import Permission, ROLE_PERMISSIONS, TenantRole
from recovery.api.repository import Membership

TENANT=uuid4(); USER=uuid4(); ACCOUNT=uuid4(); PORTFOLIO=uuid4(); TASK=uuid4(); NOTE=uuid4(); NOW=datetime(2026,10,15,tzinfo=timezone.utc)

class Repo:
    def __init__(self, role=TenantRole.ADMIN): self.role=role
    def touch_user(self, **kwargs): return True
    def list_memberships(self, **kwargs): return [{"tenant_id":TENANT,"tenant_name":"Recovery Co","tenant_slug":"recovery-co","role":self.role.value,"status":"active"}]
    def membership(self, *, user_id, tenant_id): return Membership(TENANT,self.role,"active") if user_id==USER and tenant_id==TENANT else None
    def command_center(self, **kwargs):
        return {"tenant_id":TENANT,"tenant_name":"Recovery Co","account_count":1,"portfolio_count":1,"open_task_count":2,"unread_notification_count":1,"ready_for_approval_count":3,"current_account_count":1,"stale_account_count":0,"money_by_currency":[{"currency_code":"USD","potentially_avoidable_observed_micros":10_000_000,"verified_recovery_micros":2_000_000}],"accounts":[{"id":ACCOUNT,"customer_id":"1234567890","descriptive_name":"Roof Co","currency_code":"USD","time_zone":"America/New_York","latest_sync_at":NOW,"latest_analysis_at":NOW,"data_status":"current","potentially_avoidable_observed_micros":10_000_000,"verified_recovery_micros":2_000_000,"ready_for_approval_count":3}],"generated_at":NOW}
    def list_portfolios(self, **kwargs): return [{"id":PORTFOLIO,"name":"Home Services","description":"Core clients","account_count":1,"created_at":NOW,"updated_at":NOW}]
    def portfolio_detail(self, **kwargs): return {**self.list_portfolios()[0],"accounts":[{"id":ACCOUNT,"customer_id":"1234567890","descriptive_name":"Roof Co","currency_code":"USD","time_zone":"America/New_York","account_status":"ENABLED"}]}
    def create_portfolio(self, **kwargs): return {"id":PORTFOLIO,"name":kwargs["name"],"description":kwargs.get("description"),"account_count":0,"created_at":NOW,"updated_at":NOW}
    def add_portfolio_account(self, **kwargs): return None
    def remove_portfolio_account(self, **kwargs): return None
    def list_tasks(self, **kwargs): return [{"id":TASK,"account_id":ACCOUNT,"portfolio_id":None,"title":"Review query leak","description":None,"source_type":"manual","source_id":None,"priority":"high","status":"open","assigned_to":USER,"due_at":None,"created_by":USER,"created_at":NOW,"updated_at":NOW,"completed_at":None}]
    def create_task(self, **kwargs): return {"id":TASK,"account_id":kwargs.get("account_id"),"portfolio_id":kwargs.get("portfolio_id"),"title":kwargs["title"],"description":kwargs.get("description"),"source_type":"manual","source_id":None,"priority":kwargs["priority"],"status":"open","assigned_to":kwargs.get("assigned_to"),"due_at":kwargs.get("due_at"),"created_by":USER,"created_at":NOW,"updated_at":NOW,"completed_at":None}
    def update_task_status(self, **kwargs): return {**self.list_tasks()[0],"status":kwargs["status"],"completed_at":NOW if kwargs["status"]=="done" else None}
    def list_notifications(self, **kwargs): return [{"id":NOTE,"kind":"alert","severity":"warning","title":"Tracking stale","body":"No fresh tag data","href":"/app","source_type":"system","source_id":None,"read_at":None,"created_at":NOW}]
    def mark_notification_read(self, **kwargs): return {**self.list_notifications()[0],"read_at":NOW}
    def global_search(self, **kwargs): return [{"kind":"account","id":str(ACCOUNT),"title":"Roof Co","subtitle":"1234567890","href":f"/app/accounts/{ACCOUNT}?tenant={TENANT}&account={ACCOUNT}"}]

P=Principal(user_id=USER,subject=str(USER),email="user@example.test",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={"Authorization":"Bearer token"}

def client(role=TenantRole.ADMIN): return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({"token":P})))

def test_command_center_keeps_currency_bucket_and_money_classes_separate():
    r=client().get(f"/v1/tenants/{TENANT}/command-center",headers=HEAD)
    assert r.status_code==200
    b=r.json()["money_by_currency"][0]
    assert b["currency_code"]=="USD"
    assert b["potentially_avoidable_observed_micros"]==10_000_000
    assert b["verified_recovery_micros"]==2_000_000

def test_portfolio_and_task_permissions_are_not_visual_only():
    assert Permission.PORTFOLIO_MANAGE not in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.TASK_MANAGE in ROLE_PERMISSIONS[TenantRole.ANALYST]
    c=client(TenantRole.ANALYST)
    assert c.get(f"/v1/tenants/{TENANT}/portfolios",headers=HEAD).status_code==200
    assert c.post(f"/v1/tenants/{TENANT}/portfolios",headers=HEAD,json={"name":"X"}).status_code==403
    assert c.post(f"/v1/tenants/{TENANT}/tasks",headers=HEAD,json={"title":"Follow up","priority":"normal"}).status_code==201

def test_notifications_are_user_scoped_by_api_repository_contract():
    c=client(TenantRole.VIEWER)
    r=c.get(f"/v1/tenants/{TENANT}/notifications?unread_only=true",headers=HEAD)
    assert r.status_code==200 and r.json()[0]["title"]=="Tracking stale"
    m=c.post(f"/v1/tenants/{TENANT}/notifications/{NOTE}/read",headers=HEAD)
    assert m.status_code==200 and m.json()["read_at"] is not None

def test_global_search_requires_at_least_two_characters():
    c=client(TenantRole.VIEWER)
    assert c.get(f"/v1/tenants/{TENANT}/search?q=r",headers=HEAD).status_code==422
    r=c.get(f"/v1/tenants/{TENANT}/search?q=roof",headers=HEAD)
    assert r.status_code==200 and r.json()[0]["kind"]=="account"
