from __future__ import annotations

from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from recovery.api.app import create_app
from recovery.api.auth import Principal, StaticTokenVerifier
from recovery.api.onboarding_service import OnboardingApplicationService
from recovery.api.repository import ApiConflict
from recovery.deployment import ProductionReadiness
from recovery.launch_control import LaunchMode
from recovery.signup_abuse import SignupAbuseVerificationError, TurnstileConfig, TurnstileVerification, TurnstileVerifier

ROOT=Path(__file__).resolve().parents[1]

class Response:
    def __init__(self,payload,status=200): self.payload=payload;self.status=status
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self,n=-1): return json.dumps(self.payload).encode()


def verifier(monkeypatch,payload):
    monkeypatch.setattr('recovery.signup_abuse.urlrequest.urlopen',lambda req,timeout:Response(payload))
    return TurnstileVerifier(TurnstileConfig(site_key='site',secret_key='secret',expected_hostnames=frozenset({'app.example.com'})))


def test_turnstile_requires_hostname_action_and_recent_success(monkeypatch):
    v=verifier(monkeypatch,{'success':True,'hostname':'app.example.com','action':'workspace-create','challenge_ts':datetime.now(timezone.utc).isoformat()})
    out=v.verify(token='abc',idempotency_key=uuid4())
    assert out.hostname=='app.example.com' and out.action=='workspace-create'


def test_turnstile_rejects_wrong_hostname(monkeypatch):
    v=verifier(monkeypatch,{'success':True,'hostname':'evil.example','action':'workspace-create','challenge_ts':datetime.now(timezone.utc).isoformat()})
    with pytest.raises(SignupAbuseVerificationError,match='hostname'):v.verify(token='abc',idempotency_key=uuid4())


def test_turnstile_rejects_wrong_action(monkeypatch):
    v=verifier(monkeypatch,{'success':True,'hostname':'app.example.com','action':'login','challenge_ts':datetime.now(timezone.utc).isoformat()})
    with pytest.raises(SignupAbuseVerificationError,match='action'):v.verify(token='abc',idempotency_key=uuid4())


def test_turnstile_rejects_expired_challenge(monkeypatch):
    old=datetime.now(timezone.utc)-timedelta(minutes=10)
    v=verifier(monkeypatch,{'success':True,'hostname':'app.example.com','action':'workspace-create','challenge_ts':old.isoformat()})
    with pytest.raises(SignupAbuseVerificationError,match='expired'):v.verify(token='abc',idempotency_key=uuid4())


def test_turnstile_rejects_missing_or_oversize_token(monkeypatch):
    v=verifier(monkeypatch,{'success':True,'hostname':'app.example.com','action':'workspace-create'})
    with pytest.raises(SignupAbuseVerificationError):v.verify(token='',idempotency_key=uuid4())
    with pytest.raises(SignupAbuseVerificationError):v.verify(token='x'*2049,idempotency_key=uuid4())


def principal():
    u=uuid4();return Principal(user_id=u,subject=str(u),email='u@example.com',issuer='x',audience='authenticated',role_claim='authenticated',issued_at=None,expires_at=datetime(2099,1,1,tzinfo=timezone.utc))


def test_onboarding_public_mode_requires_and_forwards_verified_challenge():
    evidence=TurnstileVerification('app.example.com','workspace-create',datetime.now(timezone.utc))
    class Verify:
        def verify(self,**kwargs): assert kwargs['token']=='token';return evidence
    class Store:
        def organization_request_replay(self,**k): return None
        def current_launch_mode(self,**k): return LaunchMode.PUBLIC
        def create_organization(self,**k): self.kw=k;return uuid4(),False
    st=Store();svc=OnboardingApplicationService(store=st,api_repository=object(),oauth=None,signup_abuse_verifier=Verify())
    svc.create_organization(principal=principal(),display_name='Acme',slug='acme',idempotency_key='abc',turnstile_token='token')
    assert st.kw['public_abuse_verified'] is True and st.kw['public_abuse_evidence']==evidence


def test_onboarding_public_mode_fails_closed_without_verifier():
    class Store:
        def organization_request_replay(self,**k): return None
        def current_launch_mode(self,**k): return LaunchMode.PUBLIC
    svc=OnboardingApplicationService(store=Store(),api_repository=object(),oauth=None)
    with pytest.raises(ApiConflict,match='anti-abuse'):svc.create_organization(principal=principal(),display_name='Acme',slug='acme',idempotency_key='abc',turnstile_token='x')


def test_invite_mode_does_not_require_turnstile_runtime():
    class Store:
        def organization_request_replay(self,**k): return None
        def current_launch_mode(self,**k): return LaunchMode.INVITE_ONLY
        def create_organization(self,**k): self.kw=k;return uuid4(),False
    st=Store();svc=OnboardingApplicationService(store=st,api_repository=object(),oauth=None)
    svc.create_organization(principal=principal(),display_name='Acme',slug='acme',idempotency_key='abc')
    assert st.kw['public_abuse_verified'] is False


def test_public_launch_status_fails_closed_when_runtime_abuse_config_is_missing():
    class Repo:
        def public_launch_status(self,**k):return {'launch_mode':'public','workspace_creation_open':True,'access_granted':True,'access_hint':None,'access_expires_at':None,'release_id':'r1'}
    app=create_app(repository=Repo(),verifier=StaticTokenVerifier({}),public_signup_abuse_config={'ready':False,'site_key':None,'max_per_user_24h':1})
    body=TestClient(app).get('/v1/launch/status').json()
    assert body['workspace_creation_open'] is False and body['signup_abuse_ready'] is False


def base_env():
    return {'RECOVERY_ENVIRONMENT':'production','DATABASE_URL':'postgres://x','RECOVERY_WORKER_DATABASE_URL':'postgres://y','SUPABASE_URL':'https://x.supabase.co','API_ALLOWED_ORIGINS':'https://app.example.com','RECOVERY_BACKUP_POLICY_ACK':'PITR_OR_DAILY_BACKUP_VERIFIED','RECOVERY_TERMS_URL':'https://app.example.com/terms','RECOVERY_TERMS_VERSION':'t1','RECOVERY_PRIVACY_URL':'https://app.example.com/privacy','RECOVERY_PRIVACY_VERSION':'p1','RECOVERY_DATA_DELETION_URL':'https://app.example.com/delete','RECOVERY_SUPPORT_EMAIL':'support@example.com','GOOGLE_ADS_OAUTH_CLIENT_ID':'a','GOOGLE_ADS_OAUTH_CLIENT_SECRET':'b','GOOGLE_ADS_OAUTH_REDIRECT_URI':'https://app.example.com/api/google','GOOGLE_OAUTH_SECRET_MANAGER_PROJECT':'p','GOOGLE_ADS_OAUTH_VERIFICATION_ACK':'RESTRICTED_SCOPE_VERIFIED','GOOGLE_ADS_PRODUCTION_ACCESS_ACK':'EXPLORER_OR_HIGHER','GEMINI_API_KEY':'x','BILLING_ENABLED':'false'}


def test_production_readiness_requires_signup_abuse_configuration():
    r=ProductionReadiness(base_env()).run();checks={x.name:x for x in r.checks}
    assert checks['public_signup_abuse'].status=='fail'
    env=base_env()|{'RECOVERY_TURNSTILE_SITE_KEY':'site','RECOVERY_TURNSTILE_SECRET':'secret','RECOVERY_TURNSTILE_HOSTNAMES':'app.example.com','RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H':'1'}
    r=ProductionReadiness(env).run();checks={x.name:x for x in r.checks}
    assert checks['public_signup_abuse'].status=='pass'


def test_production_readiness_rejects_local_turnstile_hostname():
    env=base_env()|{'RECOVERY_TURNSTILE_SITE_KEY':'site','RECOVERY_TURNSTILE_SECRET':'secret','RECOVERY_TURNSTILE_HOSTNAMES':'localhost','RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H':'1'}
    checks={x.name:x for x in ProductionReadiness(env).run().checks}
    assert checks['public_signup_abuse'].status=='fail'


def test_database_and_store_contract_serialize_public_rate_boundary_and_never_store_token():
    sql=(ROOT/'src/recovery/db/migrations/0023_launch_execution_signup_abuse.sql').read_text()
    src=(ROOT/'src/recovery/api/onboarding_service.py').read_text()
    assert 'workspace_creation_abuse_events' in sql and 'prevent_immutable_mutation' in sql and 'FORCE ROW LEVEL SECURITY' in sql
    assert 'public-org-rate:' in src and "created_at>now()-interval '24 hours'" in src
    assert 'turnstile_token' not in sql and 'secret_key' not in sql
