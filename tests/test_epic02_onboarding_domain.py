from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from recovery.onboarding import (
    GOOGLE_ADS_SCOPE,
    GoogleOAuthProvider,
    GoogleOAuthSettings,
    GuidedGeoAreaInput,
    GuidedNonOfferInput,
    GuidedOfferInput,
    OAuthTokenSet,
    build_guided_business_truth_payload,
)
from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.google_ads.auth import UserOAuthConfig


def test_google_oauth_authorization_requests_offline_ads_scope_and_state():
    provider = GoogleOAuthProvider(GoogleOAuthSettings(
        client_id="client.apps.googleusercontent.com",
        client_secret="secret",
        redirect_uri="https://app.example.com/api/google-ads/oauth/callback",
    ))
    url = provider.authorization_url(state="abc-state", login_hint="owner@example.com")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert q["scope"] == [GOOGLE_ADS_SCOPE]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["abc-state"]
    assert q["login_hint"] == ["owner@example.com"]


def test_oauth_token_requires_refresh_token_for_background_saas():
    with pytest.raises(ValueError, match="refresh token"):
        OAuthTokenSet(access_token="a", refresh_token="", expires_in=3600, scope=GOOGLE_ADS_SCOPE, token_type="Bearer")


def test_user_oauth_config_never_requires_customer_id_or_developer_token():
    config = UserOAuthConfig(client_id="id", client_secret="secret", refresh_token="refresh")
    assert config.client_configuration() == {
        "client_id":"id", "client_secret":"secret", "refresh_token":"refresh", "use_proto_plus":True
    }


def test_guided_business_truth_is_valid_phase2_truth_without_raw_json_knowledge():
    payload = build_guided_business_truth_payload(
        business_id="acct-1", business_name="Northstar Roofing", version=1, actor="user:1",
        offers=(GuidedOfferInput("Roof replacement","Residential roof replacement",("new roof",)),),
        non_offers=(GuidedNonOfferInput("Roofing jobs","We are acquiring customers, not employees"),),
        service_areas=(GuidedGeoAreaInput("Dallas, Texas","US",region="Texas",city="Dallas"),),
        catalog_complete=False,
        employment_policy="deny", free_policy="conditional", diy_policy="deny",
        primary_outcomes=("Qualified roofing lead",),
        now=datetime(2026,10,15,tzinfo=timezone.utc),
    )
    snapshot = parse_business_truth_payload(payload, submitted_by="user:1")
    assert snapshot.business_name == "Northstar Roofing"
    assert snapshot.offers[0].name == "Roof replacement"
    assert snapshot.intent_policies[0].category.value == "employment"
    assert snapshot.intent_policies[0].disposition.value == "deny"
    assert snapshot.offer_catalog_completeness.value == "partial"


def test_guided_truth_does_not_default_unanswered_intents_to_deny():
    payload = build_guided_business_truth_payload(
        business_id="a",business_name="B",version=1,actor="u",
        offers=(GuidedOfferInput("Service","Paid service"),),non_offers=(),service_areas=(),catalog_complete=False,
        employment_policy="unknown",free_policy="unknown",diy_policy="unknown",primary_outcomes=("Qualified lead",),
    )
    assert {p["disposition"] for p in payload["intent_policies"]} == {"unknown"}
