from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import secrets
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class OnboardingStep(str, Enum):
    ORGANIZATION = "organization"
    BILLING = "billing"
    GOOGLE_ADS = "google_ads"
    ACCOUNT_SELECTION = "account_selection"
    BUSINESS_TRUTH = "business_truth"
    MEASUREMENT = "measurement"
    FIRST_SYNC = "first_sync"
    FIRST_ANALYSIS = "first_analysis"
    FIRST_VALUE = "first_value"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class GoogleOAuthSettings:
    client_id: str
    client_secret: str
    redirect_uri: str

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("Google OAuth client_id is required")
        if not self.client_secret.strip():
            raise ValueError("Google OAuth client_secret is required")
        if not self.redirect_uri.startswith("https://") and not self.redirect_uri.startswith("http://localhost"):
            raise ValueError("Google OAuth redirect_uri must be HTTPS outside localhost")


@dataclass(frozen=True, slots=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    token_type: str

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise ValueError("OAuth access token is missing")
        if not self.refresh_token.strip():
            # Recovery OS needs offline background sync. A connection without a refresh
            # token cannot be treated as completed onboarding.
            raise ValueError("Google OAuth did not return a refresh token; offline access is required")
        if self.expires_in <= 0:
            raise ValueError("OAuth expires_in must be positive")
        scopes = {x for x in self.scope.split() if x}
        if GOOGLE_ADS_SCOPE not in scopes:
            raise ValueError("Google OAuth response did not grant the Google Ads scope")

    @property
    def refresh_token_sha256(self) -> str:
        return hashlib.sha256(self.refresh_token.encode("utf-8")).hexdigest()


class CredentialVault(Protocol):
    def put_refresh_token(self, *, secret_name: str, refresh_token: str) -> str: ...
    def get_refresh_token(self, *, secret_ref: str) -> str: ...
    def delete_secret(self, *, secret_ref: str) -> None: ...


class InMemoryCredentialVault:
    """Tests/local contract only. Production should use a managed secret vault."""
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put_refresh_token(self, *, secret_name: str, refresh_token: str) -> str:
        if not secret_name.strip() or not refresh_token.strip():
            raise ValueError("secret_name and refresh_token are required")
        ref = f"memory://{secret_name}"
        self._values[ref] = refresh_token
        return ref

    def get_refresh_token(self, *, secret_ref: str) -> str:
        try:
            return self._values[secret_ref]
        except KeyError as exc:
            raise KeyError("OAuth refresh-token secret not found") from exc

    def delete_secret(self, *, secret_ref: str) -> None:
        self._values.pop(secret_ref, None)


class GoogleSecretManagerCredentialVault:
    """Production refresh-token vault backed by Google Cloud Secret Manager.

    Tokens never enter application tables; only the returned secret resource reference is
    persisted. Import is lazy so offline domain tests do not require the cloud SDK.
    """
    def __init__(self, *, project_id: str) -> None:
        if not project_id.strip():
            raise ValueError("Secret Manager project_id is required")
        self.project_id = project_id.strip()

    def _client(self):
        from google.cloud import secretmanager
        return secretmanager.SecretManagerServiceClient()

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
        cleaned = cleaned.strip("-")[:240]
        if not cleaned:
            raise ValueError("secret name is empty after normalization")
        return cleaned

    def put_refresh_token(self, *, secret_name: str, refresh_token: str) -> str:
        if not refresh_token.strip():
            raise ValueError("refresh_token is required")
        client = self._client()
        parent = f"projects/{self.project_id}"
        sid = self._safe_name(secret_name)
        secret_path = f"{parent}/secrets/{sid}"
        from google.api_core.exceptions import NotFound
        try:
            client.get_secret(request={"name": secret_path})
        except NotFound:
            # Create only when genuinely absent. Permission/availability failures must
            # propagate instead of being misclassified as "secret missing".
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": sid,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        version = client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": refresh_token.encode("utf-8")},
            }
        )
        return str(version.name)

    def get_refresh_token(self, *, secret_ref: str) -> str:
        response = self._client().access_secret_version(request={"name": secret_ref})
        token = bytes(response.payload.data).decode("utf-8")
        if not token:
            raise RuntimeError("OAuth refresh-token secret is empty")
        return token

    def delete_secret(self, *, secret_ref: str) -> None:
        # Versions are immutable; delete the containing secret when the connection is revoked.
        parts = secret_ref.split("/versions/", 1)
        secret = parts[0]
        self._client().delete_secret(request={"name": secret})


class GoogleOAuthProvider:
    def __init__(self, settings: GoogleOAuthSettings, *, timeout_seconds: float = 30.0) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def new_state_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def state_sha256(state: str) -> str:
        if not state.strip():
            raise ValueError("OAuth state is required")
        return hashlib.sha256(state.encode("utf-8")).hexdigest()

    def authorization_url(self, *, state: str, login_hint: str | None = None) -> str:
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_ADS_SCOPE,
            "access_type": "offline",
            # Consent is explicit because background account sync depends on a refresh token.
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> OAuthTokenSet:
        if not code.strip():
            raise ValueError("OAuth authorization code is required")
        body = urlencode({
            "code": code,
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "redirect_uri": self.settings.redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        request = Request(
            GOOGLE_TOKEN_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed Google HTTPS endpoint
            payload = json.loads(response.read().decode("utf-8"))
        return OAuthTokenSet(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=int(payload.get("expires_in") or 0),
            scope=str(payload.get("scope") or ""),
            token_type=str(payload.get("token_type") or "Bearer"),
        )


@dataclass(frozen=True, slots=True)
class GuidedOfferInput:
    name: str
    description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidedNonOfferInput:
    name: str
    reason: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidedGeoAreaInput:
    display_name: str
    country_code: str
    region: str | None = None
    city: str | None = None
    postal_code: str | None = None


@dataclass(frozen=True, slots=True)
class GuidedAudienceInput:
    name: str
    disposition: str
    reason: str
    aliases: tuple[str, ...] = ()
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class GuidedProtectedQueryInput:
    query: str
    reason: str


def _slug(value: str, prefix: str) -> str:
    normalized = "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
    normalized = normalized.strip("-")[:48]
    digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{normalized or 'item'}-{digest}"


def confirmed_basis(*, actor: str, now: datetime, note: str) -> dict[str, Any]:
    return {
        "status": "confirmed",
        "evidence_ids": [],
        "confirmed_by": actor,
        "confirmed_at": now.isoformat(),
        "note": note,
    }


def build_guided_business_truth_payload(
    *,
    business_id: str,
    business_name: str,
    version: int,
    actor: str,
    offers: tuple[GuidedOfferInput, ...],
    non_offers: tuple[GuidedNonOfferInput, ...],
    service_areas: tuple[GuidedGeoAreaInput, ...],
    catalog_complete: bool,
    employment_policy: str,
    free_policy: str,
    diy_policy: str,
    primary_outcomes: tuple[str, ...],
    additional_intent_policies: tuple[tuple[str, str], ...] = (),
    audience_policies: tuple[GuidedAudienceInput, ...] = (),
    supporting_outcomes: tuple[str, ...] = (),
    invalid_outcomes: tuple[str, ...] = (),
    protected_queries: tuple[GuidedProtectedQueryInput, ...] = (),
    geo_requirement: str = "destination_or_job_must_be_in_service_area",
    geo_condition: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the validated Phase-2 payload from customer-friendly onboarding fields.

    The guided form does not force a customer to understand internal IDs, evidence
    objects, enum names, or raw JSON. Conservative defaults deliberately remain
    UNKNOWN/CONDITIONAL instead of inventing business exclusions.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not business_name.strip():
        raise ValueError("business_name is required")
    if not offers:
        raise ValueError("at least one active offer/service is required")
    if not primary_outcomes:
        raise ValueError("at least one primary business outcome is required")

    def disposition(value: str) -> str:
        v = value.strip().lower()
        if v not in {"allow", "deny", "conditional", "unknown"}:
            raise ValueError("guided intent policy must be allow, deny, conditional, or unknown")
        return v

    offer_rows = []
    for offer in offers:
        if not offer.name.strip() or not offer.description.strip():
            raise ValueError("each offer requires name and description")
        offer_rows.append({
            "offer_id": _slug(offer.name, "offer"),
            "name": offer.name.strip(),
            "aliases": [a.strip() for a in offer.aliases if a.strip()],
            "description": offer.description.strip(),
            "commercial_model": "unknown",
            "offer_status": "active",
            "basis": confirmed_basis(actor=actor, now=moment, note="Confirmed during guided onboarding"),
        })

    non_offer_rows = []
    for item in non_offers:
        if not item.name.strip() or not item.reason.strip():
            raise ValueError("each explicit non-offer requires name and reason")
        non_offer_rows.append({
            "exclusion_id": _slug(item.name, "nonoffer"),
            "name": item.name.strip(),
            "aliases": [a.strip() for a in item.aliases if a.strip()],
            "reason": item.reason.strip(),
            "basis": confirmed_basis(actor=actor, now=moment, note="Confirmed during guided onboarding"),
        })

    intent_rows = []
    raw_intent = [("employment", employment_policy), ("free", free_policy), ("diy", diy_policy), *additional_intent_policies]
    seen_categories: set[str] = set()
    allowed_categories = {
        "purchase","quote","booking","demo","trial","informational","diy","free","employment",
        "support","training","research","competitor","second_hand","rental","repair","wholesale","other",
    }
    for category, value in raw_intent:
        category = str(category).strip().lower()
        if category in seen_categories:
            raise ValueError(f"duplicate guided intent policy category: {category}")
        if category not in allowed_categories:
            raise ValueError(f"unsupported guided intent category: {category}")
        seen_categories.add(category)
        disp = disposition(value)
        reason = f"Business owner selected {disp} for {category} intent in Business Truth"
        row: dict[str, Any] = {
            "policy_id": f"business-truth-{category}",
            "category": category,
            "disposition": disp,
            "reason": reason,
            "basis": confirmed_basis(actor=actor, now=moment, note=reason),
            "offer_ids": [],
        }
        if disp == "conditional":
            row["condition"] = "Requires manual/contextual review until the business defines a narrower rule"
        intent_rows.append(row)

    audience_rows = []
    for item in audience_policies:
        disp = disposition(item.disposition)
        if not item.name.strip() or not item.reason.strip():
            raise ValueError("each audience policy requires name and reason")
        row = {
            "audience_id": _slug(item.name, "audience"),
            "name": item.name.strip(),
            "aliases": [a.strip() for a in item.aliases if a.strip()],
            "disposition": disp,
            "reason": item.reason.strip(),
            "basis": confirmed_basis(actor=actor, now=moment, note="Audience policy confirmed in Business Truth"),
        }
        if disp == "conditional":
            row["condition"] = (item.condition or "Requires contextual review").strip()
        audience_rows.append(row)

    geo_policy = None
    if service_areas:
        areas = []
        for idx, area in enumerate(service_areas, start=1):
            if not area.display_name.strip():
                raise ValueError("service area display_name is required")
            areas.append({
                "area_id": f"area-{idx}-{_slug(area.display_name, 'geo')[-16:]}",
                "display_name": area.display_name.strip(),
                "country_code": area.country_code.strip().upper(),
                "region": area.region.strip() if area.region else None,
                "city": area.city.strip() if area.city else None,
                "postal_code": area.postal_code.strip() if area.postal_code else None,
                "google_geo_target_constant": None,
            })
        requirement = geo_requirement.strip().lower()
        allowed_requirements={"no_restriction","customer_must_be_in_service_area","destination_or_job_must_be_in_service_area","conditional","unknown"}
        if requirement not in allowed_requirements:
            raise ValueError("unsupported geo requirement")
        if requirement == "no_restriction":
            raise ValueError("service areas cannot be supplied when geo requirement is no_restriction")
        geo_policy = {
            "requirement": requirement,
            "included_areas": areas,
            "excluded_areas": [],
            "basis": confirmed_basis(actor=actor, now=moment, note="Service areas confirmed during onboarding"),
            "condition": (geo_condition or "Requires contextual review").strip() if requirement == "conditional" else None,
        }
    elif geo_requirement.strip().lower() == "no_restriction":
        geo_policy = {
            "requirement": "no_restriction", "included_areas": [], "excluded_areas": [],
            "basis": confirmed_basis(actor=actor, now=moment, note="No geographic restriction confirmed in Business Truth"),
            "condition": None,
        }

    outcomes = []
    def add_outcomes(values: tuple[str, ...], role: str, label: str) -> None:
        for name in values:
            if not name.strip():
                continue
            outcomes.append({
                "outcome_id": _slug(f"{role}:{name}", "outcome"),
                "name": name.strip(),
                "role": role,
                "description": f"{label} confirmed in Business Truth: {name.strip()}",
                "basis": confirmed_basis(actor=actor, now=moment, note="Confirmed in guided Business Truth"),
            })
    add_outcomes(primary_outcomes, "primary_business_outcome", "Primary business outcome")
    add_outcomes(supporting_outcomes, "supporting_signal", "Supporting signal")
    add_outcomes(invalid_outcomes, "not_a_business_outcome", "Invalid/non-business outcome")
    if not any(x["role"] == "primary_business_outcome" for x in outcomes):
        raise ValueError("at least one nonblank primary business outcome is required")

    protected_rows=[]
    seen_protected=set()
    for item in protected_queries:
        q=item.query.strip(); reason=item.reason.strip()
        if not q or not reason:
            raise ValueError("each protected query requires query and reason")
        key=" ".join(q.casefold().split())
        if key in seen_protected:
            raise ValueError(f"duplicate protected query: {q}")
        seen_protected.add(key)
        protected_rows.append({
            "query": q, "reason": reason,
            "basis": confirmed_basis(actor=actor, now=moment, note="Protected query confirmed in Business Truth"),
        })

    return {
        "business_id": business_id,
        "business_name": business_name.strip(),
        "version": version,
        "created_at": moment.isoformat(),
        "created_by": actor,
        "offer_catalog_completeness": "complete" if catalog_complete else "partial",
        "audience_catalog_completeness": "unknown",
        "offers": offer_rows,
        "explicit_non_offers": non_offer_rows,
        "intent_policies": intent_rows,
        "audience_policies": audience_rows,
        "geo_policy": geo_policy,
        "outcomes": outcomes,
        "protected_queries": protected_rows,
        "evidence": [],
        "schema_version": 1,
        "supersedes_version": version - 1 if version > 1 else None,
    }
