from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from .auth import Principal
from .business_truth_io import parse_business_truth_payload
from .billing_service import BillingApplicationService
from .idempotency import validate_idempotency_key
from .jobs import JobReceipt, JobType
from .policy import AuthorizationError, Permission, TenantAccess
from recovery.reporting import ReportRequest, ReportScope, ReportType
from .repository import ApiRepository, Membership


class ApplicationService:
    def __init__(self, repository: ApiRepository, billing: BillingApplicationService | None = None) -> None:
        self.repo = repository
        self.billing = billing

    def _require_billing(self, *, access: TenantAccess, capability: str, account_id: UUID | None = None,
                         sync_start: date | None = None, sync_end: date | None = None,
                         reserve_account: bool = False) -> None:
        if self.billing is not None:
            self.billing.require_full(access=access, capability=capability, account_id=account_id,
                                      sync_start=sync_start, sync_end=sync_end, reserve_account=reserve_account)

    def register_seen_user(self, principal: Principal) -> None:
        if not self.repo.touch_user(user_id=principal.user_id, email=principal.email):
            raise AuthorizationError("user is disabled")

    def access(self, *, principal: Principal, tenant_id: UUID, permission: Permission) -> TenantAccess:
        membership = self.repo.membership(user_id=principal.user_id, tenant_id=tenant_id)
        if membership is None:
            # Do not distinguish missing tenant from missing membership.
            raise AuthorizationError("tenant access denied")
        access = TenantAccess(tenant_id=tenant_id, principal=principal, role=membership.role,
                              account_access_mode=membership.account_access_mode,
                              client_portal=membership.client_portal,
                              allowed_account_ids=membership.allowed_account_ids)
        access.require(permission)
        return access


    def enqueue_deployment_probe(self, *, access: TenantAccess, idempotency_key: str, endpoint: str) -> JobReceipt:
        """Enqueue a zero-external-effect worker round-trip probe.

        This is intentionally admin/owner-only and billing-independent. It exists only
        to prove API -> PostgreSQL queue -> deployed worker -> PostgreSQL result.
        """
        access.require(Permission.DEPLOYMENT_PROBE)
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=validate_idempotency_key(idempotency_key),
            job_type=JobType.DEPLOYMENT_PROBE,
            payload={"probe": "deployment_round_trip"},
        )

    def enqueue_pilot_google_ads_read_probe(self, *, access: TenantAccess, account_id: UUID, idempotency_key: str, endpoint: str) -> JobReceipt:
        """Queue a deployed, read-only Google Ads credential/customer proof for pilot qualification."""
        access.require(Permission.PILOT_PROBE)
        access.require_account(account_id)
        self.repo.ensure_account(tenant_id=access.tenant_id,account_id=account_id)
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,user_id=access.principal.user_id,endpoint=endpoint,
            idempotency_key=validate_idempotency_key(idempotency_key),
            job_type=JobType.PILOT_GOOGLE_ADS_READ_PROBE,
            payload={"account_id":str(account_id)},
            operation_key=f"pilot-google-read:{account_id}",
        )

    def enqueue_monitoring_evaluation(self, *, access: TenantAccess, account_id: UUID, idempotency_key: str, endpoint: str) -> JobReceipt:
        access.require(Permission.MONITORING_EVALUATE)
        access.require_account(account_id)
        self.repo.ensure_account(tenant_id=access.tenant_id, account_id=account_id)
        self._require_billing(access=access, capability="monitoring evaluation", account_id=account_id)
        key=validate_idempotency_key(idempotency_key)
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id, user_id=access.principal.user_id, endpoint=endpoint,
            idempotency_key=key, job_type=JobType.MONITORING_EVALUATION,
            payload={"account_id": str(account_id), "requested_by": str(access.principal.user_id)},
            operation_key=f"manual-monitor:{account_id}:{key}",
        )

    def enqueue_report_generation(self, *, access: TenantAccess, report_type: str, scope_kind: str, scope_id: str,
                                  period_start: date | None, period_end: date | None, idempotency_key: str, endpoint: str) -> JobReceipt:
        access.require(Permission.REPORT_GENERATE)
        request=ReportRequest(report_type=ReportType(report_type),scope_kind=ReportScope(scope_kind),scope_id=scope_id,period_start=period_start,period_end=period_end)
        if request.scope_kind is ReportScope.ACCOUNT:
            access.require_account(UUID(scope_id))
            self.repo.ensure_account(tenant_id=access.tenant_id,account_id=UUID(scope_id))
        elif request.scope_kind is ReportScope.PORTFOLIO:
            access.require_unrestricted_scope()
            self.repo.portfolio_detail(tenant_id=access.tenant_id,portfolio_id=UUID(scope_id))
        elif access.account_access_mode != "all_accounts":
            raise AuthorizationError("organization reports require all_accounts access")
        elif scope_id != str(access.tenant_id):
            raise ValueError("organization report scope_id must equal tenant_id")
        self._require_billing(access=access, capability="report generation", account_id=UUID(scope_id) if request.scope_kind is ReportScope.ACCOUNT else None)
        key=validate_idempotency_key(idempotency_key)
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,user_id=access.principal.user_id,endpoint=endpoint,idempotency_key=key,
            job_type=JobType.REPORT_GENERATION,payload={
                "report_type":request.report_type.value,"scope_kind":request.scope_kind.value,"scope_id":request.scope_id,
                "period_start":request.period_start.isoformat() if request.period_start else None,
                "period_end":request.period_end.isoformat() if request.period_end else None,
            },
        )

    def enqueue_sync(self, *, access: TenantAccess, account_id: UUID, start: date, end: date,
                     idempotency_key: str, endpoint: str) -> JobReceipt:
        access.require(Permission.SYNC_START)
        if start > end:
            raise ValueError("start must be <= end")
        access.require_account(account_id)
        self.repo.ensure_account(tenant_id=access.tenant_id, account_id=account_id)
        self._require_billing(access=access, capability="Google Ads sync", account_id=account_id,
                              sync_start=start, sync_end=end, reserve_account=True)
        key = validate_idempotency_key(idempotency_key)
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=key,
            job_type=JobType.GOOGLE_ADS_SYNC,
            payload={"account_id": str(account_id), "start": start.isoformat(), "end": end.isoformat()},
        )

    def create_business_truth(self, *, access: TenantAccess, account_id: UUID, payload: dict[str, Any],
                              idempotency_key: str, endpoint: str) -> tuple[UUID, str, int, bool]:
        access.require(Permission.BUSINESS_TRUTH_WRITE)
        access.require_account(account_id)
        self.repo.ensure_account(tenant_id=access.tenant_id, account_id=account_id)
        self._require_billing(access=access, capability="Business Truth update", account_id=account_id)
        key = validate_idempotency_key(idempotency_key)
        try:
            snapshot = parse_business_truth_payload(payload, submitted_by=access.actor_id)
        except KeyError as exc:
            raise ValueError(f"Business Truth is missing required field: {exc.args[0]}") from exc
        except TypeError as exc:
            raise ValueError("Business Truth payload has an invalid structure") from exc
        return self.repo.save_business_truth(
            tenant_id=access.tenant_id, account_id=account_id, user_id=access.principal.user_id, endpoint=endpoint,
            idempotency_key=key, request_payload=payload, snapshot=snapshot
        )

    def enqueue_analysis(self, *, access: TenantAccess, account_id: UUID, sync_run_id: UUID,
                         truth_snapshot_id: UUID, as_of: date, conversion_lag_days: int,
                         idempotency_key: str, endpoint: str) -> JobReceipt:
        access.require(Permission.ANALYSIS_START)
        self._require_billing(access=access, capability="analysis", account_id=account_id)
        self.repo.validate_analysis_inputs(
            tenant_id=access.tenant_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            truth_snapshot_id=truth_snapshot_id,
            as_of=as_of,
        )
        if conversion_lag_days < 0 or conversion_lag_days > 365:
            raise ValueError("conversion_lag_days must be between 0 and 365")
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=validate_idempotency_key(idempotency_key),
            job_type=JobType.ANALYSIS_RUN,
            payload={
                "account_id": str(account_id),
                "sync_run_id": str(sync_run_id),
                "truth_snapshot_id": str(truth_snapshot_id),
                "as_of": as_of.isoformat(),
                "conversion_lag_days": conversion_lag_days,
            },
        )

    def enqueue_semantic_shadow(self, *, access: TenantAccess, account_id: UUID,
                                sync_run_id: UUID, truth_snapshot_id: UUID,
                                idempotency_key: str, endpoint: str) -> JobReceipt:
        access.require(Permission.SEMANTIC_SHADOW_START)
        self._require_billing(access=access, capability="semantic shadow", account_id=account_id)
        # Reuse the same exact-account/sync/truth validation as production analysis,
        # but without an as_of/conversion policy because shadow semantics use no metrics.
        self.repo.validate_shadow_inputs(
            tenant_id=access.tenant_id,
            account_id=account_id,
            sync_run_id=sync_run_id,
            truth_snapshot_id=truth_snapshot_id,
        )
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=validate_idempotency_key(idempotency_key),
            job_type=JobType.SEMANTIC_SHADOW,
            payload={
                "account_id": str(account_id),
                "sync_run_id": str(sync_run_id),
                "truth_snapshot_id": str(truth_snapshot_id),
            },
        )

    def decide_proposal(self, *, access: TenantAccess, proposal_artifact_id: UUID,
                        proposal_fingerprint: str, decision: str, note: str | None) -> UUID:
        access.require(Permission.PROPOSAL_DECIDE)
        if decision == "approved":
            self._require_billing(access=access, capability="proposal approval")
        return self.repo.record_proposal_decision(
            tenant_id=access.tenant_id,
            proposal_artifact_id=proposal_artifact_id,
            proposal_fingerprint=proposal_fingerprint,
            decision=decision,
            actor=access.actor_id,
            note=note,
        )

    def enqueue_mutation(self, *, access: TenantAccess, proposal_artifact_id: UUID,
                         idempotency_key: str, endpoint: str, rollback: bool = False) -> JobReceipt:
        access.require(Permission.MUTATION_ROLLBACK if rollback else Permission.MUTATION_EXECUTE)
        if not rollback:
            gate=getattr(self.repo,"internal_feature_enabled",None)
            if gate is not None and not gate(tenant_id=access.tenant_id,feature_key="google_ads_mutations"):
                raise ApiConflict("Google Ads mutations are temporarily disabled by a platform operational control")
            self._require_billing(access=access, capability="Google Ads mutation")
        proposal = (
            self.repo.proposal_rollback_payload(
                tenant_id=access.tenant_id, proposal_artifact_id=proposal_artifact_id
            )
            if rollback
            else self.repo.proposal_execution_payload(
                tenant_id=access.tenant_id, proposal_artifact_id=proposal_artifact_id
            )
        )
        return self.repo.enqueue_job(
            tenant_id=access.tenant_id,
            user_id=access.principal.user_id,
            endpoint=endpoint,
            idempotency_key=validate_idempotency_key(idempotency_key),
            job_type=JobType.ROLLBACK_NEGATIVE if rollback else JobType.APPLY_NEGATIVE,
            payload=proposal,
            operation_key=f"proposal:{proposal_artifact_id}:{'rollback' if rollback else 'apply'}",
        )
