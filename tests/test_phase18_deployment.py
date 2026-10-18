from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import StaticTokenVerifier
from recovery.deployment import ProductionReadiness


class EmptyRepo:
    pass


def service_account(tmp_path: Path) -> str:
    p=tmp_path/'google.json'
    p.write_text(json.dumps({
        'type':'service_account','project_id':'proj','client_email':'svc@example.iam.gserviceaccount.com',
        'private_key':'-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n'
    }), encoding='utf-8')
    return str(p)


def base_env(tmp_path: Path, *, environment='staging'):
    return {
        'RECOVERY_ENVIRONMENT': environment,
        'DATABASE_URL': 'postgresql://user:secret@db.example/postgres',
        'RECOVERY_WORKER_DATABASE_URL': 'postgresql://worker:secret@db.example/postgres',
        'SUPABASE_URL': 'https://abc.supabase.co',
        'API_ALLOWED_ORIGINS': 'https://app.example.com',
        'GOOGLE_ADS_SERVICE_ACCOUNT_JSON': service_account(tmp_path),
        'GEMINI_API_KEY': 'fake-test-key',
        'BILLING_ENABLED': 'true',
        'RAZORPAY_KEY_ID': 'rzp_test_fake' if environment=='staging' else 'rzp_live_fake',
        'RAZORPAY_KEY_SECRET': 'fake',
        'RAZORPAY_WEBHOOK_SECRET': 'fake',
        'BILLING_PLANS_JSON': '[{"key":"starter"}]',
        'RECOVERY_BACKUP_POLICY_ACK': 'PITR_OR_DAILY_BACKUP_VERIFIED',
    }


def test_staging_static_readiness_passes_and_never_returns_secret_values(tmp_path):
    env=base_env(tmp_path)
    report=ProductionReadiness(env).run(probe_database=False)
    assert report.ready is True
    rendered=json.dumps(report.to_dict())
    assert 'fake-test-key' not in rendered
    assert 'postgresql://user:secret' not in rendered
    assert 'BEGIN PRIVATE KEY' not in rendered


def test_production_requires_https_cors_live_billing_and_backup_ack(tmp_path):
    env=base_env(tmp_path, environment='production')
    env['API_ALLOWED_ORIGINS']='http://app.example.com'
    env['RAZORPAY_KEY_ID']='rzp_test_wrong'
    env['RECOVERY_BACKUP_POLICY_ACK']=''
    report=ProductionReadiness(env).run(probe_database=False)
    assert report.ready is False
    failed={c.name for c in report.checks if c.status=='fail'}
    assert {'cors_origins','billing_mode','backup_policy'} <= failed


def test_missing_google_key_file_fails_closed(tmp_path):
    env=base_env(tmp_path)
    env['GOOGLE_ADS_SERVICE_ACCOUNT_JSON']=str(tmp_path/'missing.json')
    report=ProductionReadiness(env).run(probe_database=False)
    assert any(c.name=='google_ads_credentials' and c.status=='fail' for c in report.checks)


def test_api_exposes_separate_liveness_and_readiness_endpoints():
    app=create_app(repository=EmptyRepo(), verifier=StaticTokenVerifier({}), readiness_probe=lambda:{'database':'ready','migrations':7})
    client=TestClient(app)
    assert client.get('/healthz').json()=={'status':'ok'}
    r=client.get('/readyz')
    assert r.status_code==200 and r.json()['database']=='ready'


def test_api_readiness_fails_without_leaking_exception():
    def boom(): raise RuntimeError('postgresql://user:super-secret@host/db')
    app=create_app(repository=EmptyRepo(), verifier=StaticTokenVerifier({}), readiness_probe=boom)
    r=TestClient(app).get('/readyz')
    assert r.status_code==503
    assert 'super-secret' not in r.text
    assert r.json()=={'status':'not-ready'}


def test_phase18_deployment_artifacts_use_worker_pool_and_non_root_container():
    root=Path(__file__).resolve().parents[1]
    docker=(root/'deploy'/'Dockerfile.backend').read_text()
    worker=(root/'deploy'/'gcloud-worker.ps1').read_text()
    api=(root/'deploy'/'gcloud-api.ps1').read_text()
    assert 'USER recovery' in docker
    assert 'recovery.api.app:create_app_from_env' in docker
    assert 'gcloud run worker-pools deploy' in worker
    assert '--instances $Instances' in worker
    assert '--command recovery-worker' in worker
    assert '--readiness-probe' in api and '/readyz' in api
    assert 'RAZORPAY_KEY_SECRET=' not in worker


def test_worker_cli_has_sigterm_handler():
    root=Path(__file__).resolve().parents[1]
    src=(root/'src'/'recovery'/'worker'/'cli.py').read_text()
    assert 'signal.SIGTERM' in src
    assert 'stop_event=stop_event' in src

def test_production_self_serve_oauth_requires_restricted_scope_verification_ack(tmp_path):
    env=base_env(tmp_path, environment='production')
    env.update({
        'GOOGLE_ADS_OAUTH_CLIENT_ID':'client-id',
        'GOOGLE_ADS_OAUTH_CLIENT_SECRET':'client-secret',
        'GOOGLE_ADS_OAUTH_REDIRECT_URI':'https://app.example.com/api/google-ads/oauth/callback',
        'GOOGLE_OAUTH_SECRET_MANAGER_PROJECT':'proj',
    })
    env.pop('GOOGLE_ADS_SERVICE_ACCOUNT_JSON', None)
    report=ProductionReadiness(env).run(probe_database=False)
    assert any(c.name=='google_ads_oauth' and c.status=='fail' for c in report.checks)
    env['GOOGLE_ADS_OAUTH_VERIFICATION_ACK']='RESTRICTED_SCOPE_VERIFIED'
    report=ProductionReadiness(env).run(probe_database=False)
    assert any(c.name=='google_ads_oauth' and c.status=='pass' for c in report.checks)


def test_billing_grace_policy_is_bounded_and_non_secret(tmp_path):
    env=base_env(tmp_path)
    env['BILLING_GRACE_HOURS']='24'
    report=ProductionReadiness(env).run(probe_database=False)
    check=next(c for c in report.checks if c.name=='billing_grace_policy')
    assert check.status=='pass' and check.metadata['grace_hours']==24
    env['BILLING_GRACE_HOURS']='721'
    report=ProductionReadiness(env).run(probe_database=False)
    assert any(c.name=='billing_grace_policy' and c.status=='fail' for c in report.checks)
    env['BILLING_GRACE_HOURS']='not-an-int'
    report=ProductionReadiness(env).run(probe_database=False)
    assert any(c.name=='billing_grace_policy' and c.status=='fail' for c in report.checks)


def test_cloud_run_api_deploys_explicit_billing_grace_policy():
    root=Path(__file__).resolve().parents[1]
    api=(root/'deploy'/'gcloud-api.ps1').read_text()
    assert '[ValidateRange(0,720)][int]$BillingGraceHours = 0' in api
    assert 'BILLING_GRACE_HOURS=$BillingGraceHours' in api
