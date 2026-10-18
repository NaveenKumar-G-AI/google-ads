from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SCHEMA="recovery-launch-evidence.v1"


def _https(value: str, label: str) -> str:
    v=value.strip().rstrip('/')
    p=urlparse(v)
    if p.scheme!="https" or not p.hostname:
        raise ValueError(f"{label} must be an HTTPS URL")
    return v


def _get(url: str, *, timeout: float = 12.0, json_expected: bool = False) -> tuple[str, bytes, Any | None]:
    req=Request(url,headers={"User-Agent":"RecoveryOS-LaunchEvidence/1","Accept":"application/json,text/html;q=0.9,*/*;q=0.1"})
    with urlopen(req,timeout=timeout) as response:
        final=response.geturl()
        if urlparse(final).scheme!="https":raise ValueError(f"{url} redirected away from HTTPS")
        if not 200<=response.status<400:raise ValueError(f"{url} returned HTTP {response.status}")
        body=response.read(1_000_000)
    parsed=None
    if json_expected:
        parsed=json.loads(body.decode('utf-8'))
        if not isinstance(parsed,dict):raise ValueError(f"{url} did not return a JSON object")
    return final,body,parsed


def _ref(url: str, body: bytes) -> str:
    return f"{url}#sha256={hashlib.sha256(body).hexdigest()}"


def _evidence(*, kind: str, status: str, operator: str, detail: str, refs: list[str], release_id: str, metadata: dict[str,Any]) -> dict[str,Any]:
    return {"schema_version":SCHEMA,"kind":kind,"status":status,"performed_at":datetime.now(timezone.utc).isoformat(),"operator":operator,"detail":detail,"evidence_refs":refs,"release_id":release_id,"metadata":metadata}


def run(*, api_url: str, dashboard_url: str, data_deletion_url: str, operator: str, release_id: str, evidence_dir: Path, timeout: float = 12.0) -> bool:
    api=_https(api_url,"api_url"); dashboard=_https(dashboard_url,"dashboard_url"); deletion=_https(data_deletion_url,"data_deletion_url")
    if not operator.strip() or not release_id.strip():raise ValueError("operator and release_id are required")
    evidence_dir.mkdir(parents=True,exist_ok=True)
    results:dict[str,dict[str,Any]]={}
    ok=True
    try:
        build_url=f"{api}/buildz"; build_final,build_body,build=_get(build_url,timeout=timeout,json_expected=True)
        status_url=f"{api}/v1/launch/status"; status_final,status_body,status=_get(status_url,timeout=timeout,json_expected=True)
        dash_final,dash_body,_=_get(dashboard,timeout=timeout)
        identity_ok=str(build.get("release_id") or "")==release_id
        tls_ok=identity_ok
        results["production_domain_tls"]=_evidence(kind="production_domain_tls",status="pass" if tls_ok else "fail",operator=operator,detail="Production API/dashboard HTTPS surfaces are reachable with trusted TLS and exact release identity." if tls_ok else "Production HTTPS surfaces were reachable but API release identity did not match.",refs=[_ref(build_final,build_body),_ref(status_final,status_body),_ref(dash_final,dash_body)],release_id=release_id,metadata={"api_release_id":build.get("release_id"),"dashboard_final_url":dash_final})
        if not tls_ok:ok=False

        terms=_https(str(status.get("terms_url") or ""),"launch status terms_url"); privacy=_https(str(status.get("privacy_url") or ""),"launch status privacy_url")
        tf,tb,_=_get(terms,timeout=timeout); pf,pb,_=_get(privacy,timeout=timeout); df,db,_=_get(deletion,timeout=timeout)
        legal_ok=bool(status.get("legal_acceptance_ready") and status.get("terms_version") and status.get("privacy_version"))
        results["legal_privacy_publication"]=_evidence(kind="legal_privacy_publication",status="pass" if legal_ok else "fail",operator=operator,detail="Published Terms, Privacy and Data Deletion pages are reachable over HTTPS and the deployed API exposes versioned legal identities." if legal_ok else "Published legal pages are reachable but deployed version identity is incomplete.",refs=[_ref(tf,tb),_ref(pf,pb),_ref(df,db),_ref(status_final,status_body)],release_id=release_id,metadata={"terms_version":status.get("terms_version"),"privacy_version":status.get("privacy_version")})
        if not legal_ok:ok=False

        limit=status.get("public_workspace_max_per_user_24h")
        abuse_ok=bool(status.get("signup_abuse_ready") and status.get("turnstile_site_key") and isinstance(limit,int) and 1<=limit<=20)
        results["public_signup_abuse_controls"]=_evidence(kind="public_signup_abuse_controls",status="pass" if abuse_ok else "fail",operator=operator,detail="Deployed API reports server-side Turnstile protection and an explicit per-user 24-hour workspace-creation limit." if abuse_ok else "Deployed public-signup abuse controls are incomplete.",refs=[_ref(status_final,status_body)],release_id=release_id,metadata={"turnstile_site_key_present":bool(status.get("turnstile_site_key")),"max_workspaces_per_user_24h":limit,"note":"The secret key is intentionally not exposed. Actual public creation still fails closed if Siteverify rejects a token."})
        if not abuse_ok:ok=False
    except Exception as exc:
        ok=False
        detail=f"public surface evidence collection failed: {type(exc).__name__}: {str(exc)[:500]}"
        for kind in ("production_domain_tls","legal_privacy_publication","public_signup_abuse_controls"):
            results.setdefault(kind,_evidence(kind=kind,status="fail",operator=operator,detail=detail,refs=[api,dashboard,deletion],release_id=release_id,metadata={}))
    for kind,payload in results.items():
        (evidence_dir/f"{kind}.json").write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    return ok


def main() -> None:
    p=argparse.ArgumentParser(description="Collect machine-verifiable Recovery OS public launch surface evidence")
    p.add_argument("--api-url",required=True);p.add_argument("--dashboard-url",required=True);p.add_argument("--data-deletion-url",required=True);p.add_argument("--operator",required=True);p.add_argument("--release-id",required=True);p.add_argument("--evidence-dir",required=True);p.add_argument("--timeout-seconds",type=float,default=12.0)
    a=p.parse_args();ok=run(api_url=a.api_url,dashboard_url=a.dashboard_url,data_deletion_url=a.data_deletion_url,operator=a.operator,release_id=a.release_id,evidence_dir=Path(a.evidence_dir),timeout=a.timeout_seconds);raise SystemExit(0 if ok else 2)
if __name__=="__main__":main()
