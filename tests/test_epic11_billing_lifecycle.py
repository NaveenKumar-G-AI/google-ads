from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
import pytest
from recovery.billing import BillingPlan,BillingPlanCatalog,ProviderSubscription,ProviderInvoice,parse_provider_subscription,EntitlementState
from recovery.api.auth import Principal
from recovery.api.billing_service import BillingApplicationService,BillingRuntime
from recovery.api.policy import TenantAccess,TenantRole
from recovery.api.repository import ApiConflict

TENANT=uuid4();USER=uuid4();A1=uuid4();A2=uuid4();NOW=datetime.now(timezone.utc)
STARTER=BillingPlan('starter','Starter','plan_starter','INR',499900,120,2,90)
PRO=BillingPlan('pro','Pro','plan_pro','INR',999900,120,1,180)
CAT=BillingPlanCatalog([STARTER,PRO])

def principal(): return Principal(user_id=USER,subject=str(USER),email='owner@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=NOW+timedelta(days=3650))
def access(role=TenantRole.OWNER): return TenantAccess(TENANT,principal(),role)

def sub(plan='plan_starter',status='active',method='card',scheduled=False,intent=None):
    notes={'recovery_tenant_id':str(TENANT),'recovery_checkout_intent_id':str(intent or REPO_INTENT),'recovery_plan_key':'starter'}
    return ProviderSubscription(id='sub_test',plan_id=plan,status=status,short_url='https://rzp.io/i/test',current_start=NOW-timedelta(days=15),current_end=NOW+timedelta(days=15),quantity=1,notes=notes,customer_id='cust_test',payment_method=method,total_count=120,paid_count=4,remaining_count=116,has_scheduled_changes=scheduled,change_scheduled_at=NOW+timedelta(days=15) if scheduled else None,charge_at=NOW+timedelta(days=15),ended_at=None,raw={'id':'sub_test','plan_id':plan,'status':status,'notes':notes,'payment_method':method,'has_scheduled_changes':scheduled})

REPO_INTENT=uuid4()
class Provider:
    def __init__(self): self.plan='plan_starter';self.status='active';self.method='card';self.scheduled=False;self.pending_plan=None;self.updates=[];self.cancels=[]
    def fetch_plan(self,pid):
        p=STARTER if pid=='plan_starter' else PRO
        return {'id':pid,'item':{'amount':p.amount_subunits,'currency':p.currency}}
    def fetch_subscription(self,sid): return sub(self.plan,self.status,self.method,self.scheduled)
    def update_subscription_plan(self,*,subscription_id,plan_id,schedule_change_at): self.updates.append((subscription_id,plan_id,schedule_change_at));self.scheduled=True;self.pending_plan=plan_id;return sub(self.plan,self.status,self.method,True)
    def fetch_pending_update(self,sid): return sub(self.pending_plan or self.plan,self.status,self.method,True)
    def cancel_scheduled_update(self,sid): self.scheduled=False;self.pending_plan=None;return sub(self.plan,self.status,self.method,False)
    def cancel_subscription(self,*,subscription_id,cancel_at_cycle_end): self.cancels.append((subscription_id,cancel_at_cycle_end));return sub(self.plan,self.status,self.method,self.scheduled)
    def fetch_subscription_invoices(self,sid): return [ProviderInvoice('inv_test',sid,'pay_test','paid','INR',499900,499900,0,NOW-timedelta(days=3),NOW-timedelta(days=3),{'id':'inv_test','subscription_id':sid})]

class Repo:
    def __init__(self):
        self.current={'provider_subscription_id':'sub_test','provider_plan_id':'plan_starter','plan_key':'starter','provider_status':'active','entitlement_state':'full','current_start':NOW-timedelta(days=15),'current_end':NOW+timedelta(days=15),'grace_until':None,'has_scheduled_changes':False}
        self.checkout={'id':REPO_INTENT,'provider_subscription_id':'sub_test','plan_key':'starter'};self.ops={};self.slots=[{'account_id':A1,'customer_id':'1','descriptive_name':'One','occurred_at':NOW-timedelta(days=4)},{'account_id':A2,'customer_id':'2','descriptive_name':'Two','occurred_at':NOW-timedelta(days=3)}];self.pending=None;self.profile=None;self.invoices=[];self.history=[]
    def billing_current(self,*,tenant_id): return dict(self.current) if self.current else None
    def billing_checkout_by_provider(self,*,tenant_id,provider_subscription_id): return dict(self.checkout) if provider_subscription_id=='sub_test' else None
    def reconcile_billing_subscription(self,*,tenant_id,subscription,plan,entitlement_state,grace_until=None):
        self.current.update(provider_subscription_id=subscription.id,provider_plan_id=subscription.plan_id,plan_key=plan.key,provider_status=subscription.status,entitlement_state=entitlement_state.value,current_start=subscription.current_start,current_end=subscription.current_end,payment_method=subscription.payment_method,has_scheduled_changes=subscription.has_scheduled_changes,change_scheduled_at=subscription.change_scheduled_at,grace_until=grace_until);sid=uuid4();self.history.append({'id':sid,**self.current,'observed_at':NOW});return sid
    def list_billing_account_slots(self,*,tenant_id): return list(self.slots)
    def billing_lifecycle_operation_by_request(self,*,tenant_id,user_id,idempotency_key):
        for op in self.ops.values():
            if op['requested_by']==user_id and op['idempotency_key']==idempotency_key: return self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=op['id'])
        return None
    def latest_billing_lifecycle_operations(self,*,tenant_id,provider_subscription_id,limit=50): return [self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=x) for x in reversed(list(self.ops))]
    def prepare_billing_lifecycle_operation(self,*,tenant_id,user_id,endpoint,idempotency_key,operation_type,provider_subscription_id,target_plan_key,effective_at):
        for op in self.ops.values():
            if op['idempotency_key']==idempotency_key and op['requested_by']==user_id: return self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=op['id']),True
        oid=uuid4();self.ops[oid]={'id':oid,'tenant_id':tenant_id,'requested_by':user_id,'operation_type':operation_type,'provider_subscription_id':provider_subscription_id,'target_plan_key':target_plan_key,'idempotency_key':idempotency_key,'request_sha256':'a'*64,'effective_at':effective_at,'created_at':NOW,'events':[{'id':uuid4(),'event_type':'prepared','actor':str(user_id),'payload':{},'occurred_at':NOW}]};return self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=oid),False
    def append_billing_lifecycle_event(self,*,tenant_id,operation_id,event_type,actor,payload=None): self.ops[operation_id]['events'].append({'id':uuid4(),'event_type':event_type,'actor':actor,'payload':payload or {},'occurred_at':NOW})
    def billing_lifecycle_operation(self,*,tenant_id,operation_id):
        op={**self.ops[operation_id]};op['events']=list(op['events']);op['state']=op['events'][-1]['event_type'];return op
    def record_billing_pending_change(self,*,tenant_id,subscription_id,pending,target_plan): self.pending={'target_plan_key':target_plan.key};return uuid4()
    def latest_billing_pending_change(self,*,tenant_id,subscription_id): return self.pending
    def record_billing_invoices(self,*,tenant_id,subscription_id,invoices): self.invoices=[{'provider_invoice_id':x.id,'provider_payment_id':x.payment_id,'status':x.status,'currency':x.currency,'amount':x.amount,'amount_paid':x.amount_paid,'amount_due':x.amount_due,'issued_at':x.issued_at,'paid_at':x.paid_at,'observed_at':NOW} for x in invoices];return len(invoices)
    def list_billing_invoices(self,*,tenant_id,subscription_id,limit=100): return self.invoices[:limit]
    def save_billing_profile(self,*,tenant_id,user_id,legal_name,billing_email,tax_country,tax_region,gstin): self.profile={'id':uuid4(),'legal_name':legal_name,'billing_email':billing_email,'tax_country':tax_country,'tax_region':tax_region,'gstin':gstin,'actor_user_id':user_id,'occurred_at':NOW};return self.profile
    def billing_profile(self,*,tenant_id): return self.profile
    def billing_entitlement_history(self,*,tenant_id,limit=100): return self.history[:limit]
    def release_billing_account_slot(self,*,tenant_id,account_id,actor): self.slots=[x for x in self.slots if x['account_id']!=account_id]

def service(repo=None,provider=None,grace=0): return BillingApplicationService(repository=repo or Repo(),runtime=BillingRuntime(provider=provider or Provider(),catalog=CAT,webhook_secret='secret',grace_hours=grace))

def test_provider_parser_populates_lifecycle_fields():
    raw={'id':'sub_x','plan_id':'plan_starter','status':'active','notes':{},'customer_id':'cust_x','payment_method':'card','total_count':10,'paid_count':2,'remaining_count':8,'has_scheduled_changes':True,'change_scheduled_at':int(NOW.timestamp()),'charge_at':int(NOW.timestamp())}
    x=parse_provider_subscription(raw);assert x.payment_method=='card' and x.has_scheduled_changes is True and x.remaining_count==8 and x.change_scheduled_at is not None

def test_plan_change_preview_exposes_downgrade_slot_impact_and_card_gate():
    repo=Repo();p=Provider();preview=service(repo,p).plan_change_preview(access=access(),target_plan_key='pro')
    assert preview['schedule_change_at']=='cycle_end' and preview['automated_change_supported'] is True
    assert len(preview['accounts_over_target_limit'])==1 and preview['accounts_over_target_limit'][0]['account_id']==A2
    p.method='upi';assert service(repo,p).plan_change_preview(access=access(),target_plan_key='pro')['automated_change_supported'] is False

def test_plan_change_is_card_only_cycle_end_and_idempotent():
    repo=Repo();p=Provider();repo.slots=repo.slots[:1];svc=service(repo,p)
    first=svc.schedule_plan_change(access=access(),target_plan_key='pro',idempotency_key='pc-1',endpoint='/billing/plan-change')
    assert p.updates==[('sub_test','plan_pro','cycle_end')] and first['state']=='reconciled'
    again=svc.schedule_plan_change(access=access(),target_plan_key='pro',idempotency_key='pc-1',endpoint='/billing/plan-change')
    assert again['id']==first['id'] and len(p.updates)==1
    p2=Provider();p2.method='upi'
    with pytest.raises(ApiConflict): service(Repo(),p2).schedule_plan_change(access=access(),target_plan_key='pro',idempotency_key='pc-2',endpoint='/billing/plan-change')

def test_reconcile_allows_legitimate_provider_plan_change_without_breaking_checkout_ownership():
    repo=Repo();p=Provider();p.plan='plan_pro';result=service(repo,p).reconcile(access=access())
    assert result['plan_key']=='pro' and repo.current['plan_key']=='pro'

def test_grace_starts_once_and_does_not_roll_forward_on_every_pending_reconcile():
    repo=Repo();p=Provider();svc=service(repo,p,grace=24);p.status='pending'
    first=svc.reconcile(access=access());g=first['grace_until'];assert first['entitlement_state']==EntitlementState.GRACE.value and g is not None
    second=svc.reconcile(access=access());assert second['grace_until']==g

def test_cycle_end_cancellation_never_requests_immediate_cancel():
    repo=Repo();p=Provider();op=service(repo,p).cancel_at_cycle_end(access=access(),idempotency_key='cancel-1',endpoint='/billing/cancel')
    assert p.cancels==[('sub_test',True)] and op['state']=='reconciled'

def test_profile_validation_is_local_and_indian_gstin_is_strict():
    repo=Repo();svc=service(repo,Provider())
    saved=svc.save_profile(access=access(),legal_name='Acme Pvt Ltd',billing_email='BILLING@EXAMPLE.COM',tax_country='in',tax_region='TN',gstin='33ABCDE1234F1Z5')
    assert saved['billing_email']=='billing@example.com' and saved['tax_country']=='IN'
    with pytest.raises(ValueError): svc.save_profile(access=access(),legal_name='Acme',billing_email='x@y.com',tax_country='US',tax_region=None,gstin='33ABCDE1234F1Z5')

def test_invoice_refresh_and_slot_release_are_explicit():
    repo=Repo();svc=service(repo,Provider());r=svc.refresh_invoices(access=access());assert r['provider_count']==1 and r['new_snapshots']==1
    svc.release_account_slot(access=access(),account_id=A1);assert [x['account_id'] for x in repo.slots]==[A2]
