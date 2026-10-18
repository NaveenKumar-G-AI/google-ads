from uuid import uuid4

import pytest

import recovery.worker.google_jobs as jobs
from recovery.onboarding import InMemoryCredentialVault
from recovery.worker.domain import PermanentWorkerError
from recovery.worker.google_jobs import PostgresOAuthAwareClientResolver


class DummyCore:
    pass


class Fallback:
    def __init__(self):
        self.calls=[]
    def client_for(self, **kwargs):
        self.calls.append(kwargs)
        return "fallback-client"


def test_oauth_backed_account_uses_customer_refresh_token_and_login_customer(monkeypatch):
    vault=InMemoryCredentialVault()
    ref=vault.put_refresh_token(secret_name="acct",refresh_token="refresh-123")
    resolver=PostgresOAuthAwareClientResolver(
        core=DummyCore(), oauth_client_id="cid", oauth_client_secret="secret", vault=vault, fallback=Fallback()
    )
    monkeypatch.setattr(
        PostgresOAuthAwareClientResolver,
        "_oauth_binding",
        lambda self, **kwargs: {
            "refresh_token_secret_ref":ref,"account_connection_status":"active","oauth_status":"connected",
            "login_customer_id":"1234567890","credential_ref":"oauth-connection:x",
        },
    )
    seen={}
    monkeypatch.setattr(jobs,"build_user_oauth_client",lambda config: seen.setdefault("config",config) or "unused")
    result=resolver.client_for(tenant_id=uuid4(),credential_ref="oauth-connection:x",customer_id="1112223333")
    config=seen["config"]
    assert config.refresh_token=="refresh-123"
    assert config.login_customer_id=="1234567890"
    assert config.client_id=="cid"
    assert result is config  # setdefault returns config


def test_oauth_backed_account_never_silently_falls_back(monkeypatch):
    fallback=Fallback()
    resolver=PostgresOAuthAwareClientResolver(
        core=DummyCore(),oauth_client_id="cid",oauth_client_secret="secret",
        vault=InMemoryCredentialVault(),fallback=fallback,
    )
    monkeypatch.setattr(PostgresOAuthAwareClientResolver,"_oauth_binding",lambda self,**kwargs: None)
    with pytest.raises(PermanentWorkerError) as exc:
        resolver.client_for(tenant_id=uuid4(),credential_ref="oauth-connection:x",customer_id="1112223333")
    assert exc.value.code=="GOOGLE_OAUTH_BINDING_MISSING"
    assert fallback.calls==[]


def test_legacy_account_can_use_service_account_fallback(monkeypatch):
    fallback=Fallback()
    resolver=PostgresOAuthAwareClientResolver(
        core=DummyCore(),oauth_client_id="cid",oauth_client_secret="secret",
        vault=InMemoryCredentialVault(),fallback=fallback,
    )
    monkeypatch.setattr(PostgresOAuthAwareClientResolver,"_oauth_binding",lambda self,**kwargs: None)
    assert resolver.client_for(tenant_id=uuid4(),credential_ref="legacy",customer_id="1112223333")=="fallback-client"
    assert len(fallback.calls)==1
