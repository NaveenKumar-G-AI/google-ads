from fastapi.testclient import TestClient
from recovery.api.app import create_app


class Repo:
    def public_launch_status(self,**kwargs):
        return {'launch_mode':'public','workspace_creation_open':True,'access_granted':False,'access_hint':None,'access_expires_at':None,'release_id':'r14'}


class Verifier:
    def verify(self,token): raise AssertionError('public launch status must not require auth')


def test_public_launch_status_returns_server_authoritative_legal_policy_identity():
    app=create_app(repository=Repo(),verifier=Verifier(),public_legal_config={'terms_url':'https://example.com/terms','terms_version':'terms-2026-10','privacy_url':'https://example.com/privacy','privacy_version':'privacy-2026-10'})
    r=TestClient(app).get('/v1/launch/status')
    assert r.status_code==200
    body=r.json()
    assert body['launch_mode']=='public' and body['workspace_creation_open'] is True
    assert body['legal_acceptance_ready'] is True
    assert body['terms_url']=='https://example.com/terms'
    assert body['terms_version']=='terms-2026-10'
    assert body['privacy_url']=='https://example.com/privacy'
    assert body['privacy_version']=='privacy-2026-10'


def test_public_launch_status_fails_legal_readiness_when_config_is_partial():
    app=create_app(repository=Repo(),verifier=Verifier(),public_legal_config={'terms_url':'https://example.com/terms','terms_version':'terms-1'})
    body=TestClient(app).get('/v1/launch/status').json()
    assert body['legal_acceptance_ready'] is False
    assert body['privacy_url'] is None and body['privacy_version'] is None
