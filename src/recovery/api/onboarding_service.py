from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from recovery.api.auth import Principal
from recovery.api.idempotency import validate_idempotency_key
from recovery.api.jobs import JobReceipt, JobType
from recovery.api.policy import AuthorizationError, Permission, TenantAccess
from recovery.api.repository import ApiConflict, ApiNotFound, ApiRepository
from recovery.api.billing_service import BillingApplicationService
from recovery.business_truth import BusinessTruthSnapshot
from recovery.db.canonical import canonical_json_text
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.google_ads.auth import UserOAuthConfig, build_user_oauth_client
from recovery.google_ads.discovery import DiscoveredGoogleAdsAccount, GoogleAdsAccountDiscovery
from recovery.launch_control import LaunchMode, derive_launch_access, launch_email_sha256
from recovery.signup_abuse import SignupAbuseVerificationError, TurnstileVerification, TurnstileVerifier
from recovery.onboarding import (
    CredentialVault,
    GoogleOAuthProvider,
    GuidedGeoAreaInput,
    GuidedNonOfferInput,
    GuidedOfferInput,
    GuidedAudienceInput,
    GuidedProtectedQueryInput,
    OnboardingStep,
    build_guided_business_truth_payload,
)
from .business_truth_io import parse_business_truth_payload


class OnboardingNotConfigured(RuntimeError):
    pass


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_text(payload).encode("utf-8")).hexdigest()


def normalize_org_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    slug = slug[:64].strip("-")
    if len(slug) < 3:
        slug = f"org-{hashlib.sha256(value.encode()).hexdigest()[:8]}"
    return slug


@dataclass(frozen=True, slots=True)
class OAuthConnectionRuntime:
    provider: GoogleOAuthProvider
    vault: CredentialVault


class PostgresOnboardingStore:
    def __init__(self, core: PostgresRecoveryRepository, *, public_workspace_max_per_user_24h: int = 1) -> None:
        self.core = core
        if public_workspace_max_per_user_24h < 1 or public_workspace_max_per_user_24h > 20:
            raise ValueError("public workspace creation limit must be between 1 and 20 per user per 24 hours")
        self.public_workspace_max_per_user_24h = public_workspace_max_per_user_24h

    def _connect(self):
        return self.core._connect()

    @staticmethod
    def _set_user(cur: Any, user_id: UUID) -> None:
        cur.execute("SELECT set_config('recovery.user_id', %s, true)", (str(user_id),))

    @staticmethod
    def organization_request_payload(*, display_name: str, slug: str, legal_acceptance_confirmed: bool,
                                     accepted_terms_version: str | None, accepted_privacy_version: str | None) -> dict[str, Any]:
        return {"display_name": display_name.strip(), "slug": slug,
                "legal_acceptance_confirmed": bool(legal_acceptance_confirmed),
                "accepted_terms_version": accepted_terms_version,
                "accepted_privacy_version": accepted_privacy_version}

    def current_launch_mode(self, *, user_id: UUID) -> LaunchMode:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id)
            cur.execute("SELECT launch_mode FROM recovery.platform_launch_events ORDER BY occurred_at DESC,id DESC LIMIT 1")
            row=cur.fetchone()
            return LaunchMode(str(row["launch_mode"])) if row else LaunchMode.CLOSED

    def organization_request_replay(self, *, principal: Principal, display_name: str, slug: str, idempotency_key: str,
                                    legal_acceptance_confirmed: bool, accepted_terms_version: str | None, accepted_privacy_version: str | None) -> tuple[UUID,bool] | None:
        key=validate_idempotency_key(idempotency_key)
        payload=self.organization_request_payload(display_name=display_name,slug=slug,legal_acceptance_confirmed=legal_acceptance_confirmed,accepted_terms_version=accepted_terms_version,accepted_privacy_version=accepted_privacy_version)
        digest=_request_hash(payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,principal.user_id)
            cur.execute("SELECT request_sha256,tenant_id FROM recovery.onboarding_organization_requests WHERE user_id=%s AND idempotency_key=%s",(principal.user_id,key))
            row=cur.fetchone()
            if row is None:return None
            if row["request_sha256"]!=digest:raise ApiConflict("Idempotency-Key was already used with a different organization request")
            return UUID(str(row["tenant_id"])),True

    def create_organization(self, *, principal: Principal, display_name: str, slug: str,
                            idempotency_key: str, legal_acceptance_confirmed: bool = False,
                            accepted_terms_version: str | None = None,
                            accepted_privacy_version: str | None = None,
                            required_terms_url: str | None = None,
                            required_terms_version: str | None = None,
                            required_privacy_url: str | None = None,
                            required_privacy_version: str | None = None,
                            public_abuse_verified: bool = False,
                            public_abuse_evidence: TurnstileVerification | None = None) -> tuple[UUID, bool]:
        key = validate_idempotency_key(idempotency_key)
        if (required_terms_version or required_privacy_version) and not legal_acceptance_confirmed:
            raise ApiConflict("explicit Terms and Privacy acceptance is required before workspace creation")
        if required_terms_version and accepted_terms_version != required_terms_version:
            raise ApiConflict("current Terms of Service must be accepted before workspace creation")
        if required_privacy_version and accepted_privacy_version != required_privacy_version:
            raise ApiConflict("current Privacy Policy must be accepted before workspace creation")
        payload = self.organization_request_payload(display_name=display_name,slug=slug,legal_acceptance_confirmed=legal_acceptance_confirmed,accepted_terms_version=accepted_terms_version,accepted_privacy_version=accepted_privacy_version)
        digest = _request_hash(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_user(cur, principal.user_id)
                self.core._advisory_xact_lock(cur, f"org-create:{principal.user_id}:{key}")
                cur.execute(
                    "SELECT request_sha256,tenant_id FROM recovery.onboarding_organization_requests WHERE user_id=%s AND idempotency_key=%s",
                    (principal.user_id, key),
                )
                prior = cur.fetchone()
                if prior is not None:
                    if prior["request_sha256"] != digest:
                        raise ApiConflict("Idempotency-Key was already used with a different organization request")
                    return UUID(str(prior["tenant_id"])), True

                # Epic 14 launch boundary. Auth accounts may exist before public launch, but
                # creating a customer workspace fails closed unless public launch is open or
                # this email has an active pilot/invite grant. Existing idempotent creations
                # above remain replayable even after launch mode later closes.
                cur.execute("SELECT launch_mode FROM recovery.platform_launch_events ORDER BY occurred_at DESC,id DESC LIMIT 1")
                launch=cur.fetchone(); mode=LaunchMode(str(launch["launch_mode"])) if launch else LaunchMode.CLOSED
                if mode is not LaunchMode.CLOSED and not all((required_terms_url,required_terms_version,required_privacy_url,required_privacy_version)):
                    raise ApiConflict("workspace creation is blocked until current HTTPS Terms and Privacy policies and version identifiers are configured")
                if mode is LaunchMode.PUBLIC:
                    if not public_abuse_verified or public_abuse_evidence is None:
                        raise ApiConflict("public workspace creation requires a verified anti-abuse challenge")
                    # Serialize the per-user rate boundary independently of the request-key lock so
                    # concurrent distinct workspace requests cannot both pass the same count check.
                    self.core._advisory_xact_lock(cur,f"public-org-rate:{principal.user_id}")
                    cur.execute("SELECT count(*)::int AS n FROM recovery.onboarding_organization_requests WHERE user_id=%s AND created_at>now()-interval '24 hours'",(principal.user_id,))
                    if int(cur.fetchone()["n"])>=self.public_workspace_max_per_user_24h:
                        raise ApiConflict("public workspace creation rate limit exceeded; try again after the 24-hour window")
                else:
                    if mode is LaunchMode.CLOSED or not principal.email:
                        raise ApiConflict("new Recovery OS workspaces are not open in the current launch mode")
                    email_digest=launch_email_sha256(principal.email)
                    cur.execute("SELECT id,event_type,expires_at,subject_hint,occurred_at FROM recovery.platform_launch_access_events WHERE subject_email_sha256=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(email_digest,))
                    grant=cur.fetchone(); access=derive_launch_access([dict(grant)] if grant else [])
                    if not access.allowed:
                        raise ApiConflict("this account is not currently granted workspace-creation access")
                try:
                    cur.execute(
                        "SELECT recovery_private.create_organization_for_current_user(%s,%s) AS tenant_id",
                        (display_name.strip(), slug),
                    )
                    tenant_id = UUID(str(cur.fetchone()["tenant_id"]))
                except Exception as exc:
                    if getattr(exc, "sqlstate", None) == "23505":
                        raise ApiConflict("organization slug is already in use") from exc
                    raise
                cur.execute(
                    "INSERT INTO recovery.onboarding_organization_requests(user_id,idempotency_key,request_sha256,tenant_id) VALUES (%s,%s,%s,%s)",
                    (principal.user_id, key, digest, tenant_id),
                )
                cur.execute(
                    "INSERT INTO recovery.onboarding_progress(tenant_id,owner_user_id,current_step,completed_steps) VALUES (%s,%s,'billing','[\"organization\"]'::jsonb)",
                    (tenant_id, principal.user_id),
                )
                if required_terms_url and required_terms_version and required_privacy_url and required_privacy_version:
                    # Legal acceptance is evidence, not a mutable user-profile flag. It is
                    # committed in the same transaction as workspace creation so there is no
                    # state where a customer workspace exists without the acceptance that
                    # authorized this creation boundary.
                    cur.execute(
                        """INSERT INTO recovery.user_legal_acceptance_events(
                               user_id,tenant_id,terms_url,terms_version,privacy_url,privacy_version,source,accepted_at
                           ) VALUES (%s,%s,%s,%s,%s,%s,'workspace_creation',now())""",
                        (principal.user_id,tenant_id,required_terms_url,required_terms_version,required_privacy_url,required_privacy_version),
                    )
                if mode is LaunchMode.PUBLIC and public_abuse_evidence is not None:
                    cur.execute(
                        """INSERT INTO recovery.workspace_creation_abuse_events(
                               user_id,tenant_id,request_sha256,provider,hostname,action,challenge_ts
                           ) VALUES (%s,%s,%s,'cloudflare_turnstile',%s,%s,%s)""",
                        (principal.user_id,tenant_id,digest,public_abuse_evidence.hostname,public_abuse_evidence.action,public_abuse_evidence.challenge_ts),
                    )
                return tenant_id, False

    def save_oauth_state(self, *, tenant_id: UUID, user_id: UUID, state_sha256: str,
                         return_path: str, ttl_minutes: int = 10) -> None:
        if ttl_minutes < 1 or ttl_minutes > 30:
            raise ValueError("OAuth state TTL must be between 1 and 30 minutes")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO recovery.google_oauth_authorization_states(
                    tenant_id,user_id,state_sha256,return_path,expires_at
                ) VALUES (%s,%s,%s,%s,now()+(%s || ' minutes')::interval)
                """,
                (tenant_id, user_id, state_sha256, return_path, ttl_minutes),
            )

    def consume_oauth_state(self, *, user_id: UUID, state_sha256: str) -> tuple[UUID, str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_user(cur, user_id)
                cur.execute(
                    """
                    SELECT tenant_id,return_path
                    FROM recovery.google_oauth_authorization_states
                    WHERE user_id=%s AND state_sha256=%s AND consumed_at IS NULL AND expires_at>now()
                    FOR UPDATE
                    """,
                    (user_id, state_sha256),
                )
                row = cur.fetchone()
                if row is None:
                    raise ApiConflict("Google OAuth state is invalid, expired, or already used")
                tenant_id = UUID(str(row["tenant_id"]))
                self.core._set_tenant(cur, tenant_id)
                cur.execute(
                    "UPDATE recovery.google_oauth_authorization_states SET consumed_at=now() WHERE user_id=%s AND state_sha256=%s",
                    (user_id, state_sha256),
                )
                return tenant_id, str(row["return_path"])

    def save_oauth_connection(self, *, tenant_id: UUID, user_id: UUID, secret_ref: str,
                              refresh_token_sha256: str, granted_scopes: tuple[str, ...]) -> UUID:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            # Reauthorizing creates a new immutable credential reference and revokes active
            # predecessor rows. Historical account bindings remain auditable.
            cur.execute(
                "UPDATE recovery.google_oauth_connections SET status='revoked',revoked_at=now() WHERE tenant_id=%s AND connected_by=%s AND status='connected'",
                (tenant_id,user_id),
            )
            cur.execute(
                """
                INSERT INTO recovery.google_oauth_connections(
                    tenant_id,connected_by,status,refresh_token_secret_ref,refresh_token_sha256,
                    granted_scopes,last_verified_at
                ) VALUES (%s,%s,'connected',%s,%s,%s,now()) RETURNING id
                """,
                (tenant_id, user_id, secret_ref, refresh_token_sha256, list(granted_scopes)),
            )
            return UUID(str(cur.fetchone()["id"]))

    def connection(self, *, tenant_id: UUID, connection_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                "SELECT id,status,refresh_token_secret_ref,refresh_token_sha256,connected_by FROM recovery.google_oauth_connections WHERE tenant_id=%s AND id=%s",
                (tenant_id, connection_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ApiNotFound("Google OAuth connection not found")
            return dict(row)

    def replace_discovered_accounts(self, *, tenant_id: UUID, connection_id: UUID,
                                    accounts: tuple[DiscoveredGoogleAdsAccount, ...]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self.core._set_tenant(cur, tenant_id)
                cur.execute(
                    "SELECT 1 FROM recovery.google_oauth_connections WHERE tenant_id=%s AND id=%s AND status='connected'",
                    (tenant_id, connection_id),
                )
                if cur.fetchone() is None:
                    raise ApiNotFound("active Google OAuth connection not found")
                for a in accounts:
                    cur.execute(
                        """
                        INSERT INTO recovery.google_ads_discovered_accounts(
                            tenant_id,connection_id,customer_id,descriptive_name,currency_code,time_zone,
                            manager,account_status,test_account,direct_access,login_customer_id,hierarchy_level,last_seen_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                        ON CONFLICT (tenant_id,connection_id,customer_id) DO UPDATE SET
                            descriptive_name=EXCLUDED.descriptive_name,currency_code=EXCLUDED.currency_code,
                            time_zone=EXCLUDED.time_zone,manager=EXCLUDED.manager,account_status=EXCLUDED.account_status,
                            test_account=EXCLUDED.test_account,direct_access=EXCLUDED.direct_access,
                            login_customer_id=EXCLUDED.login_customer_id,hierarchy_level=EXCLUDED.hierarchy_level,last_seen_at=now()
                        """,
                        (
                            tenant_id, connection_id, a.customer_id, a.descriptive_name, a.currency_code,
                            a.time_zone, a.manager, a.account_status, a.test_account, a.direct_access,
                            a.login_customer_id, a.hierarchy_level,
                        ),
                    )
                cur.execute(
                    "UPDATE recovery.onboarding_progress SET current_step='account_selection',updated_at=now(),completed_steps=CASE WHEN completed_steps ? 'google_ads' THEN completed_steps ELSE completed_steps || '[\"google_ads\"]'::jsonb END WHERE tenant_id=%s",
                    (tenant_id,),
                )

    def list_discovered_accounts(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                WITH ranked AS (
                    SELECT d.id,d.connection_id,d.customer_id,d.descriptive_name,d.currency_code,d.time_zone,
                           d.manager,d.account_status,d.test_account,d.direct_access,d.login_customer_id,
                           d.hierarchy_level,d.selected_at,
                           row_number() OVER (
                               PARTITION BY d.customer_id
                               ORDER BY d.direct_access DESC,d.hierarchy_level ASC,c.connected_at DESC,d.id
                           ) AS rn
                    FROM recovery.google_ads_discovered_accounts d
                    JOIN recovery.google_oauth_connections c ON c.tenant_id=d.tenant_id AND c.id=d.connection_id
                    WHERE d.tenant_id=%s AND c.status='connected'
                )
                SELECT id,connection_id,customer_id,descriptive_name,currency_code,time_zone,manager,
                       account_status,test_account,direct_access,login_customer_id,hierarchy_level,selected_at
                FROM ranked WHERE rn=1
                ORDER BY manager,descriptive_name,customer_id
                """,
                (tenant_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def materialize_selected_accounts(self, *, tenant_id: UUID, user_id: UUID,
                                      customer_ids: tuple[str, ...],
                                      max_accounts: int | None = None) -> list[dict[str, Any]]:
        wanted = tuple(dict.fromkeys(customer_ids))
        if not wanted:
            raise ValueError("select at least one non-manager Google Ads account")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_user(cur, user_id)
                self.core._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    WITH ranked AS (
                        SELECT d.*,c.status AS connection_status,
                               row_number() OVER (
                                   PARTITION BY d.customer_id
                                   ORDER BY d.direct_access DESC,d.hierarchy_level ASC,c.connected_at DESC,d.id
                               ) AS rn
                        FROM recovery.google_ads_discovered_accounts d
                        JOIN recovery.google_oauth_connections c ON c.tenant_id=d.tenant_id AND c.id=d.connection_id
                        WHERE d.tenant_id=%s AND d.customer_id=ANY(%s) AND c.status='connected'
                    )
                    SELECT * FROM ranked WHERE rn=1
                    """,
                    (tenant_id, list(wanted)),
                )
                rows = {str(r["customer_id"]): r for r in cur.fetchall()}
                missing = sorted(set(wanted)-set(rows))
                if missing:
                    raise ApiNotFound("one or more selected Google Ads accounts are no longer available")
                if any(bool(rows[cid]["manager"]) for cid in wanted):
                    raise ValueError("manager accounts cannot be selected for Search recovery analysis")
                if max_accounts is not None:
                    if max_accounts <= 0:
                        raise ValueError("max_accounts must be positive")
                    self.core._advisory_xact_lock(cur, f"billing-slots:{tenant_id}")
                    cur.execute(
                        """
                        SELECT a.customer_id
                        FROM recovery.billing_account_slots s
                        JOIN recovery.google_ads_accounts a
                          ON a.tenant_id=s.tenant_id AND a.id=s.account_id
                        WHERE s.tenant_id=%s
                        """,
                        (tenant_id,),
                    )
                    already_slotted={str(x["customer_id"]) for x in cur.fetchall()}
                    needed=[cid for cid in wanted if cid not in already_slotted]
                    if len(already_slotted)+len(needed)>max_accounts:
                        raise ApiConflict(
                            f"billing plan allows at most {max_accounts} Google Ads account(s)"
                        )
                result=[]
                for cid in wanted:
                    r=rows[cid]
                    cur.execute(
                        """
                        INSERT INTO recovery.google_ads_accounts(
                            tenant_id,customer_id,descriptive_name,currency_code,time_zone,manager,account_status,test_account,
                            credential_ref,credential_fingerprint
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (tenant_id,customer_id) DO UPDATE SET
                            descriptive_name=EXCLUDED.descriptive_name,currency_code=EXCLUDED.currency_code,
                            time_zone=EXCLUDED.time_zone,manager=EXCLUDED.manager,account_status=EXCLUDED.account_status,
                            test_account=EXCLUDED.test_account,credential_ref=EXCLUDED.credential_ref,
                            credential_fingerprint=EXCLUDED.credential_fingerprint,updated_at=now()
                        RETURNING id,customer_id,descriptive_name,currency_code,time_zone,account_status,test_account
                        """,
                        (
                            tenant_id,cid,r["descriptive_name"],r["currency_code"],r["time_zone"],False,
                            r["account_status"],r["test_account"],f"oauth-connection:{r['connection_id']}",None,
                        ),
                    )
                    account=dict(cur.fetchone())
                    if max_accounts is not None:
                        cur.execute(
                            "INSERT INTO recovery.billing_account_slots(tenant_id,account_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (tenant_id, account["id"]),
                        )
                    cur.execute(
                        """
                        INSERT INTO recovery.google_ads_account_connections(
                            tenant_id,account_id,oauth_connection_id,login_customer_id,status,connected_by
                        ) VALUES (%s,%s,%s,%s,'active',%s)
                        ON CONFLICT (tenant_id,account_id) DO UPDATE SET
                            oauth_connection_id=EXCLUDED.oauth_connection_id,login_customer_id=EXCLUDED.login_customer_id,
                            status='active',connected_by=EXCLUDED.connected_by,updated_at=now()
                        """,
                        (tenant_id,account["id"],r["connection_id"],r["login_customer_id"],user_id),
                    )
                    cur.execute(
                        "UPDATE recovery.google_ads_discovered_accounts SET selected_at=COALESCE(selected_at,now()) WHERE tenant_id=%s AND id=%s",
                        (tenant_id,r["id"]),
                    )
                    result.append(account)
                cur.execute(
                    "UPDATE recovery.onboarding_progress SET current_step='business_truth',updated_at=now(),completed_steps=CASE WHEN completed_steps ? 'account_selection' THEN completed_steps ELSE completed_steps || '[\"account_selection\"]'::jsonb END WHERE tenant_id=%s",
                    (tenant_id,),
                )
                return result

    def next_truth_version(self, *, tenant_id: UUID, account_id: UUID) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                "SELECT COALESCE(max(version),0)::int+1 AS n FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s",
                (tenant_id,account_id),
            )
            return int(cur.fetchone()["n"])

    def save_truth_draft(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID, draft: dict[str, Any]) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """INSERT INTO recovery.onboarding_business_truth_drafts(tenant_id,account_id,draft,updated_by)
                   VALUES (%s,%s,%s::jsonb,%s)
                   ON CONFLICT (tenant_id,account_id) DO UPDATE SET draft=EXCLUDED.draft,updated_by=EXCLUDED.updated_by,updated_at=now()""",
                (tenant_id,account_id,json.dumps(draft),user_id),
            )

    def set_measurement_profile(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID,
                                conversion_lag_days: int) -> None:
        if conversion_lag_days<0 or conversion_lag_days>365:
            raise ValueError("conversion_lag_days must be between 0 and 365")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """INSERT INTO recovery.account_measurement_profiles(tenant_id,account_id,conversion_lag_days,configured_by)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,account_id) DO UPDATE SET conversion_lag_days=EXCLUDED.conversion_lag_days,configured_by=EXCLUDED.configured_by,updated_at=now()""",
                (tenant_id,account_id,conversion_lag_days,user_id),
            )
            cur.execute(
                "UPDATE recovery.onboarding_progress SET current_step='first_sync',updated_at=now(),completed_steps=(CASE WHEN completed_steps ? 'business_truth' THEN completed_steps ELSE completed_steps || '[\"business_truth\"]'::jsonb END) || (CASE WHEN completed_steps ? 'measurement' THEN '[]'::jsonb ELSE '[\"measurement\"]'::jsonb END) WHERE tenant_id=%s",
                (tenant_id,),
            )

    def measurement_profile(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT conversion_lag_days,configured_at,updated_at FROM recovery.account_measurement_profiles WHERE tenant_id=%s AND account_id=%s",(tenant_id,account_id))
            row=cur.fetchone(); return dict(row) if row else None

    def onboarding_status(self, *, tenant_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT current_step,completed_steps,started_at,updated_at,completed_at FROM recovery.onboarding_progress WHERE tenant_id=%s",(tenant_id,))
            progress=cur.fetchone()
            if progress is None:
                raise ApiNotFound("onboarding state not found")
            cur.execute("SELECT count(*)::int AS n FROM recovery.google_oauth_connections WHERE tenant_id=%s AND status='connected'",(tenant_id,)); connections=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.google_ads_accounts WHERE tenant_id=%s AND manager=FALSE",(tenant_id,)); accounts=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.business_truth_snapshots WHERE tenant_id=%s",(tenant_id,)); truths=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.account_measurement_profiles WHERE tenant_id=%s",(tenant_id,)); measurement=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.sync_runs WHERE tenant_id=%s AND status='completed'",(tenant_id,)); syncs=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.analysis_runs WHERE tenant_id=%s AND status='completed'",(tenant_id,)); analyses=int(cur.fetchone()["n"])
            cur.execute("SELECT count(*)::int AS n FROM recovery.analysis_artifacts WHERE tenant_id=%s AND artifact_kind='negative_keyword_proposal'",(tenant_id,)); proposals=int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT a.id,a.customer_id,a.descriptive_name,a.currency_code,
                       EXISTS(SELECT 1 FROM recovery.business_truth_snapshots b WHERE b.tenant_id=a.tenant_id AND b.account_id=a.id) AS business_truth_ready,
                       EXISTS(SELECT 1 FROM recovery.account_measurement_profiles m WHERE m.tenant_id=a.tenant_id AND m.account_id=a.id) AS measurement_ready,
                       EXISTS(SELECT 1 FROM recovery.sync_runs s WHERE s.tenant_id=a.tenant_id AND s.account_id=a.id AND s.status='completed') AS sync_ready,
                       EXISTS(SELECT 1 FROM recovery.analysis_runs r WHERE r.tenant_id=a.tenant_id AND r.account_id=a.id AND r.status='completed') AS analysis_ready
                FROM recovery.google_ads_accounts a
                WHERE a.tenant_id=%s AND a.manager=FALSE
                ORDER BY a.descriptive_name,a.customer_id
                """,
                (tenant_id,),
            )
            account_activation=[dict(r) for r in cur.fetchall()]
            return {
                **dict(progress),"connected_google_users":connections,"selected_accounts":accounts,
                "truth_snapshots":truths,"measurement_profiles":measurement,"completed_syncs":syncs,
                "completed_analyses":analyses,"proposal_count":proposals,
                "account_activation":account_activation,
            }

    def mark_first_value(self, *, tenant_id: UUID) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """UPDATE recovery.onboarding_progress SET current_step='complete',completed_at=COALESCE(completed_at,now()),updated_at=now(),
                   completed_steps=completed_steps || (CASE WHEN completed_steps ? 'first_sync' THEN '[]'::jsonb ELSE '[\"first_sync\"]'::jsonb END) || (CASE WHEN completed_steps ? 'first_analysis' THEN '[]'::jsonb ELSE '[\"first_analysis\"]'::jsonb END) || (CASE WHEN completed_steps ? 'first_value' THEN '[]'::jsonb ELSE '[\"first_value\"]'::jsonb END) || (CASE WHEN completed_steps ? 'complete' THEN '[]'::jsonb ELSE '[\"complete\"]'::jsonb END)
                   WHERE tenant_id=%s""",
                (tenant_id,),
            )


class OnboardingApplicationService:
    def __init__(self, *, store: PostgresOnboardingStore, api_repository: ApiRepository,
                 oauth: OAuthConnectionRuntime | None,
                 billing: BillingApplicationService | None = None,
                 terms_url: str | None = None, terms_version: str | None = None,
                 privacy_url: str | None = None, privacy_version: str | None = None,
                 signup_abuse_verifier: TurnstileVerifier | None = None) -> None:
        self.store=store; self.repo=api_repository; self.oauth=oauth; self.billing=billing; self.signup_abuse_verifier=signup_abuse_verifier
        self.terms_url=(terms_url or "").strip() or None
        self.terms_version=(terms_version or "").strip() or None
        self.privacy_url=(privacy_url or "").strip() or None
        self.privacy_version=(privacy_version or "").strip() or None
        legal=(self.terms_url,self.terms_version,self.privacy_url,self.privacy_version)
        if any(legal) and not all(legal):
            raise ValueError("Terms and Privacy URLs and version identifiers must be configured together")
        if self.terms_url and (not self.terms_url.startswith("https://") or not self.privacy_url.startswith("https://")):
            raise ValueError("Terms and Privacy URLs must use HTTPS")

    def create_organization(self, *, principal: Principal, display_name: str, slug: str | None,
                            idempotency_key: str, legal_acceptance_confirmed: bool = False,
                            accepted_terms_version: str | None = None,
                            accepted_privacy_version: str | None = None,
                            turnstile_token: str | None = None) -> tuple[UUID,bool]:
        org_slug=normalize_org_slug(slug or display_name)
        replay_lookup=getattr(self.store,"organization_request_replay",None)
        if callable(replay_lookup):
            replay=replay_lookup(principal=principal,display_name=display_name,slug=org_slug,idempotency_key=idempotency_key,legal_acceptance_confirmed=legal_acceptance_confirmed,accepted_terms_version=accepted_terms_version,accepted_privacy_version=accepted_privacy_version)
            if replay is not None:return replay
        abuse_verified=False; abuse_evidence=None
        mode_lookup=getattr(self.store,"current_launch_mode",None)
        current_mode=mode_lookup(user_id=principal.user_id) if callable(mode_lookup) else None
        if current_mode is LaunchMode.PUBLIC:
            if self.signup_abuse_verifier is None:
                raise ApiConflict("public workspace creation is unavailable until anti-abuse verification is configured")
            token=(turnstile_token or "").strip()
            request_key=validate_idempotency_key(idempotency_key)
            verify_id=uuid5(NAMESPACE_URL,f"recovery-os:workspace-create:{principal.user_id}:{request_key}:{org_slug}")
            try:abuse_evidence=self.signup_abuse_verifier.verify(token=token,idempotency_key=verify_id)
            except SignupAbuseVerificationError as exc:raise ApiConflict(str(exc)) from exc
            abuse_verified=True
        return self.store.create_organization(
            principal=principal,display_name=display_name,slug=org_slug,idempotency_key=idempotency_key,
            legal_acceptance_confirmed=legal_acceptance_confirmed,
            accepted_terms_version=accepted_terms_version,accepted_privacy_version=accepted_privacy_version,
            required_terms_url=self.terms_url,required_terms_version=self.terms_version,
            required_privacy_url=self.privacy_url,required_privacy_version=self.privacy_version,
            public_abuse_verified=abuse_verified,public_abuse_evidence=abuse_evidence,
        )

    def begin_google_oauth(self, *, access: TenantAccess, login_hint: str | None, return_path: str) -> str:
        access.require(Permission.ONBOARDING_MANAGE)
        if self.oauth is None: raise OnboardingNotConfigured("Google Ads OAuth is not configured")
        state=self.oauth.provider.new_state_token()
        self.store.save_oauth_state(tenant_id=access.tenant_id,user_id=access.principal.user_id,state_sha256=self.oauth.provider.state_sha256(state),return_path=return_path)
        return self.oauth.provider.authorization_url(state=state,login_hint=login_hint)

    def complete_google_oauth(self, *, principal: Principal, code: str, state: str, endpoint: str) -> tuple[UUID,UUID,JobReceipt,str]:
        if self.oauth is None: raise OnboardingNotConfigured("Google Ads OAuth is not configured")
        tenant_id,return_path=self.store.consume_oauth_state(user_id=principal.user_id,state_sha256=self.oauth.provider.state_sha256(state))
        membership=self.repo.membership(user_id=principal.user_id,tenant_id=tenant_id)
        if membership is None or membership.role.value not in {"owner","admin"}: raise AuthorizationError("Google Ads onboarding requires owner or admin access")
        tokens=self.oauth.provider.exchange_code(code=code)
        secret_ref=self.oauth.vault.put_refresh_token(secret_name=f"recovery-google-ads-{tenant_id}-{uuid4()}",refresh_token=tokens.refresh_token)
        connection_id=self.store.save_oauth_connection(tenant_id=tenant_id,user_id=principal.user_id,secret_ref=secret_ref,refresh_token_sha256=tokens.refresh_token_sha256,granted_scopes=tuple(tokens.scope.split()))
        receipt=self.repo.enqueue_job(tenant_id=tenant_id,user_id=principal.user_id,endpoint=endpoint,idempotency_key=f"oauth-discovery-{connection_id}",job_type=JobType.GOOGLE_ADS_ACCOUNT_DISCOVERY,payload={"connection_id":str(connection_id)},operation_key=f"oauth-discovery:{connection_id}")
        return tenant_id,connection_id,receipt,return_path

    def status(self, *, access: TenantAccess) -> dict[str, Any]:
        access.require(Permission.TENANT_READ)
        return self.store.onboarding_status(tenant_id=access.tenant_id)

    def discovered_accounts(self, *, access: TenantAccess) -> list[dict[str, Any]]:
        access.require(Permission.ONBOARDING_MANAGE)
        return self.store.list_discovered_accounts(tenant_id=access.tenant_id)

    def select_accounts(self, *, access: TenantAccess, customer_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        access.require(Permission.ONBOARDING_MANAGE)
        max_accounts = self.billing.account_selection_limit(access=access) if self.billing is not None else None
        return self.store.materialize_selected_accounts(
            tenant_id=access.tenant_id,user_id=access.principal.user_id,customer_ids=customer_ids,
            max_accounts=max_accounts,
        )

    def set_measurement(self, *, access: TenantAccess, account_id: UUID, conversion_lag_days: int) -> dict[str, Any]:
        access.require(Permission.ONBOARDING_MANAGE)
        self.repo.ensure_account(tenant_id=access.tenant_id,account_id=account_id)
        self.store.set_measurement_profile(
            tenant_id=access.tenant_id,account_id=account_id,user_id=access.principal.user_id,
            conversion_lag_days=conversion_lag_days,
        )
        return self.store.measurement_profile(tenant_id=access.tenant_id,account_id=account_id) or {
            "conversion_lag_days":conversion_lag_days,"configured_at":None,"updated_at":None
        }

    def measurement(self, *, access: TenantAccess, account_id: UUID) -> dict[str, Any] | None:
        access.require(Permission.TENANT_READ)
        self.repo.ensure_account(tenant_id=access.tenant_id,account_id=account_id)
        return self.store.measurement_profile(tenant_id=access.tenant_id,account_id=account_id)

    def complete(self, *, access: TenantAccess) -> None:
        access.require(Permission.ONBOARDING_MANAGE)
        state=self.store.onboarding_status(tenant_id=access.tenant_id)
        if state["completed_analyses"] < 1:
            raise ApiConflict("onboarding cannot complete before the first analysis succeeds")
        self.store.mark_first_value(tenant_id=access.tenant_id)

    def guided_business_truth(self, *, access: TenantAccess, account_id: UUID, data: dict[str, Any],
                              idempotency_key: str, endpoint: str) -> tuple[UUID,str,int,bool]:
        access.require(Permission.BUSINESS_TRUTH_WRITE)
        self.repo.ensure_account(tenant_id=access.tenant_id,account_id=account_id)
        version=self.store.next_truth_version(tenant_id=access.tenant_id,account_id=account_id)
        payload=build_guided_business_truth_payload(
            business_id=str(data.get("business_id") or account_id), business_name=str(data["business_name"]),
            version=version, actor=access.actor_id,
            offers=tuple(GuidedOfferInput(name=str(x["name"]),description=str(x["description"]),aliases=tuple(x.get("aliases",()))) for x in data.get("offers",())),
            non_offers=tuple(GuidedNonOfferInput(name=str(x["name"]),reason=str(x["reason"]),aliases=tuple(x.get("aliases",()))) for x in data.get("non_offers",())),
            service_areas=tuple(GuidedGeoAreaInput(display_name=str(x["display_name"]),country_code=str(x["country_code"]),region=x.get("region"),city=x.get("city"),postal_code=x.get("postal_code")) for x in data.get("service_areas",())),
            catalog_complete=bool(data.get("catalog_complete",False)), employment_policy=str(data.get("employment_policy","unknown")),
            free_policy=str(data.get("free_policy","unknown")), diy_policy=str(data.get("diy_policy","unknown")),
            primary_outcomes=tuple(str(x) for x in data.get("primary_outcomes",())),
            additional_intent_policies=tuple((str(k),str(v)) for k,v in dict(data.get("additional_intent_policies") or {}).items()),
            audience_policies=tuple(GuidedAudienceInput(name=str(x["name"]),disposition=str(x.get("disposition","unknown")),reason=str(x.get("reason") or "Business audience policy"),aliases=tuple(x.get("aliases",())),condition=x.get("condition")) for x in data.get("audience_policies",())),
            supporting_outcomes=tuple(str(x) for x in data.get("supporting_outcomes",())),
            invalid_outcomes=tuple(str(x) for x in data.get("invalid_outcomes",())),
            protected_queries=tuple(GuidedProtectedQueryInput(query=str(x["query"]),reason=str(x.get("reason") or "Business-protected query")) for x in data.get("protected_queries",())),
            geo_requirement=str(data.get("geo_requirement") or "destination_or_job_must_be_in_service_area"),
            geo_condition=str(data.get("geo_condition") or "") or None,
        )
        self.store.save_truth_draft(tenant_id=access.tenant_id,account_id=account_id,user_id=access.principal.user_id,draft=data)
        snapshot=parse_business_truth_payload(payload,submitted_by=access.actor_id)
        return self.repo.save_business_truth(tenant_id=access.tenant_id,account_id=account_id,user_id=access.principal.user_id,endpoint=endpoint,idempotency_key=validate_idempotency_key(idempotency_key),request_payload=payload,snapshot=snapshot)


class GoogleAdsAccountDiscoveryJobRunner:
    def __init__(self, *, store: PostgresOnboardingStore, vault: CredentialVault,
                 oauth_client_id: str, oauth_client_secret: str) -> None:
        self.store=store; self.vault=vault; self.client_id=oauth_client_id; self.client_secret=oauth_client_secret

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        connection_id=UUID(str(payload.get("connection_id") or ""))
        connection=self.store.connection(tenant_id=tenant_id,connection_id=connection_id)
        if connection["status"]!="connected": raise RuntimeError("Google OAuth connection is not active")
        refresh=self.vault.get_refresh_token(secret_ref=str(connection["refresh_token_secret_ref"]))
        client=build_user_oauth_client(UserOAuthConfig(client_id=self.client_id,client_secret=self.client_secret,refresh_token=refresh))
        accounts=GoogleAdsAccountDiscovery(client).discover()
        self.store.replace_discovered_accounts(tenant_id=tenant_id,connection_id=connection_id,accounts=accounts)
        return {"connection_id":str(connection_id),"discovered_accounts":len(accounts)}
