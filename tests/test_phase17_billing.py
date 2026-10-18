from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from recovery.billing import (
    BillingPlan, BillingPlanCatalog, BillingProviderError, CheckoutAmbiguousError,
    EntitlementState, ProviderSubscription, entitlement_for_status, verify_razorpay_webhook,
)
from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.billing_service import BillingApplicationService, BillingRuntime
from recovery.api.policy import TenantAccess, TenantRole
from recovery.api.repository import ApiConflict, Membership

TENANT=uuid4(); USER=uuid4(); ACCOUNT=uuid4(); NOW=datetime(2026,10,15,tzinfo=timezone.utc)

PLAN=BillingPlan(
    key="starter", display_name="Starter", provider_plan_id="plan_starter",
    currency="INR", amount_subunits=499900, total_count=120,
    max_google_ads_accounts=1, max_sync_range_days=90,
)
CATALOG=BillingPlanCatalog([PLAN])


def provider_sub(status="created", *, sid="sub_test", plan_id="plan_starter", intent_id=None):
    notes={"recovery_tenant_id":str(TENANT), "recovery_plan_key":"starter"}
    if intent_id is not None: notes["recovery_checkout_intent_id"]=str(intent_id)
    raw={"id":sid,"plan_id":plan_id,"status":status,"quantity":1,"short_url":"https://rzp.io/i/test","notes":notes,
         "current_start":1792022400 if status=="active" else None,"current_end":1794700800 if status=="active" else None}
    return ProviderSubscription(id=sid,plan_id=plan_id,status=status,short_url=raw["short_url"],
        current_start=datetime.fromtimestamp(raw["current_start"],timezone.utc) if raw["current_start"] else None,
        current_end=datetime.fromtimestamp(raw["current_end"],timezone.utc) if raw["current_end"] else None,
        quantity=1,notes=notes,raw=raw)

class Provider:
    def __init__(self):
        self.created=[]; self.fetches=[]; self.status="active"; self.fail_create=None; self.intent=None
    def fetch_plan(self, plan_id):
        return {"id":plan_id,"item":{"amount":499900,"currency":"INR"}}
    def create_subscription(self, *, plan, tenant_id, checkout_intent_id):
        self.created.append((plan.key,tenant_id,checkout_intent_id)); self.intent=checkout_intent_id
        if self.fail_create: raise self.fail_create
        return provider_sub("created", intent_id=checkout_intent_id)
    def fetch_subscription(self, subscription_id):
        self.fetches.append(subscription_id)
        return provider_sub(self.status,sid=subscription_id,intent_id=self.intent)

class Repo:
    def __init__(self):
        self.current=None; self.intent=None; self.webhooks={}; self.webhook_results={}; self.slots=[]; self.snapshots=[]
        self.role=TenantRole.ADMIN; self.jobs=[]; self.seen=[]
    def touch_user(self, *, user_id,email): self.seen.append(user_id); return True
    def list_memberships(self, **kw): return [{"tenant_id":TENANT,"role":self.role.value,"status":"active"}]
    def membership(self, *, user_id, tenant_id): return Membership(TENANT,self.role,"active") if tenant_id==TENANT else None
    def list_accounts(self, **kw): return [{"id":ACCOUNT,"customer_id":"123","descriptive_name":"A","currency_code":"INR","time_zone":"Asia/Kolkata","account_status":"ENABLED","test_account":False}]
    def ensure_account(self, *, tenant_id, account_id):
        if tenant_id!=TENANT or account_id!=ACCOUNT: raise RuntimeError("not found")
    def billing_current(self, *, tenant_id): return self.current
    def billing_checkout_by_request(self, *, tenant_id,user_id,idempotency_key):
        return dict(self.intent) if self.intent and self.intent["idempotency_key"]==idempotency_key else None
    def prepare_billing_checkout(self, *, tenant_id,user_id,endpoint,idempotency_key,plan_key):
        if self.intent is not None:
            if self.intent["idempotency_key"] != idempotency_key: raise AssertionError("test only supports one key")
            return dict(self.intent), True
        self.intent={"id":uuid4(),"tenant_id":tenant_id,"requested_by":user_id,"plan_key":plan_key,"idempotency_key":idempotency_key,"state":"prepared","provider_subscription_id":None,"provider_plan_id":None,"checkout_url":None}
        return dict(self.intent), False
    def set_billing_checkout_state(self, *, tenant_id,intent_id,state,provider_subscription_id=None,provider_plan_id=None,checkout_url=None,failure_code=None):
        assert self.intent and self.intent["id"]==intent_id
        self.intent.update(state=state, provider_subscription_id=provider_subscription_id or self.intent.get("provider_subscription_id"), provider_plan_id=provider_plan_id or self.intent.get("provider_plan_id"), checkout_url=checkout_url or self.intent.get("checkout_url"), failure_code=failure_code)
    def billing_checkout_by_provider(self, *, tenant_id,provider_subscription_id):
        return dict(self.intent) if self.intent and self.intent.get("provider_subscription_id")==provider_subscription_id else None
    def latest_billing_checkout(self, *, tenant_id): return dict(self.intent) if self.intent else None
    def reconcile_billing_subscription(self, *, tenant_id,subscription,plan,entitlement_state):
        sid=uuid4(); self.snapshots.append((sid,subscription.status,entitlement_state.value))
        self.current={"provider":"razorpay","provider_subscription_id":subscription.id,"provider_plan_id":subscription.plan_id,"plan_key":plan.key,"provider_status":subscription.status,"entitlement_state":entitlement_state.value,"current_start":subscription.current_start,"current_end":subscription.current_end}
        return sid
    def claim_billing_webhook(self, *,provider_event_id,raw_body_sha256):
        if provider_event_id in self.webhooks: return self.webhooks[provider_event_id],False
        wid=uuid4(); self.webhooks[provider_event_id]=wid; return wid,True
    def billing_webhook_has_result(self, *,webhook_event_id): return webhook_event_id in self.webhook_results
    def record_billing_webhook_result(self, *,webhook_event_id,**kwargs): self.webhook_results[webhook_event_id]=kwargs
    def reserve_billing_account_slot(self, *,tenant_id,account_id,max_accounts):
        if account_id in self.slots: return
        if len(self.slots)>=max_accounts: raise ApiConflict("limit")
        self.slots.append(account_id)
    # minimal normal API methods
    def enqueue_job(self, **kwargs):
        from recovery.api.jobs import JobReceipt,JobStatus
        self.jobs.append(kwargs)
        return JobReceipt(uuid4(),kwargs["job_type"],JobStatus.QUEUED)
    def validate_analysis_inputs(self, **kwargs): pass
    def validate_shadow_inputs(self, **kwargs): pass
    def save_business_truth(self, **kwargs): return uuid4(),"a"*64,1,False
    def list_findings(self, **kwargs): return []
    def list_ledger(self, **kwargs): return []
    def record_proposal_decision(self, **kwargs): return uuid4()
    def proposal_execution_payload(self, **kwargs): return {"proposal_artifact_id":str(uuid4()),"proposal_fingerprint":"a"*64,"approval_event_id":str(uuid4()),"proposal":{}}
    def proposal_rollback_payload(self, **kwargs): return {"proposal_artifact_id":str(uuid4()),"resource_name":"customers/1/adGroupCriteria/2~3"}
    def get_job(self, **kwargs): raise NotImplementedError


def principal():
    return Principal(user_id=USER,subject=str(USER),email="owner@test",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))


def runtime(provider): return BillingRuntime(provider=provider,catalog=CATALOG,webhook_secret="whsec")

def access(repo): return TenantAccess(TENANT,principal(),repo.role)


def test_status_mapping_is_fail_closed():
    assert entitlement_for_status("active") is EntitlementState.FULL
    assert entitlement_for_status("pending") is EntitlementState.BILLING_PENDING
    assert entitlement_for_status("halted") is EntitlementState.READ_ONLY
    assert entitlement_for_status("weird_new_state") is EntitlementState.BLOCKED


def test_webhook_signature_uses_exact_raw_body():
    raw=b'{"event":"subscription.activated"}'
    sig=hmac.new(b"secret",raw,hashlib.sha256).hexdigest()
    verify_razorpay_webhook(raw_body=raw,signature=sig,secret="secret")
    with pytest.raises(Exception): verify_razorpay_webhook(raw_body=raw+b" ",signature=sig,secret="secret")


def test_checkout_is_idempotent_and_does_not_create_provider_twice():
    repo=Repo(); provider=Provider(); svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    first=svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    second=svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    assert first["provider_subscription_id"]=="sub_test"
    assert second["idempotency_replay"] is True
    assert len(provider.created)==1


def test_ambiguous_create_is_not_blindly_replayed():
    repo=Repo(); provider=Provider(); provider.fail_create=CheckoutAmbiguousError("timeout")
    svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    with pytest.raises(CheckoutAmbiguousError): svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    provider.fail_create=None
    with pytest.raises(ApiConflict): svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    assert len(provider.created)==1


def test_checkout_blocks_if_configured_price_does_not_match_provider_plan():
    repo=Repo(); provider=Provider(); provider.fetch_plan=lambda _:{"item":{"amount":1,"currency":"INR"}}
    svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    with pytest.raises(ApiConflict): svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    assert provider.created==[]


def test_reconcile_fetches_provider_state_and_only_active_unlocks():
    repo=Repo(); provider=Provider(); svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    provider.status="pending"; pending=svc.reconcile(access=access(repo)); assert pending["entitlement_state"]=="billing_pending"
    provider.status="active"; active=svc.reconcile(access=access(repo)); assert active["entitlement_state"]=="full"


def test_webhook_does_not_trust_payload_status_and_refetches_current_provider_state():
    repo=Repo(); provider=Provider(); svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    provider.status="active"
    body={"event":"subscription.halted","payload":{"subscription":{"entity":{"id":"sub_test","status":"halted","notes":{"recovery_tenant_id":str(TENANT)}}}}}
    raw=json.dumps(body,separators=(",",":")).encode(); sig=hmac.new(b"whsec",raw,hashlib.sha256).hexdigest()
    result=svc.handle_webhook(raw_body=raw,signature=sig,provider_event_id_header="evt-1")
    assert result["entitlement_state"]=="full"
    assert repo.current["provider_status"]=="active"
    assert provider.fetches==["sub_test"]


def test_duplicate_webhook_is_processed_once_after_result_exists():
    repo=Repo(); provider=Provider(); svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    svc.start_checkout(access=access(repo),plan_key="starter",idempotency_key="bill-1",endpoint="/billing/checkout")
    body={"event":"subscription.activated","payload":{"subscription":{"entity":{"id":"sub_test","notes":{"recovery_tenant_id":str(TENANT)}}}}}
    raw=json.dumps(body,separators=(",",":")).encode(); sig=hmac.new(b"whsec",raw,hashlib.sha256).hexdigest()
    a=svc.handle_webhook(raw_body=raw,signature=sig,provider_event_id_header="evt-1")
    b=svc.handle_webhook(raw_body=raw,signature=sig,provider_event_id_header="evt-1")
    assert a["status"]=="reconciled" and b=={"duplicate":True,"status":"already_processed"}
    assert len(provider.fetches)==1


def test_inactive_billing_blocks_new_sync_but_read_and_rollback_policy_remain_separate():
    repo=Repo(); provider=Provider()
    app=create_app(repository=repo,verifier=StaticTokenVerifier({"t":principal()}),billing_runtime=runtime(provider))
    client=TestClient(app); head={"Authorization":"Bearer t","Idempotency-Key":"sync-1"}
    r=client.post(f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/syncs",headers=head,json={"start":"2026-10-01","end":"2026-10-07"})
    assert r.status_code==402 and r.json()["error"]["code"]=="BILLING_REQUIRED"
    # reads remain available
    assert client.get(f"/v1/tenants/{TENANT}/accounts",headers={"Authorization":"Bearer t"}).status_code==200


def test_active_plan_enforces_sync_window_and_account_limit():
    repo=Repo(); provider=Provider(); svc=BillingApplicationService(repository=repo,runtime=runtime(provider))
    repo.current={"plan_key":"starter","entitlement_state":"full"}
    with pytest.raises(Exception): svc.require_full(access=access(repo),capability="sync",account_id=ACCOUNT,sync_start=date(2026,1,1),sync_end=date(2026,5,1))
    svc.require_full(access=access(repo),capability="sync",account_id=ACCOUNT,sync_start=date(2026,10,1),sync_end=date(2026,10,7),reserve_account=True)
    assert repo.slots==[ACCOUNT]


def test_owner_can_start_checkout_api_but_viewer_cannot():
    repo=Repo(); provider=Provider(); app=create_app(repository=repo,verifier=StaticTokenVerifier({"t":principal()}),billing_runtime=runtime(provider)); c=TestClient(app)
    url=f"/v1/tenants/{TENANT}/billing/checkout"
    r=c.post(url,headers={"Authorization":"Bearer t","Idempotency-Key":"bill-1"},json={"plan_key":"starter"})
    assert r.status_code==201 and r.json()["checkout_url"]=="https://rzp.io/i/test"
    repo2=Repo(); repo2.role=TenantRole.VIEWER
    c2=TestClient(create_app(repository=repo2,verifier=StaticTokenVerifier({"t":principal()}),billing_runtime=runtime(Provider())))
    assert c2.post(url,headers={"Authorization":"Bearer t","Idempotency-Key":"bill-1"},json={"plan_key":"starter"}).status_code==403


def test_invalid_webhook_signature_is_rejected_before_provider_fetch():
    repo=Repo(); provider=Provider(); app=create_app(repository=repo,verifier=StaticTokenVerifier({"t":principal()}),billing_runtime=runtime(provider)); c=TestClient(app)
    raw=b'{"event":"subscription.activated"}'
    r=c.post("/v1/billing/webhooks/razorpay",content=raw,headers={"X-Razorpay-Signature":"bad"})
    assert r.status_code==401
    assert provider.fetches==[]


def test_rollback_remains_available_when_subscription_is_inactive():
    repo=Repo(); provider=Provider(); repo.current={"plan_key":"starter","entitlement_state":"read_only","provider_subscription_id":"sub_old"}
    app=create_app(repository=repo,verifier=StaticTokenVerifier({"t":principal()}),billing_runtime=runtime(provider)); c=TestClient(app)
    proposal=uuid4()
    r=c.post(f"/v1/tenants/{TENANT}/proposals/{proposal}/rollback",headers={"Authorization":"Bearer t","Idempotency-Key":"rb-1"})
    assert r.status_code==202
    assert r.json()["job_type"]=="rollback_negative"
