from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.jobs import JobReceipt, JobStatus, JobType
from recovery.api.policy import TenantRole
from recovery.api.repository import ApiConflict, Membership


TENANT = uuid4()
ACCOUNT = uuid4()
PROPOSAL = uuid4()
USER = uuid4()


class FakeRepo:
    def __init__(self, role=TenantRole.ADMIN):
        self.role = role
        self.seen = []
        self.jobs = {}
        self.approved = False
        self.user_enabled = True
        self.truth_idem = {}
        self.operations = {}
        self.enqueued_payloads = []

    def touch_user(self, *, user_id, email):
        self.seen.append((user_id, email))
        return self.user_enabled

    def list_memberships(self, *, user_id):
        return [{"tenant_id": TENANT, "role": self.role.value, "status": "active"}]

    def membership(self, *, user_id, tenant_id):
        if user_id != USER or tenant_id != TENANT:
            return None
        return Membership(TENANT, self.role, "active")

    def list_accounts(self, *, tenant_id):
        return [{
            "id": ACCOUNT, "customer_id": "1234567890", "descriptive_name": "Test",
            "currency_code": "USD", "time_zone": "America/New_York",
            "account_status": "ENABLED", "test_account": False,
        }]


    def ensure_account(self, *, tenant_id, account_id):
        if tenant_id != TENANT or account_id != ACCOUNT:
            from recovery.api.repository import ApiNotFound
            raise ApiNotFound("Google Ads account not found")

    def enqueue_job(self, *, tenant_id, user_id, endpoint, idempotency_key, job_type, payload, operation_key=None):
        k=(tenant_id,user_id,endpoint,idempotency_key)
        if k in self.jobs:
            old_hash, receipt = self.jobs[k]
            from recovery.api.idempotency import canonical_request_sha256
            h=canonical_request_sha256(method="POST", path=endpoint, payload=payload)
            if h != old_hash:
                raise ApiConflict("Idempotency-Key was already used with a different request")
            return JobReceipt(receipt.job_id, receipt.job_type, receipt.status, True)
        from recovery.api.idempotency import canonical_request_sha256
        if operation_key is not None:
            op=(tenant_id,job_type.value,operation_key)
            if op in self.operations:
                raise ApiConflict("this logical operation already has a durable job; reuse its original idempotency key")
        self.enqueued_payloads.append(dict(payload))
        receipt=JobReceipt(uuid4(),job_type,JobStatus.QUEUED)
        if operation_key is not None:
            self.operations[(tenant_id,job_type.value,operation_key)]=receipt.job_id
        self.jobs[k]=(canonical_request_sha256(method="POST",path=endpoint,payload=payload),receipt)
        return receipt

    def save_business_truth(self, *, tenant_id, account_id, user_id, endpoint, idempotency_key, request_payload, snapshot):
        from recovery.api.idempotency import canonical_request_sha256
        k=(tenant_id,user_id,endpoint,idempotency_key)
        h=canonical_request_sha256(method="POST",path=endpoint,payload=request_payload)
        if k in self.truth_idem:
            old_h, result=self.truth_idem[k]
            if old_h != h:
                raise ApiConflict("Idempotency-Key was already used with a different request")
            return (*result[:3], True)
        result=(uuid4(),snapshot.fingerprint_sha256,snapshot.version,False)
        self.truth_idem[k]=(h,result)
        return result

    def validate_analysis_inputs(self, **kwargs):
        return None

    def validate_shadow_inputs(self, **kwargs):
        return None

    def list_findings(self, **kwargs):
        return []

    def record_proposal_decision(self, *, decision, **kwargs):
        self.approved = decision == "approved"
        return uuid4()

    def proposal_execution_payload(self, *, tenant_id, proposal_artifact_id):
        if not self.approved:
            raise ApiConflict("proposal must have an approved decision before execution")
        return {"proposal_artifact_id": str(proposal_artifact_id), "proposal_fingerprint": "a"*64, "approval_event_id": str(uuid4()), "proposal": {}}

    def proposal_rollback_payload(self, *, tenant_id, proposal_artifact_id):
        raise ApiConflict("proposal has no applied Google resource to roll back")

    def get_job(self, *, tenant_id, user_id, job_id):
        return {
            "job_id": job_id, "job_type": "google_ads_sync", "status": "queued",
            "attempts": 0, "max_attempts": 5, "result": None, "failure_code": None,
            "created_at": datetime(2026,10,15,tzinfo=timezone.utc), "started_at": None, "completed_at": None,
        }

    def list_ledger(self, **kwargs):
        return []


def principal():
    return Principal(
        user_id=USER, subject=str(USER), email="owner@example.test",
        issuer="https://x.supabase.co/auth/v1", audience="authenticated",
        role_claim="authenticated", issued_at=None,
        expires_at=datetime(2099,1,1,tzinfo=timezone.utc),
    )


def client(role=TenantRole.ADMIN):
    repo=FakeRepo(role)
    app=create_app(repository=repo,verifier=StaticTokenVerifier({"token":principal()}))
    return TestClient(app),repo

HEADERS={"Authorization":"Bearer token"}


def test_health_is_public_but_me_requires_auth():
    c,_=client()
    assert c.get("/healthz").status_code==200
    assert c.get("/v1/me").status_code==401
    r=c.get("/v1/me",headers=HEADERS)
    assert r.status_code==200
    assert r.headers["x-request-id"]
    assert r.headers["cache-control"]=="no-store"


def test_cross_tenant_path_returns_access_denied():
    c,_=client()
    other=uuid4()
    r=c.get(f"/v1/tenants/{other}/accounts",headers=HEADERS)
    assert r.status_code==403
    assert r.json()["error"]["code"]=="ACCESS_DENIED"


def test_viewer_cannot_start_sync():
    c,_=client(TenantRole.VIEWER)
    r=c.post(f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/syncs",headers={**HEADERS,"Idempotency-Key":"sync-1"},json={"start":"2026-10-01","end":"2026-10-10"})
    assert r.status_code==403


def test_sync_requires_idempotency_key_and_replays_same_request():
    c,_=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/syncs"
    body={"start":"2026-10-01","end":"2026-10-10"}
    assert c.post(url,headers=HEADERS,json=body).status_code==400
    h={**HEADERS,"Idempotency-Key":"sync-1"}
    first=c.post(url,headers=h,json=body)
    second=c.post(url,headers=h,json=body)
    assert first.status_code==202 and second.status_code==202
    assert first.json()["job_id"]==second.json()["job_id"]
    assert second.json()["idempotency_replay"] is True


def test_same_idempotency_key_with_different_request_conflicts():
    c,_=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/syncs"
    h={**HEADERS,"Idempotency-Key":"sync-1"}
    assert c.post(url,headers=h,json={"start":"2026-10-01","end":"2026-10-10"}).status_code==202
    r=c.post(url,headers=h,json={"start":"2026-10-01","end":"2026-10-11"})
    assert r.status_code==409


def test_analyst_cannot_approve_or_execute():
    c,_=client(TenantRole.ANALYST)
    r=c.post(f"/v1/tenants/{TENANT}/proposals/{PROPOSAL}/decision",headers=HEADERS,json={"decision":"approved","proposal_fingerprint":"a"*64})
    assert r.status_code==403


def test_admin_must_approve_before_execution():
    c,_=client(TenantRole.ADMIN)
    execute=f"/v1/tenants/{TENANT}/proposals/{PROPOSAL}/execute"
    h={**HEADERS,"Idempotency-Key":"exec-1"}
    assert c.post(execute,headers=h).status_code==409
    decision=c.post(f"/v1/tenants/{TENANT}/proposals/{PROPOSAL}/decision",headers=HEADERS,json={"decision":"approved","proposal_fingerprint":"a"*64})
    assert decision.status_code==200
    applied=c.post(execute,headers=h)
    assert applied.status_code==202
    assert applied.json()["job_type"]=="apply_negative"


def test_rollback_requires_an_applied_resource():
    c,repo=client(TenantRole.ADMIN)
    repo.approved=True
    url=f"/v1/tenants/{TENANT}/proposals/{PROPOSAL}/rollback"
    r=c.post(url,headers={**HEADERS,"Idempotency-Key":"rollback-1"})
    assert r.status_code==409


def test_job_status_is_tenant_authorized():
    c,_=client(TenantRole.VIEWER)
    jid=uuid4()
    r=c.get(f"/v1/tenants/{TENANT}/jobs/{jid}",headers=HEADERS)
    assert r.status_code==200
    assert r.json()["job_id"]==str(jid)


def test_disabled_authenticated_user_is_denied():
    c,repo=client()
    repo.user_enabled=False
    r=c.get("/v1/me",headers=HEADERS)
    assert r.status_code==403

def test_validation_errors_do_not_echo_full_body():
    c,_=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/syncs"
    r=c.post(url,headers={**HEADERS,"Idempotency-Key":"x"},json={"start":"not-a-date","end":"2026-10-10","secret":"do-not-echo"})
    assert r.status_code==422
    body=r.json()
    assert body["error"]["code"]=="VALIDATION_FAILED"
    assert "do-not-echo" not in str(body)


def minimal_truth_payload():
    return {
        "schema_version": 1,
        "business_id": "biz-1",
        "business_name": "Accurate Roofing",
        "version": 1,
        "supersedes_version": None,
        "created_at": "2000-01-01T00:00:00+00:00",
        "created_by": "untrusted-client",
        "offer_catalog_completeness": "complete",
        "audience_catalog_completeness": "unknown",
        "offers": [{
            "offer_id": "roof", "name": "Roof replacement", "aliases": [],
            "description": "Residential roof replacement", "commercial_model": "quote_based",
            "offer_status": "active",
            "basis": {"status":"confirmed","evidence_ids":["owner"],"confirmed_by":"owner","confirmed_at":"2026-10-15T06:00:00+00:00","note":None}
        }],
        "explicit_non_offers": [], "intent_policies": [], "audience_policies": [],
        "geo_policy": None, "outcomes": [],
        "evidence": [{"evidence_id":"owner","kind":"operator","reference":"Owner confirmation","captured_at":"2026-10-15T06:00:00+00:00","content_sha256":None}],
    }

def test_business_truth_requires_idempotency_and_replays_exact_request():
    c,_=client(TenantRole.ADMIN)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/business-truth"
    body={"payload":minimal_truth_payload()}
    assert c.post(url,headers=HEADERS,json=body).status_code==400
    h={**HEADERS,"Idempotency-Key":"truth-v1"}
    a=c.post(url,headers=h,json=body)
    b=c.post(url,headers=h,json=body)
    assert a.status_code==201 and b.status_code==201
    assert a.json()["truth_snapshot_id"]==b.json()["truth_snapshot_id"]
    assert b.json()["idempotency_replay"] is True


def test_apply_cannot_be_queued_twice_with_different_retry_keys():
    c,repo=client(TenantRole.ADMIN)
    repo.approved=True
    url=f"/v1/tenants/{TENANT}/proposals/{PROPOSAL}/execute"
    a=c.post(url,headers={**HEADERS,"Idempotency-Key":"exec-a"})
    b=c.post(url,headers={**HEADERS,"Idempotency-Key":"exec-b"})
    assert a.status_code==202
    assert b.status_code==409


def test_analysis_requires_explicit_conversion_lag_policy():
    c,_=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/analyses"
    body={"sync_run_id":str(uuid4()),"truth_snapshot_id":str(uuid4()),"as_of":"2026-10-15"}
    r=c.post(url,headers={**HEADERS,"Idempotency-Key":"analysis-no-lag"},json=body)
    assert r.status_code==422


def test_analysis_queues_exact_conversion_lag_policy():
    c,repo=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/analyses"
    body={
        "sync_run_id":str(uuid4()),"truth_snapshot_id":str(uuid4()),
        "as_of":"2026-10-15","conversion_lag_days":14,
    }
    r=c.post(url,headers={**HEADERS,"Idempotency-Key":"analysis-lag-14"},json=body)
    assert r.status_code==202
    assert repo.enqueued_payloads[-1]["conversion_lag_days"]==14


def test_analyst_can_queue_semantic_shadow_but_it_is_a_distinct_job():
    c,repo=client(TenantRole.ANALYST)
    url=f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/semantic-shadow-runs"
    body={"sync_run_id":str(uuid4()),"truth_snapshot_id":str(uuid4())}
    r=c.post(url,headers={**HEADERS,"Idempotency-Key":"shadow-1"},json=body)
    assert r.status_code==202
    assert r.json()["job_type"]=="semantic_shadow"
    assert repo.enqueued_payloads[-1]["account_id"]==str(ACCOUNT)
