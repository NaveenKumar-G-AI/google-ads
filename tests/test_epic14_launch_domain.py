from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
import json
import pytest

from recovery.api.auth import Principal
from recovery.api.onboarding_service import OnboardingApplicationService,PostgresOnboardingStore
from recovery.api.repository import ApiConflict
from recovery.launch_control import (
    LaunchMode,derive_launch_access,derive_launch_state,launch_email_hint,launch_email_sha256,
    normalize_launch_email,workspace_creation_allowed,
)
from recovery.launch_gate import LaunchGate,validate_launch_gate_report,LAUNCH_GATE_SCHEMA

NOW=datetime(2026,10,16,10,tzinfo=timezone.utc)


def principal():
    uid=uuid4()
    return Principal(uid,str(uid),'Founder@Example.COM','https://x.supabase.co/auth/v1','authenticated','authenticated',NOW,NOW+timedelta(days=1))


def test_launch_email_identity_is_normalized_hashed_and_masked():
    assert normalize_launch_email('  Founder@Example.COM ')=='founder@example.com'
    assert len(launch_email_sha256('Founder@Example.com'))==64
    assert launch_email_sha256('Founder@Example.com')==launch_email_sha256(' founder@example.COM ')
    assert launch_email_hint('founder@example.com')=='f*****r@example.com'


def test_launch_state_defaults_closed_and_latest_event_wins():
    assert derive_launch_state([]).mode is LaunchMode.CLOSED
    s=derive_launch_state([
        {'id':'1','launch_mode':'pilot_only','release_id':None,'qualification_id':None,'reason':'pilot','occurred_at':NOW},
        {'id':'2','launch_mode':'invite_only','release_id':None,'qualification_id':None,'reason':'invite','occurred_at':NOW+timedelta(minutes=1)},
    ])
    assert s.mode is LaunchMode.INVITE_ONLY and s.reason=='invite'


def test_launch_access_expiry_and_workspace_rules_fail_closed():
    active=derive_launch_access([{'id':'1','event_type':'granted','expires_at':NOW+timedelta(hours=1),'subject_hint':'f***@x','occurred_at':NOW}],now=NOW)
    expired=derive_launch_access([{'id':'1','event_type':'granted','expires_at':NOW-timedelta(seconds=1),'subject_hint':'f***@x','occurred_at':NOW}],now=NOW)
    assert workspace_creation_allowed(LaunchMode.PUBLIC,expired) is True
    assert workspace_creation_allowed(LaunchMode.PILOT_ONLY,active) is True
    assert workspace_creation_allowed(LaunchMode.INVITE_ONLY,expired) is False
    assert workspace_creation_allowed(LaunchMode.CLOSED,active) is False


def test_launch_gate_report_validation_requires_exact_release_freshness_and_all_pass():
    report={'schema_version':LAUNCH_GATE_SCHEMA,'generated_at':NOW.isoformat(),'expected_release_id':'r14','qualified':True,'checks':[{'name':'x','status':'pass','detail':'ok','metadata':{}}]}
    validate_launch_gate_report(report,now=NOW,expected_release_id='r14')
    with pytest.raises(ValueError,match='release_id mismatch'):
        validate_launch_gate_report(report,now=NOW,expected_release_id='other')
    stale={**report,'generated_at':(NOW-timedelta(hours=25)).isoformat()}
    with pytest.raises(ValueError,match='stale'):
        validate_launch_gate_report(stale,now=NOW)
    bad={**report,'checks':[{'name':'x','status':'fail','detail':'bad','metadata':{}}]}
    with pytest.raises(ValueError,match='non-pass'):
        validate_launch_gate_report(bad,now=NOW)


def test_v1_launch_gate_rejects_pilot_gate_from_different_release(tmp_path:Path):
    pilot=tmp_path/'pilot.json';pilot.write_text(json.dumps({'generated_at':NOW.isoformat(),'expected_release_id':'old-release','qualified':True,'checks':[{'status':'pass'}]}))
    gate=LaunchGate(pilot_gate_report=pilot,readiness_report=tmp_path/'ready.json',acceptance_report=tmp_path/'accept.json',evidence_dir=tmp_path,expected_release_id='new-release',now=NOW)
    gate._pilot()
    assert gate.checks[0].status=='fail'
    assert 'does not match' in gate.checks[0].detail


def test_onboarding_service_requires_complete_https_legal_configuration():
    class Store: pass
    with pytest.raises(ValueError,match='configured together'):
        OnboardingApplicationService(store=Store(),api_repository=object(),oauth=None,terms_url='https://x/terms',terms_version='v1')
    with pytest.raises(ValueError,match='HTTPS'):
        OnboardingApplicationService(store=Store(),api_repository=object(),oauth=None,terms_url='http://x/terms',terms_version='v1',privacy_url='https://x/privacy',privacy_version='p1')


def test_onboarding_service_forwards_server_legal_identity_and_explicit_confirmation():
    class Store:
        def __init__(self): self.kwargs=None
        def create_organization(self,**kwargs): self.kwargs=kwargs;return uuid4(),False
    store=Store();svc=OnboardingApplicationService(store=store,api_repository=object(),oauth=None,terms_url='https://x/terms',terms_version='terms-7',privacy_url='https://x/privacy',privacy_version='privacy-4')
    svc.create_organization(principal=principal(),display_name='Acme',slug='acme',idempotency_key='k1',legal_acceptance_confirmed=True,accepted_terms_version='terms-7',accepted_privacy_version='privacy-4')
    assert store.kwargs['legal_acceptance_confirmed'] is True
    assert store.kwargs['required_terms_url']=='https://x/terms'
    assert store.kwargs['required_terms_version']=='terms-7'
    assert store.kwargs['required_privacy_url']=='https://x/privacy'
    assert store.kwargs['required_privacy_version']=='privacy-4'


def test_postgres_store_rejects_missing_confirmation_or_wrong_version_before_database_access():
    class ExplodingCore:
        def _connect(self): raise AssertionError('database must not be touched')
    store=PostgresOnboardingStore(ExplodingCore())
    p=principal()
    with pytest.raises(ApiConflict,match='explicit Terms and Privacy acceptance'):
        store.create_organization(principal=p,display_name='Acme',slug='acme',idempotency_key='k1',legal_acceptance_confirmed=False,accepted_terms_version='t1',accepted_privacy_version='p1',required_terms_url='https://x/terms',required_terms_version='t1',required_privacy_url='https://x/privacy',required_privacy_version='p1')
    with pytest.raises(ApiConflict,match='Terms of Service'):
        store.create_organization(principal=p,display_name='Acme',slug='acme',idempotency_key='k2',legal_acceptance_confirmed=True,accepted_terms_version='old',accepted_privacy_version='p1',required_terms_url='https://x/terms',required_terms_version='t1',required_privacy_url='https://x/privacy',required_privacy_version='p1')
