from datetime import datetime,timedelta,timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from recovery.billing import BillingPlan,BillingPlanCatalog,ProviderSubscription
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.billing_service import BillingRuntime
from recovery.api.policy import Permission,ROLE_PERMISSIONS,TenantRole
from recovery.api.repository import Membership
TENANT=uuid4();USER=uuid4();NOW=datetime.now(timezone.utc);INTENT=uuid4()
PLAN=BillingPlan('starter','Starter','plan_starter','INR',499900,120,2,90);PRO=BillingPlan('pro','Pro','plan_pro','INR',999900,120,5,180);CAT=BillingPlanCatalog([PLAN,PRO])
P=Principal(user_id=USER,subject=str(USER),email='owner@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=NOW+timedelta(days=3650));HEAD={'Authorization':'Bearer t'}
class Provider:
    def fetch_plan(self,pid):
        p=PLAN if pid=='plan_starter' else PRO;return {'item':{'amount':p.amount_subunits,'currency':p.currency}}
    def fetch_subscription(self,sid): return ProviderSubscription('sub_test','plan_starter','active',None,NOW-timedelta(days=15),NOW+timedelta(days=15),1,{'recovery_tenant_id':str(TENANT),'recovery_checkout_intent_id':str(INTENT)},payment_method='card')
class Repo:
    def __init__(self,role):self.role=role
    def touch_user(self,**k):return True
    def list_memberships(self,**k):return [{'tenant_id':TENANT,'tenant_name':'T','role':self.role.value,'status':'active'}]
    def membership(self,*,user_id,tenant_id):return Membership(TENANT,self.role,'active')
    def billing_current(self,*,tenant_id):return {'provider_subscription_id':'sub_test','provider_plan_id':'plan_starter','plan_key':'starter','provider_status':'active','entitlement_state':'full','current_start':NOW-timedelta(days=15),'current_end':NOW+timedelta(days=15),'payment_method':'card','grace_until':None,'has_scheduled_changes':False}
    def billing_profile(self,*,tenant_id):return None
    def list_billing_account_slots(self,*,tenant_id):return []
    def latest_billing_lifecycle_operations(self,**k):return []
    def billing_checkout_by_provider(self,**k):return {'id':INTENT,'plan_key':'starter','provider_subscription_id':'sub_test'}
    def list_billing_invoices(self,**k):return []
    def billing_entitlement_history(self,**k):return []
def client(role):return TestClient(create_app(repository=Repo(role),verifier=StaticTokenVerifier({'t':P}),billing_runtime=BillingRuntime(provider=Provider(),catalog=CAT,webhook_secret='whsec')))

def test_only_admin_owner_can_read_billing_lifecycle():
    assert client(TenantRole.VIEWER).get(f'/v1/tenants/{TENANT}/billing',headers=HEAD).status_code==403
    assert client(TenantRole.ANALYST).get(f'/v1/tenants/{TENANT}/billing',headers=HEAD).status_code==403
    r=client(TenantRole.ADMIN).get(f'/v1/tenants/{TENANT}/billing',headers=HEAD);assert r.status_code==200 and r.json()['plan_key']=='starter'

def test_admin_can_preview_cycle_end_plan_change_but_analyst_cannot():
    body={'target_plan_key':'pro'}
    r=client(TenantRole.ADMIN).post(f'/v1/tenants/{TENANT}/billing/plan-change/preview',headers=HEAD,json=body);assert r.status_code==200 and r.json()['schedule_change_at']=='cycle_end'
    assert client(TenantRole.ANALYST).post(f'/v1/tenants/{TENANT}/billing/plan-change/preview',headers=HEAD,json=body).status_code==403

def test_billing_permissions_are_not_in_viewer_or_analyst_roles():
    for role in (TenantRole.VIEWER,TenantRole.ANALYST):
        assert Permission.BILLING_READ not in ROLE_PERMISSIONS[role]
        assert Permission.BILLING_MANAGE not in ROLE_PERMISSIONS[role]
    assert Permission.BILLING_READ in ROLE_PERMISSIONS[TenantRole.ADMIN]
    assert Permission.BILLING_MANAGE in ROLE_PERMISSIONS[TenantRole.OWNER]
