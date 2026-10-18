from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.policy import TenantRole
from recovery.api.repository import Membership

TENANT=uuid4(); ACCOUNT=uuid4(); USER=uuid4(); ANALYSIS=uuid4(); SYNC=uuid4(); TRUTH=uuid4()
NOW=datetime(2026,10,15,10,0,tzinfo=timezone.utc)

class Repo:
    def touch_user(self, **kwargs): return True
    def list_memberships(self, **kwargs): return [{"tenant_id":TENANT,"role":"viewer","status":"active"}]
    def membership(self, *, user_id, tenant_id): return Membership(TENANT,TenantRole.VIEWER,"active") if tenant_id==TENANT else None
    def list_accounts(self, **kwargs): return [self.account()]
    def account(self): return {"id":ACCOUNT,"customer_id":"1234567890","descriptive_name":"Roof Co","currency_code":"USD","time_zone":"America/New_York","account_status":"ENABLED","test_account":False}
    def ensure_account(self, *, tenant_id, account_id):
        if tenant_id!=TENANT or account_id!=ACCOUNT: raise RuntimeError("unexpected")
    def workspace_summary(self, **kwargs):
        return {
            "account": self.account(),
            "latest_sync":{"id":SYNC,"status":"completed","started_at":NOW,"completed_at":NOW,"detail":{"window_start":"2026-10-01","window_end":"2026-10-07"}},
            "latest_truth":{"id":TRUTH,"status":"available","started_at":NOW,"completed_at":NOW,"detail":{"version":2,"truth_fingerprint":"a"*64}},
            "latest_analysis":{"id":ANALYSIS,"status":"completed","started_at":NOW,"completed_at":NOW,"detail":{"as_of":"2026-10-15"}},
            "currency_code":"USD","potentially_avoidable_observed_micros":31_000_000,
            "visible_search_term_micros":180_000_000,"unobserved_search_micros":20_000_000,
            "coverage_band":"high","query_count":320,"review_required_count":7,"proposal_count":12,
            "ready_for_approval_count":5,"verified_recovery_micros":4_000_000,"verified_recovery_entries":1,
            "last_updated_at":NOW,
        }
    def list_findings(self, **kwargs):
        assert kwargs["account_id"]==ACCOUNT
        return []
    def list_ledger(self, **kwargs):
        assert kwargs["account_id"]==ACCOUNT
        return []
    def list_proposals(self, **kwargs):
        assert kwargs["account_id"]==ACCOUNT
        return [{"artifact_id":uuid4(),"analysis_run_id":ANALYSIS,"artifact_fingerprint":"b"*64,"currency_code":"USD","money_micros":5_000_000,"payload":{"disposition":"ready_for_approval","risk":"low","candidate":{"text":"roof jobs","match_type":"EXACT","scope":"ad_group"}},"decision":None,"decision_event_id":None,"decided_at":None,"mutation_event_type":None,"resource_name":None,"mutation_occurred_at":None,"created_at":NOW}]
    def get_job(self, **kwargs): raise NotImplementedError

P=Principal(user_id=USER,subject=str(USER),email="viewer@example.test",issuer="https://x.supabase.co/auth/v1",audience="authenticated",role_claim="authenticated",issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))
HEAD={"Authorization":"Bearer t"}

def client(): return TestClient(create_app(repository=Repo(),verifier=StaticTokenVerifier({"t":P})))

def test_workspace_returns_backend_authoritative_money_classes():
    r=client().get(f"/v1/tenants/{TENANT}/accounts/{ACCOUNT}/workspace",headers=HEAD)
    assert r.status_code==200
    body=r.json()
    assert body["potentially_avoidable_observed_micros"]==31_000_000
    assert body["verified_recovery_micros"]==4_000_000
    assert body["unobserved_search_micros"]==20_000_000
    assert body["latest_analysis"]["id"]==str(ANALYSIS)

def test_findings_and_ledger_accept_account_scope():
    assert client().get(f"/v1/tenants/{TENANT}/findings?account_id={ACCOUNT}",headers=HEAD).status_code==200
    assert client().get(f"/v1/tenants/{TENANT}/recovery-ledger?account_id={ACCOUNT}",headers=HEAD).status_code==200


def test_proposals_are_account_scoped_and_return_event_state():
    r=client().get(f"/v1/tenants/{TENANT}/proposals?account_id={ACCOUNT}&analysis_run_id={ANALYSIS}",headers=HEAD)
    assert r.status_code==200
    body=r.json()[0]
    assert body["payload"]["candidate"]["text"]=="roof jobs"
    assert body["decision"] is None
    assert body["mutation_event_type"] is None
