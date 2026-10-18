from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
from typing import Any, Protocol
from uuid import UUID

from recovery.db.canonical import canonical_payload
from recovery.api.jobs import JobType
from recovery.api.repository import PostgresApiRepository, ApiConflict
from recovery.accuracy import AccuracyPolicy
from recovery.recovery_ledger import ConfigurationVerification, RecoveryVerificationEngine
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.db.sync_store import PostgresSyncStoreFactory
from recovery.google_ads.adapter import GOOGLE_ADS_API_VERSION, GoogleAdsV26Adapter
from recovery.google_ads.auth import (
    ServiceAccountConfig, UserOAuthConfig, build_service_account_client, build_user_oauth_client,
)
from recovery.google_ads.mutation import (
    GoogleAdsNegativeMutationExecutor,
    MutationReceipt,
    ValidationReceipt,
)
from recovery.google_ads.sync import GoogleAdsSyncEngine
from recovery.onboarding import CredentialVault
from recovery.negative_keywords import (
    ApprovalRecord,
    Collision,
    NegativeKeywordCandidate,
    NegativeKeywordProposal,
    NegativeMatchType,
    NegativeScope,
    ProposalDisposition,
    ProposalReason,
    ProposalReasonCode,
    ProposalRisk,
    build_mutation_plan,
)

from .domain import PermanentWorkerError


class GoogleAdsClientResolver(Protocol):
    def client_for(self, *, tenant_id: UUID, credential_ref: str | None, customer_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class EnvServiceAccountClientResolver:
    """Founder-operated V1 resolver using one manager/service account from env.

    Secrets remain outside PostgreSQL. `credential_ref` is metadata only. A later
    secret-manager resolver can implement the same protocol without changing workers.
    """
    developer_token_env: str = "GOOGLE_ADS_DEVELOPER_TOKEN"
    json_path_env: str = "GOOGLE_ADS_SERVICE_ACCOUNT_JSON"
    login_customer_env: str = "GOOGLE_ADS_LOGIN_CUSTOMER_ID"

    def client_for(self, *, tenant_id: UUID, credential_ref: str | None, customer_id: str) -> Any:
        token = os.environ.get(self.developer_token_env, "").strip()
        path = os.environ.get(self.json_path_env, "").strip()
        login = os.environ.get(self.login_customer_env, "").strip() or None
        if not path:
            raise PermanentWorkerError(
                "Google Ads service-account environment is not configured",
                code="GOOGLE_CREDENTIALS_MISSING",
            )
        return build_service_account_client(ServiceAccountConfig(
            json_key_file_path=path,
            developer_token=token or None,
            login_customer_id=login,
        ))


@dataclass(slots=True)
class PostgresOAuthAwareClientResolver:
    """Resolve the advertiser's own OAuth grant before any legacy service-account fallback.

    Self-serve accounts selected during Epic 2 are bound to an OAuth connection in
    PostgreSQL while the refresh token itself remains in a managed vault. A missing or
    revoked binding for an OAuth-backed account is a hard failure: silently falling back
    to a founder credential could cross an authorization boundary or use the wrong MCC.
    """

    core: PostgresRecoveryRepository
    oauth_client_id: str
    oauth_client_secret: str
    vault: CredentialVault
    fallback: GoogleAdsClientResolver | None = None

    def __post_init__(self) -> None:
        if not self.oauth_client_id.strip() or not self.oauth_client_secret.strip():
            raise ValueError("OAuth client ID and secret are required")

    def _oauth_binding(self, *, tenant_id: UUID, customer_id: str) -> dict[str, Any] | None:
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT a.credential_ref, ac.login_customer_id, ac.status AS account_connection_status,
                       oc.status AS oauth_status, oc.refresh_token_secret_ref
                FROM recovery.google_ads_accounts a
                LEFT JOIN recovery.google_ads_account_connections ac
                  ON ac.tenant_id=a.tenant_id AND ac.account_id=a.id
                LEFT JOIN recovery.google_oauth_connections oc
                  ON oc.tenant_id=ac.tenant_id AND oc.id=ac.oauth_connection_id
                WHERE a.tenant_id=%s AND a.customer_id=%s
                """,
                (tenant_id, customer_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def client_for(self, *, tenant_id: UUID, credential_ref: str | None, customer_id: str) -> Any:
        row = self._oauth_binding(tenant_id=tenant_id, customer_id=customer_id)
        oauth_backed = bool((credential_ref or "").startswith("oauth-connection:"))
        if row and row.get("refresh_token_secret_ref"):
            if row.get("account_connection_status") != "active" or row.get("oauth_status") != "connected":
                raise PermanentWorkerError(
                    "Google Ads OAuth connection requires reauthorization",
                    code="GOOGLE_OAUTH_REAUTHORIZATION_REQUIRED",
                )
            try:
                refresh_token = self.vault.get_refresh_token(
                    secret_ref=str(row["refresh_token_secret_ref"])
                )
            except Exception as exc:
                raise PermanentWorkerError(
                    "Google Ads OAuth credential could not be loaded",
                    code="GOOGLE_OAUTH_SECRET_UNAVAILABLE",
                ) from exc
            return build_user_oauth_client(UserOAuthConfig(
                client_id=self.oauth_client_id,
                client_secret=self.oauth_client_secret,
                refresh_token=refresh_token,
                login_customer_id=str(row["login_customer_id"]) if row.get("login_customer_id") else None,
            ))
        if oauth_backed:
            raise PermanentWorkerError(
                "OAuth-backed Google Ads account has no active credential binding",
                code="GOOGLE_OAUTH_BINDING_MISSING",
            )
        if self.fallback is None:
            raise PermanentWorkerError(
                "Google Ads credentials are not configured for this account",
                code="GOOGLE_CREDENTIALS_MISSING",
            )
        return self.fallback.client_for(
            tenant_id=tenant_id, credential_ref=credential_ref, customer_id=customer_id
        )


@dataclass(slots=True)
class GoogleAdsSyncJobRunner:
    core: PostgresRecoveryRepository
    client_resolver: GoogleAdsClientResolver

    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            account_id = UUID(str(payload["account_id"]))
            start = date.fromisoformat(str(payload["start"]))
            end = date.fromisoformat(str(payload["end"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise PermanentWorkerError("invalid sync job payload", code="BAD_SYNC_PAYLOAD") from exc
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT id, customer_id, credential_ref, credential_fingerprint
                FROM recovery.google_ads_accounts
                WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, account_id),
            )
            row = cur.fetchone()
            if row is None:
                raise PermanentWorkerError("Google Ads account no longer exists", code="ACCOUNT_NOT_FOUND")
        client = self.client_resolver.client_for(
            tenant_id=tenant_id, credential_ref=row["credential_ref"], customer_id=row["customer_id"]
        )
        adapter = GoogleAdsV26Adapter.from_google_ads_client(client)
        engine = GoogleAdsSyncEngine(adapter)
        factory = PostgresSyncStoreFactory(
            repository=self.core,
            tenant_id=tenant_id,
            request_id=f"worker-job:{job_id}",
            credential_ref=row["credential_ref"],
            credential_fingerprint=row["credential_fingerprint"],
        )
        result = engine.sync(
            customer_id=row["customer_id"], start=start, end=end, store_factory=factory
        )
        # A successful provider sync schedules monitoring against the exact fresh
        # evidence. This is durable work, not a best-effort in-process callback.
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute("SELECT requested_by FROM recovery.api_jobs WHERE tenant_id=%s AND id=%s", (tenant_id, job_id))
            request_row=cur.fetchone()
        monitoring_job_id=None
        if request_row is not None:
            api=PostgresApiRepository(self.core)
            key=f"post-sync-monitor:{job_id}"
            try:
                receipt=api.enqueue_job(
                    tenant_id=tenant_id, user_id=request_row["requested_by"],
                    endpoint=f"/internal/post-sync/{job_id}/monitoring",
                    idempotency_key=key, job_type=JobType.MONITORING_EVALUATION,
                    payload={"account_id":str(account_id),"source_sync_job_id":str(job_id)},
                    operation_key=key,
                )
                monitoring_job_id=str(receipt.job_id)
            except ApiConflict:
                # Idempotent replay or a previously scheduled logical operation is safe.
                monitoring_job_id="already_scheduled"
        payload=canonical_payload(result)
        payload["monitoring_job_id"]=monitoring_job_id
        return payload

    def terminal_failure(self, job, exc: BaseException) -> None:
        self.core.fail_sync_run_by_request(
            tenant_id=job.tenant_id, request_id=f"worker-job:{job.job_id}",
            failure_code=str(getattr(exc, "code", None) or type(exc).__name__)[:120],
            failure_detail=str(exc),
        )


def parse_negative_keyword_proposal(payload: dict[str, Any]) -> NegativeKeywordProposal:
    try:
        c = payload["candidate"]
        candidate = NegativeKeywordCandidate(
            text=str(c["text"]), match_type=NegativeMatchType(str(c["match_type"])),
            scope=NegativeScope(str(c["scope"])), customer_id=str(c["customer_id"]),
            campaign_id=str(c["campaign_id"]) if c.get("campaign_id") is not None else None,
            ad_group_id=str(c["ad_group_id"]) if c.get("ad_group_id") is not None else None,
        )
        reasons = tuple(
            ProposalReason(
                code=ProposalReasonCode(str(r["code"])), message=str(r["message"]),
                decisive=bool(r["decisive"]),
            ) for r in payload.get("reasons", ())
        )
        protected = tuple(
            Collision(source=str(x["source"]), text=str(x["text"]), detail=str(x["detail"]))
            for x in payload.get("protected_query_collisions", ())
        )
        positive = tuple(
            Collision(source=str(x["source"]), text=str(x["text"]), detail=str(x["detail"]))
            for x in payload.get("positive_keyword_collisions", ())
        )
        return NegativeKeywordProposal(
            proposal_id=str(payload["proposal_id"]), candidate=candidate,
            truth_fingerprint=str(payload["truth_fingerprint"]),
            evidence_snapshot_id=str(payload["evidence_snapshot_id"]),
            evidence_observation_ids=tuple(str(x) for x in payload.get("evidence_observation_ids", ())),
            disposition=ProposalDisposition(str(payload["disposition"])),
            risk=ProposalRisk(str(payload["risk"])), reasons=reasons,
            protected_query_collisions=protected, positive_keyword_collisions=positive,
            existing_covering_negative_resource_names=tuple(
                str(x) for x in payload.get("existing_covering_negative_resource_names", ())
            ),
            potentially_avoidable_cost_micros=int(payload["potentially_avoidable_cost_micros"]),
            currency_code=str(payload["currency_code"]),
            schema_version=int(payload.get("schema_version", 1)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise PermanentWorkerError("stored negative proposal payload is invalid", code="BAD_STORED_PROPOSAL") from exc


@dataclass(frozen=True, slots=True)
class MutationContext:
    proposal_artifact_id: UUID
    proposal: NegativeKeywordProposal
    approval_event_id: UUID
    approval: ApprovalRecord
    credential_ref: str | None


@dataclass(slots=True)
class GoogleAdsNegativeMutationJobRunner:
    core: PostgresRecoveryRepository
    client_resolver: GoogleAdsClientResolver

    def _context(self, *, tenant_id: UUID, payload: dict[str, Any]) -> MutationContext:
        try:
            artifact_id = UUID(str(payload["proposal_artifact_id"]))
        except (KeyError, ValueError) as exc:
            raise PermanentWorkerError("missing/invalid proposal artifact", code="BAD_MUTATION_PAYLOAD") from exc
        approval_raw = payload.get("approval_event_id")
        applied_event_raw = payload.get("applied_mutation_event_id")
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT external_id, artifact_fingerprint, payload
                FROM recovery.analysis_artifacts
                WHERE tenant_id=%s AND id=%s AND artifact_kind='negative_keyword_proposal'
                """,
                (tenant_id, artifact_id),
            )
            a = cur.fetchone()
            if a is None:
                raise PermanentWorkerError("proposal artifact not found", code="PROPOSAL_NOT_FOUND")
            proposal = parse_negative_keyword_proposal(dict(a["payload"]))
            if proposal.proposal_id != a["external_id"] or proposal.fingerprint_sha256 != a["artifact_fingerprint"]:
                raise PermanentWorkerError("stored proposal fingerprint mismatch", code="PROPOSAL_INTEGRITY_FAILED")
            if payload.get("proposal_fingerprint") and payload["proposal_fingerprint"] != proposal.fingerprint_sha256:
                raise PermanentWorkerError("queued proposal fingerprint no longer matches", code="PROPOSAL_CHANGED")

            is_rollback = bool(applied_event_raw and not approval_raw)
            if not is_rollback:
                # Re-check evidence freshness at worker execution time. Approval and queueing are not
                # permission to apply an obsolete action after Business Truth or completed analysis changes.
                cur.execute(
                    """SELECT r.account_id,r.id AS analysis_run_id
                       FROM recovery.analysis_runs r
                       JOIN recovery.analysis_artifacts a ON a.tenant_id=r.tenant_id AND a.analysis_run_id=r.id
                       WHERE a.tenant_id=%s AND a.id=%s""",
                    (tenant_id,artifact_id),
                )
                source=cur.fetchone()
                if source is None:
                    raise PermanentWorkerError("proposal analysis source not found", code="PROPOSAL_SOURCE_MISSING")
                cur.execute(
                    """SELECT truth_fingerprint FROM recovery.business_truth_snapshots
                       WHERE tenant_id=%s AND account_id=%s
                       ORDER BY business_version DESC,created_at DESC,id DESC LIMIT 1""",
                    (tenant_id,source["account_id"]),
                )
                latest_truth=cur.fetchone()
                if latest_truth is None or str(latest_truth["truth_fingerprint"]) != proposal.truth_fingerprint:
                    raise PermanentWorkerError("proposal became stale after Business Truth changed", code="PROPOSAL_TRUTH_STALE")
                cur.execute(
                    """SELECT id FROM recovery.analysis_runs WHERE tenant_id=%s AND account_id=%s AND status='completed'
                       ORDER BY completed_at DESC NULLS LAST,started_at DESC,id DESC LIMIT 1""",
                    (tenant_id,source["account_id"]),
                )
                latest_analysis=cur.fetchone()
                if latest_analysis is None or latest_analysis["id"] != source["analysis_run_id"]:
                    raise PermanentWorkerError("proposal became stale after newer analysis", code="PROPOSAL_ANALYSIS_STALE")
                cur.execute(
                    """SELECT event_type FROM recovery.recovery_case_events
                       WHERE tenant_id=%s AND proposal_artifact_id=%s AND event_type IN ('closed','reopened')
                       ORDER BY occurred_at DESC,id DESC LIMIT 1""",
                    (tenant_id,artifact_id),
                )
                case_state=cur.fetchone()
                if case_state and case_state["event_type"] == "closed":
                    raise PermanentWorkerError("Recovery Case was closed before execution", code="CASE_CLOSED")
            if approval_raw:
                approval_id = UUID(str(approval_raw))
                cur.execute(
                    """
                    SELECT id, proposal_artifact_id, proposal_fingerprint, decision,
                           decided_by, decided_at
                    FROM recovery.proposal_decision_events
                    WHERE tenant_id=%s AND id=%s
                    """,
                    (tenant_id, approval_id),
                )
                d = cur.fetchone()
            elif applied_event_raw:
                cur.execute(
                    """
                    SELECT d.id, d.proposal_artifact_id, d.proposal_fingerprint, d.decision,
                           d.decided_by, d.decided_at
                    FROM recovery.mutation_events m
                    JOIN recovery.proposal_decision_events d
                      ON d.tenant_id=m.tenant_id AND d.id=m.approval_event_id
                    WHERE m.tenant_id=%s AND m.id=%s
                    """,
                    (tenant_id, UUID(str(applied_event_raw))),
                )
                d = cur.fetchone()
                approval_id = d["id"] if d else UUID(int=0)
            else:
                raise PermanentWorkerError("mutation payload lacks approval reference", code="APPROVAL_MISSING")
            if d is None or d["decision"] != "approved" or d["proposal_artifact_id"] != artifact_id:
                raise PermanentWorkerError("valid approval event not found", code="APPROVAL_INVALID")
            if d["proposal_fingerprint"] != proposal.fingerprint_sha256:
                raise PermanentWorkerError("approval fingerprint differs from proposal", code="APPROVAL_STALE")
            approval = ApprovalRecord(
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.fingerprint_sha256,
                approved_by=str(d["decided_by"]), approved_at=d["decided_at"],
            )
            cur.execute(
                """
                SELECT credential_ref FROM recovery.google_ads_accounts
                WHERE tenant_id=%s AND customer_id=%s
                """,
                (tenant_id, proposal.candidate.customer_id),
            )
            acc = cur.fetchone()
            if acc is None:
                raise PermanentWorkerError("proposal advertiser account not found", code="ACCOUNT_NOT_FOUND")
        if not is_rollback:
            # Re-check the latest Measurement Integrity gate at effect time. Mapping events can
            # change without creating a new Business Truth snapshot, so queue-time validation alone
            # is not sufficient for an accuracy-first financial action.
            from recovery.api.repository import PostgresApiRepository
            measurement=PostgresApiRepository(self.core).measurement_integrity_overview(
                tenant_id=tenant_id, account_id=source["account_id"]
            )
            if not measurement["conversion_dependent_claims_allowed"]:
                raise PermanentWorkerError(
                    "Measurement Integrity no longer allows conversion-dependent mutation",
                    code="MEASUREMENT_GATE_BLOCKED",
                )
        return MutationContext(artifact_id, proposal, approval_id, approval, acc["credential_ref"])

    def _executor(self, *, tenant_id: UUID, context: MutationContext):
        client = self.client_resolver.client_for(
            tenant_id=tenant_id, credential_ref=context.credential_ref,
            customer_id=context.proposal.candidate.customer_id,
        )
        adapter = GoogleAdsV26Adapter.from_google_ads_client(client)
        executor = GoogleAdsNegativeMutationExecutor(client=client, adapter=adapter)
        return adapter, executor

    def preflight(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context(tenant_id=tenant_id, payload=payload)
        adapter, _ = self._executor(tenant_id=tenant_id, context=context)
        if "resource_name" in payload:  # rollback
            resource = str(payload["resource_name"])
            match = GoogleAdsNegativeMutationExecutor.RESOURCE_RE.fullmatch(resource)
            if not match:
                raise PermanentWorkerError("rollback resource name is invalid", code="BAD_ROLLBACK_RESOURCE")
            found = adapter.find_applied_ad_group_negative(
                customer_id=match.group("customer"), ad_group_id=match.group("adgroup"),
                resource_name=resource,
            )
            return {"resource_absent": found is None, "resource_name": resource}

        candidate = context.proposal.candidate
        exact = []
        for negative in adapter.iter_ad_group_negatives(candidate.customer_id):
            if (
                negative.ad_group_id == candidate.ad_group_id
                and negative.match_type is candidate.match_type
                and negative.text.casefold() == candidate.text.casefold()
            ):
                exact.append(negative.resource_name)
        return {
            "exact_negative_present": bool(exact),
            "resource_name": exact[0] if len(exact) == 1 else None,
            "matching_resource_names": tuple(x for x in exact if x),
        }

    def validate(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context(tenant_id=tenant_id, payload=payload)
        _, executor = self._executor(tenant_id=tenant_id, context=context)
        plan = build_mutation_plan(context.proposal, context.approval)
        receipt = executor.validate(proposal=context.proposal, approval=context.approval, plan=plan)
        self.core.record_mutation_event(
            tenant_id=tenant_id, proposal_artifact_id=context.proposal_artifact_id,
            approval_event_id=context.approval_event_id, event_type="validate_only_passed",
            resource_name=None, api_request_id=None, actor="phase10-worker",
            occurred_at=receipt.validated_at, payload=canonical_payload(receipt),
        )
        return canonical_payload(receipt)

    def apply(self, *, tenant_id: UUID, payload: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
        from recovery.api.repository import PostgresApiRepository
        if not PostgresApiRepository(self.core).internal_feature_enabled(tenant_id=tenant_id,feature_key="google_ads_mutations"):
            raise PermanentWorkerError("Google Ads mutation blocked by platform operational control",code="PLATFORM_MUTATION_HOLD")
        context = self._context(tenant_id=tenant_id, payload=payload)
        _, executor = self._executor(tenant_id=tenant_id, context=context)
        plan = build_mutation_plan(context.proposal, context.approval)
        try:
            validated_at = datetime.fromisoformat(str(validation["validated_at"]))
            receipt = ValidationReceipt(
                proposal_id=str(validation["proposal_id"]),
                plan_fingerprint=str(validation["plan_fingerprint"]),
                validated_at=validated_at, api_version=str(validation["api_version"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise PermanentWorkerError("invalid validation receipt", code="BAD_VALIDATION_RECEIPT") from exc
        mutation = executor.apply(
            proposal=context.proposal, approval=context.approval, plan=plan, validation=receipt
        )
        event_id = self.core.record_mutation_event(
            tenant_id=tenant_id, proposal_artifact_id=context.proposal_artifact_id,
            approval_event_id=context.approval_event_id, event_type="applied",
            resource_name=mutation.resource_name, api_request_id=None, actor="phase10-worker",
            occurred_at=mutation.applied_at, payload=canonical_payload(mutation),
        )

        # Bootstrap the case-specific Recovery Ledger immediately after an exact read-back
        # verified mutation. This records historical observed exposure and, only when the
        # source window is fully pre-action, a clearly labelled run-rate projection. It
        # never records verified recovery from a pre/post comparison.
        with self.core._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """SELECT r.id AS analysis_run_id,s.window_start,s.window_end,
                          COALESCE(mp.conversion_lag_days,0) AS conversion_lag_days
                   FROM recovery.analysis_artifacts a
                   JOIN recovery.analysis_runs r ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
                   JOIN recovery.sync_runs s ON s.tenant_id=r.tenant_id AND s.id=r.sync_run_id
                   LEFT JOIN recovery.account_measurement_profiles mp
                     ON mp.tenant_id=r.tenant_id AND mp.account_id=r.account_id
                   WHERE a.tenant_id=%s AND a.id=%s""",
                (tenant_id, context.proposal_artifact_id),
            )
            source=cur.fetchone()
        if source is None:
            raise RuntimeError("applied mutation has no analysis/sync source for Recovery Ledger")
        recovery_engine=RecoveryVerificationEngine(AccuracyPolicy(conversion_lag_days=int(source["conversion_lag_days"])))
        action=recovery_engine.record_applied_change(
            proposal=context.proposal, approval=context.approval, plan=plan,
            resource_name=mutation.resource_name, applied_at=mutation.applied_at,
            applied_by="phase10-worker", validate_only_passed=True,
        )
        baseline=recovery_engine.build_baseline(
            proposal=context.proposal, window_start=source["window_start"], window_end=source["window_end"]
        )
        projection=None
        projection_start=mutation.applied_at.date()+timedelta(days=1)
        if source["window_end"] < mutation.applied_at.date():
            projection=recovery_engine.project_run_rate(
                baseline=baseline, action=action, projection_start=projection_start,
                projection_end=projection_start+timedelta(days=baseline.window_days-1),
            )
        configuration=ConfigurationVerification(
            resource_name=mutation.resource_name, checked_at=mutation.applied_at, exists=True, negative=True,
            keyword_text=context.proposal.candidate.text, match_type=context.proposal.candidate.match_type,
            customer_id=context.proposal.candidate.customer_id, campaign_id=context.proposal.candidate.campaign_id or "",
            ad_group_id=context.proposal.candidate.ad_group_id or "",
        )
        ledger_summary=recovery_engine.summarize(
            baseline=baseline, action=action, configuration=configuration, projection=projection
        )
        ledger_id=self.core.record_recovery_ledger(
            tenant_id=tenant_id, analysis_run_id=source["analysis_run_id"], summary=ledger_summary,
            mutation_event_id=event_id,
        )
        return {**canonical_payload(mutation), "mutation_event_id": str(event_id),
                "recovery_ledger_entry_id": str(ledger_id), "resource_name": mutation.resource_name}

    def rollback(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context(tenant_id=tenant_id, payload=payload)
        adapter, executor = self._executor(tenant_id=tenant_id, context=context)
        resource = str(payload.get("resource_name") or "")
        match = GoogleAdsNegativeMutationExecutor.RESOURCE_RE.fullmatch(resource)
        if not match:
            raise PermanentWorkerError("rollback resource name is invalid", code="BAD_ROLLBACK_RESOURCE")
        receipt = MutationReceipt(
            proposal_id=context.proposal.proposal_id,
            plan_fingerprint="0" * 64,
            resource_name=resource,
            applied_at=datetime.now(timezone.utc),
            api_version=GOOGLE_ADS_API_VERSION,
            readback_verified=True,
        )
        executor.rollback(receipt=receipt)
        found = adapter.find_applied_ad_group_negative(
            customer_id=match.group("customer"), ad_group_id=match.group("adgroup"), resource_name=resource,
        )
        if found is not None:
            raise RuntimeError("rollback mutate returned but exact negative is still present on read-back")
        event_id = self.core.record_mutation_event(
            tenant_id=tenant_id, proposal_artifact_id=context.proposal_artifact_id,
            approval_event_id=context.approval_event_id, event_type="rolled_back",
            resource_name=resource, api_request_id=None, actor="phase10-worker",
            occurred_at=datetime.now(timezone.utc),
            payload={"resource_name": resource, "readback_absent": True},
        )
        return {"resource_name": resource, "mutation_event_id": str(event_id), "readback_absent": True}
