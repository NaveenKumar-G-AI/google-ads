from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import socket
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi.testclient import TestClient

from recovery.acceptance import StagingAcceptance
from recovery.api.app import create_app
from recovery.api.auth import Principal,StaticTokenVerifier
from recovery.api.jobs import JobReceipt,JobStatus,JobType
from recovery.api.policy import Permission,ROLE_PERMISSIONS,TenantRole
from recovery.api.repository import Membership
from recovery.pilot_gate import EVIDENCE_SCHEMA,PilotGate,REQUIRED_EVIDENCE_MAX_AGE_DAYS
from recovery.worker.health import WorkerHealthServer,WorkerHealthState
from recovery.worker.pilot_probe import GoogleAdsPilotReadProbeJobRunner

ROOT=Path(__file__).resolve().parents[1]


def test_pilot_google_probe_job_and_permission_are_admin_owner_only():
    assert JobType.PILOT_GOOGLE_ADS_READ_PROBE.value=='pilot_google_ads_read_probe'
    assert Permission.PILOT_PROBE in ROLE_PERMISSIONS[TenantRole.ADMIN]
    assert Permission.PILOT_PROBE in ROLE_PERMISSIONS[TenantRole.OWNER]
    assert Permission.PILOT_PROBE not in ROLE_PERMISSIONS[TenantRole.ANALYST]
    assert Permission.PILOT_PROBE not in ROLE_PERMISSIONS[TenantRole.VIEWER]


def test_pilot_probe_source_has_no_mutation_path():
    src=(ROOT/'src/recovery/worker/pilot_probe.py').read_text()
    assert 'GoogleAdsNegativeMutation' not in src
    assert 'mutate_' not in src
    assert 'get_customer_profile' in src
    assert '"external_effect":"read_only"' in src


def test_epic13_migration_allows_only_read_probe_new_job_type():
    sql=(ROOT/'src/recovery/db/migrations/0021_epic13_pilot_hardening.sql').read_text()
    assert "'pilot_google_ads_read_probe'" in sql
    assert 'ALTER TABLE recovery.api_jobs' in sql


class _Cursor:
    def __init__(self,row):self.row=row
    def execute(self,*a,**k):return None
    def fetchone(self):return self.row
    def __enter__(self):return self
    def __exit__(self,*a):return False
class _Conn:
    def __init__(self,row):self.row=row
    def cursor(self):return _Cursor(self.row)
    def __enter__(self):return self
    def __exit__(self,*a):return False
class _Core:
    def __init__(self,row):self.row=row
    def _connect(self):return _Conn(self.row)
    def _set_tenant(self,cur,tenant):return None
class _Resolver:
    def client_for(self,**kwargs):return object()


def test_read_probe_returns_only_sanitized_customer_profile(monkeypatch):
    import recovery.worker.pilot_probe as mod
    account=uuid4();tenant=uuid4();job=uuid4();core=_Core({'id':account,'customer_id':'1234567890','credential_ref':'oauth-connection:x'})
    class Adapter:
        @classmethod
        def from_google_ads_client(cls,c):return cls()
        def get_customer_profile(self,cid):return {'customer_id':'1234567890','descriptive_name':'Pilot','currency_code':'INR','time_zone':'Asia/Kolkata','manager':False,'status':'ENABLED','test_account':True}
    monkeypatch.setattr(mod,'GoogleAdsV26Adapter',Adapter)
    out=GoogleAdsPilotReadProbeJobRunner(core=core,client_resolver=_Resolver())(tenant_id=tenant,job_id=job,payload={'account_id':str(account)})
    assert out['probe']=='google_ads_read_ok' and out['external_effect']=='read_only'
    assert out['customer_id']=='1234567890' and out['test_account'] is True
    assert 'credential_ref' not in out


def _principal(user):
    return Principal(user_id=user,subject=str(user),email='a@test',issuer='https://x.supabase.co/auth/v1',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))


def test_pilot_probe_api_is_not_available_to_analyst():
    tenant=uuid4();user=uuid4();account=uuid4()
    class Repo:
        def touch_user(self,**k):return True
        def list_memberships(self,**k):return [{'tenant_id':tenant,'tenant_name':'T','role':'analyst','status':'active'}]
        def membership(self,**k):return Membership(tenant,TenantRole.ANALYST,'active')
    c=TestClient(create_app(repository=Repo(),verifier=StaticTokenVerifier({'token':_principal(user)})))
    r=c.post(f'/v1/tenants/{tenant}/accounts/{account}/pilot-google-ads-read-probe',headers={'Authorization':'Bearer token','Idempotency-Key':'x'},json={})
    assert r.status_code==403


def test_pilot_probe_api_admin_queues_exact_read_job():
    tenant=uuid4();user=uuid4();account=uuid4();job=uuid4()
    class Repo:
        def touch_user(self,**k):return True
        def list_memberships(self,**k):return [{'tenant_id':tenant,'tenant_name':'T','role':'admin','status':'active'}]
        def membership(self,**k):return Membership(tenant,TenantRole.ADMIN,'active')
        def ensure_account(self,**k):return None
        def enqueue_job(self,**k):
            assert k['job_type'] is JobType.PILOT_GOOGLE_ADS_READ_PROBE and k['payload']=={'account_id':str(account)}
            return JobReceipt(job,JobType.PILOT_GOOGLE_ADS_READ_PROBE,JobStatus.QUEUED)
    c=TestClient(create_app(repository=Repo(),verifier=StaticTokenVerifier({'token':_principal(user)})))
    r=c.post(f'/v1/tenants/{tenant}/accounts/{account}/pilot-google-ads-read-probe',headers={'Authorization':'Bearer token','Idempotency-Key':'pilot1'},json={})
    assert r.status_code==202 and r.json()['job_type']=='pilot_google_ads_read_probe'


def test_staging_acceptance_can_require_google_test_account(monkeypatch):
    import recovery.acceptance as mod
    tenant=uuid4();account=uuid4()
    def req(url,**kwargs):
        if url.endswith('/healthz'):return 200,{'status':'ok'}
        if url.endswith('/readyz'):return 200,{'status':'ready','migrations':21}
        if url.endswith('/buildz'):return 200,{'release_id':'r1','version':'0.32.0'}
        if url.endswith('/v1/me'):return 200,{'memberships':[{'tenant_id':str(tenant)}]}
        if url.endswith('/deployment-probe'):return 202,{'job_id':'d1'}
        if url.endswith('/pilot-google-ads-read-probe'):return 202,{'job_id':'g1'}
        if url.endswith('/jobs/d1'):return 200,{'status':'succeeded','result':{'probe':'ok','release_id':'r1'}}
        if url.endswith('/jobs/g1'):return 200,{'status':'succeeded','result':{'probe':'google_ads_read_ok','test_account':True,'customer_id':'1234567890','external_effect':'read_only','google_ads_api_version':'v26'}}
        if url.endswith('/billing'):return 200,{'entitlement_state':'full','provider_status':'active'}
        raise AssertionError(url)
    monkeypatch.setattr(mod,'_json_request',req);monkeypatch.setattr(mod,'_http_status',lambda *a,**k:200)
    report=StagingAcceptance(api_url='https://api',dashboard_url='https://app',tenant_id=tenant,bearer_token='t',expected_release_id='r1',require_billing_full=True,google_ads_account_id=account,require_google_ads_read=True,require_google_test_account=True).run()
    assert report.passed is True and {x.name:x for x in report.checks}['google_ads_read_probe'].metadata['test_account'] is True


def test_staging_acceptance_fails_when_test_account_requirement_hits_production(monkeypatch):
    import recovery.acceptance as mod
    tenant=uuid4();account=uuid4()
    def req(url,**kwargs):
        if url.endswith('/healthz'):return 200,{'status':'ok'}
        if url.endswith('/readyz'):return 200,{'status':'ready'}
        if url.endswith('/buildz'):return 200,{'release_id':'r1','version':'0.32.0'}
        if url.endswith('/v1/me'):return 200,{'memberships':[{'tenant_id':str(tenant)}]}
        if url.endswith('/deployment-probe'):return 202,{'job_id':'d'}
        if url.endswith('/pilot-google-ads-read-probe'):return 202,{'job_id':'g'}
        if url.endswith('/jobs/d'):return 200,{'status':'succeeded','result':{'probe':'ok','release_id':'r1'}}
        if url.endswith('/jobs/g'):return 200,{'status':'succeeded','result':{'probe':'google_ads_read_ok','test_account':False,'external_effect':'read_only'}}
        if url.endswith('/billing'):return 200,{'entitlement_state':'full'}
        raise AssertionError(url)
    monkeypatch.setattr(mod,'_json_request',req);monkeypatch.setattr(mod,'_http_status',lambda *a,**k:200)
    report=StagingAcceptance(api_url='https://api',dashboard_url='https://app',tenant_id=tenant,bearer_token='t',expected_release_id='r1',google_ads_account_id=account,require_google_ads_read=True,require_google_test_account=True).run()
    assert report.passed is False and {x.name:x.status for x in report.checks}['google_ads_read_probe']=='fail'


def _write_gate_reports(tmp:Path,now:datetime,*,google='pass'):
    readiness={'environment':'staging','ready':True,'generated_at':now.isoformat(),'checks':[]}
    acceptance={'passed':True,'generated_at':now.isoformat(),'checks':[{'name':'api_liveness','status':'pass','metadata':{}},{'name':'api_readiness','status':'pass','metadata':{}},{'name':'api_release_identity','status':'pass','metadata':{'release_id':'r1'}},{'name':'dashboard_http','status':'pass','metadata':{}},{'name':'authenticated_api','status':'pass','metadata':{}},{'name':'worker_round_trip','status':'pass','metadata':{}},{'name':'google_ads_read_probe','status':google,'metadata':{}},{'name':'billing_acceptance','status':'pass','metadata':{}}]}
    (tmp/'ready.json').write_text(json.dumps(readiness));(tmp/'accept.json').write_text(json.dumps(acceptance));ev=tmp/'evidence';ev.mkdir()
    for kind in REQUIRED_EVIDENCE_MAX_AGE_DAYS:(ev/f'{kind}.json').write_text(json.dumps({'schema_version':EVIDENCE_SCHEMA,'kind':kind,'status':'pass','performed_at':now.isoformat(),'operator':'ops@example','detail':f'{kind} completed','release_id':'r1' if kind=='security_review' else None,'evidence_refs':['ticket:123']}))
    return ev


def test_pilot_gate_qualifies_only_with_deployed_and_external_evidence(tmp_path):
    now=datetime(2026,10,16,10,tzinfo=timezone.utc);ev=_write_gate_reports(tmp_path,now);assert PilotGate(readiness_report=tmp_path/'ready.json',acceptance_report=tmp_path/'accept.json',evidence_dir=ev,expected_release_id='r1',now=now).run().qualified is True


def test_pilot_gate_fails_missing_and_stale_evidence(tmp_path):
    now=datetime(2026,10,16,10,tzinfo=timezone.utc);ev=_write_gate_reports(tmp_path,now);(ev/'restore_drill.json').unlink();stale=json.loads((ev/'access_review.json').read_text());stale['performed_at']=(now-timedelta(days=31)).isoformat();(ev/'access_review.json').write_text(json.dumps(stale));r=PilotGate(readiness_report=tmp_path/'ready.json',acceptance_report=tmp_path/'accept.json',evidence_dir=ev,expected_release_id='r1',now=now).run();statuses={x.name:x.status for x in r.checks};assert r.qualified is False and statuses['restore_drill']=='fail' and statuses['access_review']=='fail'


def test_pilot_gate_rejects_acceptance_without_google_read(tmp_path):
    now=datetime(2026,10,16,10,tzinfo=timezone.utc);ev=_write_gate_reports(tmp_path,now,google='skip');r=PilotGate(readiness_report=tmp_path/'ready.json',acceptance_report=tmp_path/'accept.json',evidence_dir=ev,expected_release_id='r1',now=now).run();assert r.qualified is False and {x.name:x.status for x in r.checks}['deployed_acceptance']=='fail'


def test_pilot_gate_rejects_stale_deployed_reports(tmp_path):
    now=datetime(2026,10,16,10,tzinfo=timezone.utc);ev=_write_gate_reports(tmp_path,now);ready=json.loads((tmp_path/'ready.json').read_text());ready['generated_at']=(now-timedelta(hours=25)).isoformat();(tmp_path/'ready.json').write_text(json.dumps(ready));accept=json.loads((tmp_path/'accept.json').read_text());accept['generated_at']=(now-timedelta(hours=25)).isoformat();(tmp_path/'accept.json').write_text(json.dumps(accept));r=PilotGate(readiness_report=tmp_path/'ready.json',acceptance_report=tmp_path/'accept.json',evidence_dir=ev,expected_release_id='r1',now=now).run();s={x.name:x for x in r.checks};assert r.qualified is False and 'older than 24 hours' in s['production_readiness'].detail and 'older than 24 hours' in s['deployed_acceptance'].detail


def _free_port():
    s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();return p

def _status(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())


def test_worker_health_server_startup_and_liveness_state():
    state=WorkerHealthState.create(worker_version='0.32.0');port=_free_port();server=WorkerHealthServer(state=state,host='127.0.0.1',port=port);server.start()
    try:
        assert _status(f'http://127.0.0.1:{port}/startup')[0]==503;state.startup_complete=True;code,payload=_status(f'http://127.0.0.1:{port}/startup');assert code==200 and payload['startup_complete'] is True;assert _status(f'http://127.0.0.1:{port}/health')[0]==200;state.stopping=True;assert _status(f'http://127.0.0.1:{port}/health')[0]==503
    finally:server.close()


def test_deployment_pilot_artifacts_enforce_safe_staging_and_health_contract():
    worker=(ROOT/'deploy/gcloud-worker.ps1').read_text();pilot=(ROOT/'deploy/pilot-staging.ps1').read_text();health=(ROOT/'deploy/configure-worker-health.py').read_text();backup=(ROOT/'deploy/pilot-cloudsql-backup-check.ps1').read_text();assert 'RECOVERY_WORKER_HEALTH_PORT=$HealthPort' in worker and '-RequireGoogleAdsRead -RequireGoogleTestAccount' in pilot and 'RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID' in pilot and 'validateOnly' in health and '/startup' in health and '/health' in health and 'pointInTimeRecoveryEnabled' in backup


def test_pilot_observability_helper_requires_worker_probes_and_monitoring_policies():
    script=(ROOT/'deploy/pilot-observability-check.ps1').read_text();assert 'gcloud run worker-pools describe' in script and 'gcloud monitoring policies list' in script and 'startupProbe.httpGet.path' in script and 'livenessProbe.httpGet.path' in script and 'MinAlertPolicies' in script and 'RequiredPolicyPattern' in script and 'observability_alerts' in script and 'recovery-pilot-evidence.v1' in script


def test_pilot_runbook_separates_backup_configuration_from_real_restore_drill():
    runbook=(ROOT/'docs/EPIC13_PILOT_RUNBOOK.md').read_text();assert 'This is **not** the restore drill.' in runbook and 'disposable target' in runbook and 'gcloud sql backups restore' in runbook and 'google_ads_mutations=false' in runbook and 'Test Mode success is integration evidence, not live merchant activation evidence.' in runbook


def test_pilot_slo_contract_separates_process_provider_and_product_health():
    slo=(ROOT/'docs/EPIC13_PILOT_SLO.md').read_text();assert '99.5%' in slo and 'Cloud Run startup/liveness' in slo and 'Recovery OS Monitoring' in slo and 'needs_reconciliation' in slo
