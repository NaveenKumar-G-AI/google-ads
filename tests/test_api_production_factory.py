"""Exercise the same app factory used by the Docker/Render entrypoint.

No provider or database request is allowed: only repository boundary methods are
stubbed. Test environment values are synthetic and isolated from local secrets.
"""

from datetime import datetime, timezone
import json
import os
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

import recovery.api.app as api
from recovery.api.auth import Principal
from recovery.signup_abuse import TurnstileVerifier


@pytest.fixture
def factory_env(monkeypatch):
    values = {
        "DATABASE_URL": "postgresql://test:unused@database.invalid/recovery",
        "SUPABASE_URL": "https://recovery-test.supabase.co",
        "API_ALLOWED_ORIGINS": "https://app.example.com",
        "RECOVERY_ENVIRONMENT": "staging",
        "RECOVERY_RELEASE_ID": "factory-test",
        "BILLING_ENABLED": "false",
    }

    def no_database(*args, **kwargs):
        raise AssertionError("factory tests must not connect to a database")

    monkeypatch.setattr(api.PostgresRecoveryRepository, "_connect", no_database)
    with patch.dict(os.environ, values, clear=True):
        yield


def test_deployment_factory_registers_authenticated_onboarding_routes(factory_env):
    app = api.create_app_from_env()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        for path in ("/v1/me", "/v1/launch/status/me", f"/v1/tenants/{uuid4()}/onboarding"):
            response = client.get(path)
            assert response.status_code == 401, (path, response.text)
            assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


@pytest.mark.parametrize("providers_enabled", [False, True])
def test_deployment_factory_constructs_and_wires_turnstile(factory_env, monkeypatch, providers_enabled):
    monkeypatch.setenv("RECOVERY_TURNSTILE_SITE_KEY", "synthetic-site-key")
    monkeypatch.setenv("RECOVERY_TURNSTILE_SECRET", "synthetic-private-key")
    monkeypatch.setenv("RECOVERY_TURNSTILE_HOSTNAMES", "APP.EXAMPLE.COM.,app.example.com")
    monkeypatch.setenv("RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H", "2")
    if providers_enabled:
        configured = {
            "BILLING_ENABLED": "true",
            "RAZORPAY_KEY_ID": "rzp_test_factory",
            "RAZORPAY_KEY_SECRET": "synthetic-billing-secret",
            "RAZORPAY_WEBHOOK_SECRET": "synthetic-webhook-secret",
            "BILLING_PLANS_JSON": json.dumps([{
                "key": "starter", "display_name": "Starter",
                "provider_plan_id": "plan_factory", "currency": "INR",
                "amount_subunits": 10000, "total_count": 12,
                "max_google_ads_accounts": 1, "max_sync_range_days": 90,
            }]),
            "GOOGLE_ADS_OAUTH_CLIENT_ID": "factory.apps.googleusercontent.com",
            "GOOGLE_ADS_OAUTH_CLIENT_SECRET": "synthetic-oauth-secret",
            "GOOGLE_ADS_OAUTH_REDIRECT_URI": "https://app.example.com/api/google-ads/oauth/callback",
            "GOOGLE_OAUTH_SECRET_MANAGER_PROJECT": "recovery-factory-test",
        }
        for name, value in configured.items():
            monkeypatch.setenv(name, value)
    captured = []
    service_type = api.OnboardingApplicationService

    def record_service(**kwargs):
        captured.append(kwargs)
        return service_type(**kwargs)

    monkeypatch.setattr(api, "OnboardingApplicationService", record_service)
    monkeypatch.setattr(
        api.PostgresApiRepository,
        "public_launch_status",
        lambda self, **kwargs: {
            "launch_mode": "closed",
            "workspace_creation_open": False,
            "access_granted": False,
            "access_hint": None,
            "access_expires_at": None,
            "release_id": "factory-test",
        },
    )

    app = api.create_app_from_env()
    verifier = captured[0]["signup_abuse_verifier"]
    assert isinstance(verifier, TurnstileVerifier)
    assert verifier.config.expected_hostnames == frozenset({"app.example.com"})
    assert captured[0]["store"].public_workspace_max_per_user_24h == 2
    assert (captured[0]["oauth"] is not None) is providers_enabled
    assert (captured[0]["billing"].runtime is not None) is providers_enabled
    with TestClient(app) as client:
        response = client.get("/v1/launch/status")
        assert response.status_code == 200
        body = response.json()
        assert body["signup_abuse_ready"] is True
        assert body["turnstile_site_key"] == "synthetic-site-key"
        assert body["public_workspace_max_per_user_24h"] == 2
        assert body["workspace_creation_open"] is False
        assert "synthetic-private-key" not in response.text


def test_deployment_factory_serves_signed_in_user_without_workspace(factory_env, monkeypatch):
    user_id = uuid4()
    principal = Principal(
        user_id=user_id,
        subject=str(user_id),
        email="new-user@example.com",
        issuer="https://recovery-test.supabase.co/auth/v1",
        audience="authenticated",
        role_claim="authenticated",
        issued_at=None,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(api.SupabaseJWTVerifier, "verify", lambda self, token: principal)
    monkeypatch.setattr(api.PostgresApiRepository, "touch_user", lambda self, **kwargs: True)
    monkeypatch.setattr(api.PostgresApiRepository, "list_memberships", lambda self, **kwargs: [])
    seen = []

    def launch_status(self, **kwargs):
        seen.append(kwargs)
        return {
            "launch_mode": "closed",
            "workspace_creation_open": False,
            "access_granted": False,
            "access_hint": None,
            "access_expires_at": None,
            "release_id": "factory-test",
        }

    monkeypatch.setattr(api.PostgresApiRepository, "public_launch_status", launch_status)
    with TestClient(api.create_app_from_env()) as client:
        headers = {"Authorization": "Bearer synthetic-test-token"}
        me = client.get("/v1/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["memberships"] == []
        launch = client.get("/v1/launch/status/me", headers=headers)
        assert launch.status_code == 200
        assert launch.json()["workspace_creation_open"] is False
        assert seen == [{"user_id": user_id, "email": "new-user@example.com"}]


@pytest.mark.parametrize(
    "variable,value,message",
    [
        ("RECOVERY_TURNSTILE_SITE_KEY", "site", "must be configured together"),
        ("GOOGLE_ADS_OAUTH_CLIENT_ID", "client", "must all be configured together"),
        ("BILLING_ENABLED", "true", "RAZORPAY_WEBHOOK_SECRET is required"),
    ],
)
def test_deployment_factory_rejects_partial_provider_configuration(
    factory_env, monkeypatch, variable, value, message
):
    monkeypatch.setenv(variable, value)
    with pytest.raises(RuntimeError, match=message):
        api.create_app_from_env()
