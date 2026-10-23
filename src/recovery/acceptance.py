from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    status: str
    detail: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    generated_at: str
    passed: bool
    checks: tuple[AcceptanceCheck, ...]
    def to_dict(self) -> dict[str, Any]:
        return {"generated_at":self.generated_at,"passed":self.passed,"checks":[asdict(x) for x in self.checks]}


def _json_request(url: str, *, method: str="GET", token: str|None=None, headers: dict[str,str]|None=None, body: dict[str,Any]|None=None, timeout: float=20.0)->tuple[int,dict[str,Any]]:
    raw=None if body is None else json.dumps(body).encode("utf-8")
    h={"Accept":"application/json",**(headers or {})}
    if raw is not None:h["Content-Type"]="application/json"
    if token:h["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(url,data=raw,headers=h,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            data=r.read(2_000_000);return r.status,json.loads(data.decode("utf-8")) if data else {}
    except urllib.error.HTTPError as exc:
        data=exc.read(1_000_000)
        try:payload=json.loads(data.decode("utf-8")) if data else {}
        except Exception:payload={"error":{"code":"HTTP_ERROR","message":f"HTTP {exc.code}"}}
        return exc.code,payload


def _http_status(url:str,*,timeout:float=20.0)->int:
    req=urllib.request.Request(url,headers={"User-Agent":"recovery-staging-accept/0.32"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status
    except urllib.error.HTTPError as exc:return exc.code


def _embedded_identity(payload: dict[str, Any]) -> dict[str, str] | None:
    """Accept only bounded public build fields, never arbitrary probe metadata."""
    fields = ("build_release_id", "build_revision", "build_source_sha256")
    if payload.get("build_identity") != "embedded":
        return None
    if any(not isinstance(payload.get(key), str) for key in fields):
        return None
    release, revision, source = (payload[key] for key in fields)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", release):
        return None
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", source):
        return None
    if release != payload.get("release_id"):
        return None
    return {key: payload[key] for key in fields}


class StagingAcceptance:
    def __init__(self,*,api_url:str,dashboard_url:str,tenant_id:UUID,bearer_token:str,expected_release_id:str|None=None,require_billing_full:bool=False,google_ads_account_id:UUID|None=None,require_google_ads_read:bool=False,require_google_test_account:bool=False,require_google_production_account:bool=False,timeout_seconds:int=120,require_build_identity:bool=False)->None:
        self.api=api_url.rstrip("/");self.dashboard=dashboard_url.rstrip("/");self.tenant_id=tenant_id;self.token=bearer_token.strip();self.expected_release_id=(expected_release_id or "").strip() or None;self.require_billing_full=require_billing_full;self.google_ads_account_id=google_ads_account_id;self.require_google_ads_read=require_google_ads_read;self.require_google_test_account=require_google_test_account;self.require_google_production_account=require_google_production_account;self.timeout_seconds=timeout_seconds;self.checks:list[AcceptanceCheck]=[]
        self.require_build_identity = require_build_identity

    def add(self,name:str,status:str,detail:str,**metadata:Any)->None:self.checks.append(AcceptanceCheck(name,status,detail,metadata))

    def _wait_job(self,job_id:str)->dict[str,Any]|None:
        deadline=time.monotonic()+self.timeout_seconds
        while time.monotonic()<deadline:
            sc,job=_json_request(f"{self.api}/v1/tenants/{self.tenant_id}/jobs/{job_id}",token=self.token)
            if sc!=200:return {"status":"api_error","http_status":sc}
            if job.get("status") in {"succeeded","failed","cancelled","needs_reconciliation"}:return job
            time.sleep(1.0)
        return None

    def run(self)->AcceptanceReport:
        try:
            code,health=_json_request(f"{self.api}/healthz");self.add("api_liveness","pass" if code==200 and health.get("status")=="ok" else "fail","API /healthz responded" if code==200 else "API /healthz failed",http_status=code)
        except Exception as exc:self.add("api_liveness","fail",f"API liveness connection failed: {type(exc).__name__}")
        release_id=None
        api_identity = None
        try:
            code,ready=_json_request(f"{self.api}/readyz");ok=code==200 and ready.get("status")=="ready";self.add("api_readiness","pass" if ok else "fail","API readiness passed" if ok else "API readiness failed",http_status=code,migrations=ready.get("migrations"))
        except Exception as exc:self.add("api_readiness","fail",f"API readiness connection failed: {type(exc).__name__}")
        try:
            code,build=_json_request(f"{self.api}/buildz");release_id=str(build.get("release_id") or "") if code==200 else None;ok=bool(release_id and release_id!="unversioned");ok=ok and (not self.expected_release_id or release_id==self.expected_release_id);self.add("api_release_identity","pass" if ok else "fail","API release identity is pinned" if ok else "API release identity is missing/mismatched",release_id=release_id,version=build.get("version"))
            api_identity = _embedded_identity(build) if code == 200 else None
        except Exception as exc:self.add("api_release_identity","fail",f"API build identity failed: {type(exc).__name__}")
        self.add(
            "api_build_identity",
            "pass" if api_identity else ("fail" if self.require_build_identity else "warn"),
            "API carries embedded source and revision identity" if api_identity else "Embedded API source/revision identity is unavailable or invalid",
            **(api_identity or {}),
        )
        try:
            sc=_http_status(self.dashboard);self.add("dashboard_http","pass" if 200<=sc<300 else "fail","dashboard is reachable" if 200<=sc<300 else "dashboard is not serving a 2xx page",http_status=sc)
        except Exception as exc:self.add("dashboard_http","fail",f"dashboard connection failed: {type(exc).__name__}")
        if not self.token:self.add("authenticated_api","fail","acceptance bearer token is required")
        else:
            code,me=_json_request(f"{self.api}/v1/me",token=self.token);member_ids={str(x.get("tenant_id")) for x in me.get("memberships") or []};ok=code==200 and str(self.tenant_id) in member_ids;self.add("authenticated_api","pass" if ok else "fail","staging user is authenticated and belongs to tenant" if ok else "staging token/tenant membership failed",http_status=code)
            idem=f"phase19-{uuid4()}";code,receipt=_json_request(f"{self.api}/v1/tenants/{self.tenant_id}/deployment-probe",method="POST",token=self.token,headers={"Idempotency-Key":idem},body={})
            if code!=202 or not receipt.get("job_id"):self.add("worker_round_trip","fail","deployment probe could not be queued",http_status=code)
            else:
                terminal=self._wait_job(str(receipt["job_id"]));result=(terminal or {}).get("result") or {};worker_release=result.get("release_id");ok=bool(terminal and terminal.get("status")=="succeeded" and result.get("probe")=="ok");ok=ok and (not release_id or worker_release==release_id);self.add("worker_round_trip","pass" if ok else "fail","API/queue/worker round trip succeeded on same release" if ok else "worker probe failed or release identity differs",job_id=receipt.get("job_id"),job_status=(terminal or {}).get("status"),worker_release_id=worker_release,api_release_id=release_id)
                worker_identity = _embedded_identity(result)
                compare_identity = self.require_build_identity or api_identity is not None or result.get("build_identity") == "embedded"
                identity_matches = bool(ok and api_identity and worker_identity == api_identity)
                self.add(
                    "worker_build_identity",
                    ("pass" if identity_matches else "fail") if compare_identity else "skip",
                    "API and worker embedded source identities match" if identity_matches else "Matching API/worker embedded source identity was not verified",
                    **(worker_identity or {}),
                )
            if self.google_ads_account_id is None:self.add("google_ads_read_probe","fail" if self.require_google_ads_read else "skip","Google Ads read probe account is required" if self.require_google_ads_read else "Google Ads read probe not requested")
            else:
                idem=f"pilot-google-read-{uuid4()}";code,receipt=_json_request(f"{self.api}/v1/tenants/{self.tenant_id}/accounts/{self.google_ads_account_id}/pilot-google-ads-read-probe",method="POST",token=self.token,headers={"Idempotency-Key":idem},body={})
                if code!=202 or not receipt.get("job_id"):self.add("google_ads_read_probe","fail","Google Ads read probe could not be queued",http_status=code)
                else:
                    terminal=self._wait_job(str(receipt["job_id"]));result=(terminal or {}).get("result") or {};ok=bool(terminal and terminal.get("status")=="succeeded" and result.get("probe")=="google_ads_read_ok" and result.get("external_effect")=="read_only");ok=ok and (not self.require_google_test_account or result.get("test_account") is True);ok=ok and (not self.require_google_production_account or result.get("test_account") is False);self.add("google_ads_read_probe","pass" if ok else "fail","deployed worker completed a read-only Google Ads customer-profile probe" if ok else "Google Ads deployed read probe failed or did not meet account-safety requirements",job_id=receipt.get("job_id"),job_status=(terminal or {}).get("status"),customer_id=result.get("customer_id"),test_account=result.get("test_account"),google_ads_api_version=result.get("google_ads_api_version"),external_effect=result.get("external_effect"))
            code,billing=_json_request(f"{self.api}/v1/tenants/{self.tenant_id}/billing",token=self.token)
            if code!=200:self.add("billing_acceptance","fail" if self.require_billing_full else "warn","billing status endpoint failed",http_status=code)
            else:
                full=billing.get("entitlement_state")=="full";self.add("billing_acceptance","pass" if full else ("fail" if self.require_billing_full else "skip"),"test subscription reconciled to full entitlement" if full else ("test subscription is not fully entitled" if self.require_billing_full else "billing full entitlement not required for this acceptance run"),entitlement_state=billing.get("entitlement_state"),provider_status=billing.get("provider_status"))
        passed=not any(x.status=="fail" for x in self.checks)
        return AcceptanceReport(datetime.now(timezone.utc).isoformat(),passed,tuple(self.checks))


def main()->None:
    p=argparse.ArgumentParser(description="Acceptance test a deployed Google Ads Recovery staging environment")
    p.add_argument("--require-build-identity", action="store_true", help="Require embedded revision/source stamps on API and worker and compare them")
    p.add_argument("--api-url",default=os.environ.get("RECOVERY_ACCEPTANCE_API_URL",""));p.add_argument("--dashboard-url",default=os.environ.get("RECOVERY_ACCEPTANCE_DASHBOARD_URL",""));p.add_argument("--tenant-id",default=os.environ.get("RECOVERY_ACCEPTANCE_TENANT_ID",""));p.add_argument("--bearer-token",default=os.environ.get("RECOVERY_ACCEPTANCE_BEARER_TOKEN",""));p.add_argument("--expected-release-id",default=os.environ.get("RECOVERY_RELEASE_ID",""));p.add_argument("--require-billing-full",action="store_true");p.add_argument("--google-ads-account-id",default=os.environ.get("RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID",""));p.add_argument("--require-google-ads-read",action="store_true");p.add_argument("--require-google-test-account",action="store_true");p.add_argument("--require-google-production-account",action="store_true");p.add_argument("--timeout-seconds",type=int,default=120);p.add_argument("--report",default="phase19-acceptance-report.json")
    a=p.parse_args()
    if not a.api_url or not a.dashboard_url or not a.tenant_id:raise SystemExit("--api-url, --dashboard-url and --tenant-id are required")
    r=StagingAcceptance(api_url=a.api_url,dashboard_url=a.dashboard_url,tenant_id=UUID(a.tenant_id),bearer_token=a.bearer_token,expected_release_id=a.expected_release_id,require_billing_full=a.require_billing_full,google_ads_account_id=UUID(a.google_ads_account_id) if a.google_ads_account_id else None,require_google_ads_read=a.require_google_ads_read,require_google_test_account=a.require_google_test_account,require_google_production_account=a.require_google_production_account,timeout_seconds=a.timeout_seconds,require_build_identity=a.require_build_identity).run()
    with open(a.report,"w",encoding="utf-8") as f:json.dump(r.to_dict(),f,indent=2,sort_keys=True)
    print(json.dumps(r.to_dict(),indent=2,sort_keys=True));raise SystemExit(0 if r.passed else 2)
if __name__=="__main__":main()
