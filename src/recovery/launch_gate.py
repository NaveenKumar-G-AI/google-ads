from __future__ import annotations

import argparse
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
from typing import Any

LAUNCH_GATE_SCHEMA="recovery-launch-gate.v1"
LAUNCH_EVIDENCE_SCHEMA="recovery-launch-evidence.v1"
DEPLOYED_MAX_AGE_HOURS=24
PILOT_GATE_MAX_AGE_DAYS=7
REQUIRED_EVIDENCE_MAX_AGE_DAYS={
    "google_ads_production_access":30,
    "google_oauth_verification":90,
    "razorpay_live_activation":30,
    "razorpay_live_webhook":30,
    "production_domain_tls":30,
    "legal_privacy_publication":90,
    "data_deletion_process":90,
    "support_oncall":30,
    "production_observability":30,
    "production_security_access_review":30,
    "production_backup_restore":90,
    "release_rollback_rehearsal":90,
    "public_signup_abuse_controls":30,
}

@dataclass(frozen=True,slots=True)
class LaunchGateCheck:
    name:str;status:str;detail:str;metadata:dict[str,Any]

@dataclass(frozen=True,slots=True)
class LaunchGateReport:
    schema_version:str;generated_at:str;expected_release_id:str;qualified:bool;checks:tuple[LaunchGateCheck,...]
    def to_dict(self)->dict[str,Any]:return {"schema_version":self.schema_version,"generated_at":self.generated_at,"expected_release_id":self.expected_release_id,"qualified":self.qualified,"checks":[asdict(x) for x in self.checks]}

def _load(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise ValueError(f"{path} must contain one JSON object")
    return value

def _time(raw:Any)->datetime:
    dt=datetime.fromisoformat(str(raw or "").replace("Z","+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)

def _sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()

def _fresh(raw:Any,*,now:datetime,max_age:timedelta,label:str)->tuple[bool,str,datetime|None]:
    try:dt=_time(raw)
    except Exception as exc:return False,f"{label} generated_at is invalid: {exc}",None
    age=now-dt
    if age<timedelta(minutes=-5):return False,f"{label} is future-dated",dt
    if age>max_age:return False,f"{label} is stale",dt
    return True,"fresh",dt

def validate_launch_gate_report(payload:dict[str,Any],*,now:datetime|None=None,expected_release_id:str|None=None,max_age_hours:int=24)->None:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if payload.get("schema_version")!=LAUNCH_GATE_SCHEMA:raise ValueError("launch gate schema_version mismatch")
    if payload.get("qualified") is not True:raise ValueError("launch gate report is not qualified")
    release=str(payload.get("expected_release_id") or "").strip()
    if not release:raise ValueError("launch gate expected_release_id is required")
    if expected_release_id and release!=expected_release_id:raise ValueError("launch gate release_id mismatch")
    ok,detail,_=_fresh(payload.get("generated_at"),now=now,max_age=timedelta(hours=max_age_hours),label="launch gate report")
    if not ok:raise ValueError(detail)
    checks=payload.get("checks")
    if not isinstance(checks,list) or not checks:raise ValueError("launch gate checks are required")
    if any(not isinstance(x,dict) or x.get("status")!="pass" for x in checks):raise ValueError("launch gate report contains non-pass checks")

class LaunchGate:
    def __init__(self,*,pilot_gate_report:Path,readiness_report:Path,acceptance_report:Path,evidence_dir:Path,expected_release_id:str,now:datetime|None=None)->None:
        if not expected_release_id.strip():raise ValueError("expected_release_id is required")
        self.pilot=pilot_gate_report;self.readiness=readiness_report;self.acceptance=acceptance_report;self.dir=evidence_dir;self.release=expected_release_id.strip();self.now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);self.checks:list[LaunchGateCheck]=[]
    def add(self,name:str,status:str,detail:str,**meta:Any)->None:self.checks.append(LaunchGateCheck(name,status,detail,meta))
    def _pilot(self)->None:
        try:p=_load(self.pilot);ok,fresh,dt=None,None,None
        except Exception as exc:self.add("pilot_qualification","fail",f"pilot gate could not be read: {type(exc).__name__}");return
        valid,detail,dt=_fresh(p.get("generated_at"),now=self.now,max_age=timedelta(days=PILOT_GATE_MAX_AGE_DAYS),label="pilot gate")
        pilot_release=str(p.get("expected_release_id") or "").strip()
        release_ok=pilot_release==self.release
        passed=p.get("qualified") is True and valid and release_ok
        if passed: reason="pilot hardening gate is qualified, recent, and matches the launch release"
        elif not valid: reason=detail
        elif not release_ok: reason="pilot gate release does not match the V1 launch release"
        else: reason="pilot gate is not qualified"
        self.add("pilot_qualification","pass" if passed else "fail",reason,generated_at=dt.isoformat() if dt else None,pilot_release_id=pilot_release or None,expected_release_id=self.release,sha256=_sha(self.pilot))
    def _readiness(self)->None:
        try:r=_load(self.readiness)
        except Exception as exc:self.add("production_readiness","fail",f"production readiness could not be read: {type(exc).__name__}");return
        fresh,detail,dt=_fresh(r.get("generated_at"),now=self.now,max_age=timedelta(hours=DEPLOYED_MAX_AGE_HOURS),label="production readiness")
        bad=[x.get("name") for x in r.get("checks",[]) if isinstance(x,dict) and x.get("status")=="fail"]
        passed=r.get("ready") is True and r.get("environment")=="production" and fresh and not bad
        self.add("production_readiness","pass" if passed else "fail","production readiness is fresh and passing" if passed else detail if not fresh else "production readiness is incomplete",failed_checks=bad,generated_at=dt.isoformat() if dt else None,sha256=_sha(self.readiness))
    def _acceptance(self)->None:
        try:r=_load(self.acceptance)
        except Exception as exc:self.add("production_acceptance","fail",f"production acceptance could not be read: {type(exc).__name__}");return
        fresh,detail,dt=_fresh(r.get("generated_at"),now=self.now,max_age=timedelta(hours=DEPLOYED_MAX_AGE_HOURS),label="production acceptance")
        checks={str(x.get("name")):x for x in r.get("checks",[]) if isinstance(x,dict)}
        required=["api_liveness","api_readiness","api_release_identity","dashboard_http","authenticated_api","worker_round_trip","google_ads_read_probe","billing_acceptance"]
        bad=[n for n in required if checks.get(n,{}).get("status")!="pass"]
        identity=(checks.get("api_release_identity",{}).get("metadata") or {}).get("release_id")
        google_meta=checks.get("google_ads_read_probe",{}).get("metadata") or {}
        prod_google=google_meta.get("test_account") is False and google_meta.get("external_effect")=="read_only"
        passed=r.get("passed") is True and fresh and not bad and identity==self.release and prod_google
        reason="production acceptance passed on exact release and production Google account" if passed else detail if not fresh else "production acceptance is incomplete, mismatched, or used a test Google Ads account"
        self.add("production_acceptance","pass" if passed else "fail",reason,missing_or_failed=bad,release_id=identity,expected_release_id=self.release,google_test_account=google_meta.get("test_account"),generated_at=dt.isoformat() if dt else None,sha256=_sha(self.acceptance))
    def _evidence(self,kind:str,days:int)->None:
        path=self.dir/f"{kind}.json"
        if not path.is_file():self.add(kind,"fail",f"required launch evidence is missing: {path.name}");return
        try:
            e=_load(path)
            if e.get("schema_version")!=LAUNCH_EVIDENCE_SCHEMA:raise ValueError("schema_version mismatch")
            if e.get("kind")!=kind:raise ValueError("kind mismatch")
            if e.get("status")!="pass":raise ValueError("status must be pass")
            performed=_time(e.get("performed_at"));detail=str(e.get("detail") or "").strip();operator=str(e.get("operator") or "").strip();refs=e.get("evidence_refs") or []
            if not detail or not operator:raise ValueError("detail and operator are required")
            if not isinstance(refs,list) or not refs:raise ValueError("at least one evidence_ref is required")
            age=self.now-performed
            if age<timedelta(minutes=-5):raise ValueError("performed_at is future-dated")
            if age>timedelta(days=days):raise ValueError(f"evidence is older than {days} days")
            rel=str(e.get("release_id") or "").strip() or None
            if rel and rel!=self.release:raise ValueError("release_id does not match launch release")
        except Exception as exc:self.add(kind,"fail",f"launch evidence is invalid: {exc}",sha256=_sha(path));return
        self.add(kind,"pass",detail,performed_at=performed.isoformat(),operator=operator,evidence_refs=refs,release_id=rel,sha256=_sha(path),max_age_days=days)
    def run(self)->LaunchGateReport:
        self._pilot();self._readiness();self._acceptance()
        for kind,days in REQUIRED_EVIDENCE_MAX_AGE_DAYS.items():self._evidence(kind,days)
        qualified=not any(x.status=="fail" for x in self.checks)
        return LaunchGateReport(LAUNCH_GATE_SCHEMA,self.now.isoformat(),self.release,qualified,tuple(self.checks))

def main()->None:
    p=argparse.ArgumentParser(description="Fail-closed Recovery OS V1 public-launch gate")
    p.add_argument("--pilot-gate-report",required=True);p.add_argument("--readiness-report",required=True);p.add_argument("--acceptance-report",required=True);p.add_argument("--evidence-dir",required=True);p.add_argument("--expected-release-id",required=True);p.add_argument("--report",default="launch-gate-report.json")
    a=p.parse_args();report=LaunchGate(pilot_gate_report=Path(a.pilot_gate_report),readiness_report=Path(a.readiness_report),acceptance_report=Path(a.acceptance_report),evidence_dir=Path(a.evidence_dir),expected_release_id=a.expected_release_id).run();Path(a.report).write_text(json.dumps(report.to_dict(),indent=2,sort_keys=True),encoding="utf-8");print(json.dumps(report.to_dict(),indent=2,sort_keys=True));raise SystemExit(0 if report.qualified else 2)
if __name__=="__main__":main()
