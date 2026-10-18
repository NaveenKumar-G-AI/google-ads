from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

EVIDENCE_SCHEMA="recovery-pilot-evidence.v1"
DEPLOYED_REPORT_MAX_AGE_HOURS=24
REQUIRED_EVIDENCE_MAX_AGE_DAYS={
    "backup_configuration":30,"restore_drill":90,"access_review":30,"security_review":90,
    "observability_alerts":30,"incident_response_drill":90,"reconciliation_rollback_drill":90,"pilot_tenant_setup":30,
}

@dataclass(frozen=True,slots=True)
class PilotGateCheck:
    name:str;status:str;detail:str;metadata:dict[str,Any]

@dataclass(frozen=True,slots=True)
class PilotGateReport:
    generated_at:str;expected_release_id:str|None;qualified:bool;checks:tuple[PilotGateCheck,...]
    def to_dict(self)->dict[str,Any]:return {"generated_at":self.generated_at,"expected_release_id":self.expected_release_id,"qualified":self.qualified,"checks":[asdict(x) for x in self.checks]}

def _load_json(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise ValueError(f"{path} must contain one JSON object")
    return value

def _parse_time(value:str)->datetime:
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:raise ValueError("evidence timestamps must be timezone-aware")
    return dt.astimezone(timezone.utc)

def _sha256(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()

def _fresh_report_time(report:dict[str,Any],*,now:datetime,label:str)->tuple[bool,str,datetime|None]:
    raw=str(report.get("generated_at") or "").strip()
    if not raw:return False,f"{label} generated_at is missing",None
    try:generated=_parse_time(raw)
    except Exception as exc:return False,f"{label} generated_at is invalid: {exc}",None
    age=now-generated
    if age<timedelta(minutes=-5):return False,f"{label} generated_at is in the future",generated
    if age>timedelta(hours=DEPLOYED_REPORT_MAX_AGE_HOURS):return False,f"{label} is older than {DEPLOYED_REPORT_MAX_AGE_HOURS} hours",generated
    return True,"fresh",generated

class PilotGate:
    def __init__(self,*,readiness_report:Path,acceptance_report:Path,evidence_dir:Path,expected_release_id:str|None=None,require_billing_full:bool=True,now:datetime|None=None)->None:
        self.readiness_report=readiness_report;self.acceptance_report=acceptance_report;self.evidence_dir=evidence_dir;self.expected_release_id=(expected_release_id or "").strip() or None;self.require_billing_full=require_billing_full;self.now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc);self.checks:list[PilotGateCheck]=[]
    def add(self,name:str,status:str,detail:str,**metadata:Any)->None:self.checks.append(PilotGateCheck(name,status,detail,metadata))
    def _check_readiness(self)->None:
        try:report=_load_json(self.readiness_report)
        except Exception as exc:self.add("production_readiness","fail",f"readiness report could not be read: {type(exc).__name__}");return
        fresh,fresh_detail,generated=_fresh_report_time(report,now=self.now,label="readiness report")
        ok=report.get("ready") is True and report.get("environment") in {"staging","production"} and fresh
        failed=[x.get("name") for x in report.get("checks",[]) if x.get("status")=="fail"]
        detail="static/runtime deployment readiness report passed" if ok else (fresh_detail if not fresh else "deployment readiness report is not ready")
        self.add("production_readiness","pass" if ok else "fail",detail,environment=report.get("environment"),generated_at=generated.isoformat() if generated else None,failed_checks=failed,sha256=_sha256(self.readiness_report))
    def _check_acceptance(self)->None:
        try:report=_load_json(self.acceptance_report)
        except Exception as exc:self.add("deployed_acceptance","fail",f"acceptance report could not be read: {type(exc).__name__}");return
        checks={str(x.get("name")):x for x in report.get("checks",[]) if isinstance(x,dict)};required=["api_liveness","api_readiness","api_release_identity","dashboard_http","authenticated_api","worker_round_trip","google_ads_read_probe"]
        if self.require_billing_full:required.append("billing_acceptance")
        bad=[name for name in required if checks.get(name,{}).get("status")!="pass"]
        release=(checks.get("api_release_identity",{}).get("metadata") or {}).get("release_id");release_ok=not self.expected_release_id or release==self.expected_release_id
        fresh,fresh_detail,generated=_fresh_report_time(report,now=self.now,label="acceptance report")
        ok=report.get("passed") is True and not bad and release_ok and fresh
        detail="deployed API/dashboard/worker/provider acceptance passed" if ok else (fresh_detail if not fresh else "deployed acceptance is incomplete or mismatched")
        self.add("deployed_acceptance","pass" if ok else "fail",detail,missing_or_failed=bad,release_id=release,expected_release_id=self.expected_release_id,generated_at=generated.isoformat() if generated else None,sha256=_sha256(self.acceptance_report))
    def _check_evidence(self,kind:str,max_age_days:int)->None:
        path=self.evidence_dir/f"{kind}.json"
        if not path.is_file():self.add(kind,"fail",f"required pilot evidence is missing: {path.name}");return
        try:
            e=_load_json(path)
            if e.get("schema_version")!=EVIDENCE_SCHEMA:raise ValueError("schema_version mismatch")
            if e.get("kind")!=kind:raise ValueError("kind mismatch")
            performed=_parse_time(str(e.get("performed_at") or ""));status=str(e.get("status") or "");detail=str(e.get("detail") or "").strip();operator=str(e.get("operator") or "").strip();refs=e.get("evidence_refs") or []
            if status!="pass":raise ValueError("status must be pass")
            if not detail or not operator:raise ValueError("detail and operator are required")
            if not isinstance(refs,list) or not refs:raise ValueError("at least one evidence_ref is required")
            age=self.now-performed
            if age<timedelta(minutes=-5):raise ValueError("performed_at is in the future")
            if age>timedelta(days=max_age_days):raise ValueError(f"evidence is older than {max_age_days} days")
            rel=str(e.get("release_id") or "").strip() or None
            if rel and self.expected_release_id and rel!=self.expected_release_id:raise ValueError("release_id does not match pilot release")
        except Exception as exc:self.add(kind,"fail",f"pilot evidence is invalid: {exc}",sha256=_sha256(path));return
        self.add(kind,"pass",detail,performed_at=performed.isoformat(),operator=operator,evidence_refs=refs,release_id=rel,sha256=_sha256(path),max_age_days=max_age_days)
    def run(self)->PilotGateReport:
        self._check_readiness();self._check_acceptance()
        for kind,days in REQUIRED_EVIDENCE_MAX_AGE_DAYS.items():self._check_evidence(kind,days)
        qualified=not any(x.status=="fail" for x in self.checks)
        return PilotGateReport(self.now.isoformat(),self.expected_release_id,qualified,tuple(self.checks))

def main()->None:
    p=argparse.ArgumentParser(description="Fail-closed Recovery OS pilot launch gate");p.add_argument("--readiness-report",required=True);p.add_argument("--acceptance-report",required=True);p.add_argument("--evidence-dir",required=True);p.add_argument("--expected-release-id",default="");p.add_argument("--billing-optional",action="store_true");p.add_argument("--report",default="pilot-gate-report.json");a=p.parse_args()
    report=PilotGate(readiness_report=Path(a.readiness_report),acceptance_report=Path(a.acceptance_report),evidence_dir=Path(a.evidence_dir),expected_release_id=a.expected_release_id,require_billing_full=not a.billing_optional).run();Path(a.report).write_text(json.dumps(report.to_dict(),indent=2,sort_keys=True),encoding="utf-8");print(json.dumps(report.to_dict(),indent=2,sort_keys=True));raise SystemExit(0 if report.qualified else 2)
if __name__=="__main__":main()
