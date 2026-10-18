from __future__ import annotations

from dataclasses import dataclass
import hashlib
from decimal import Decimal
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from recovery.business_truth import BusinessTruthSnapshot, CustomerLocationRequirement, TruthClaim
from recovery.accuracy import AccuracyPolicy
from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.waste_intelligence import UserLocationObservation, evaluate_geo_leaks, query_leak_family
from recovery.billing import BillingPlan, EntitlementState, ProviderInvoice, ProviderSubscription
from recovery.db.canonical import canonical_payload, payload_sha256
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.search_intelligence import validate_sort
from recovery.search_intent import normalize_query
from recovery.recovery_cases import derive_case_projection
from recovery.recovery_center import aggregate_latest_ledger
from recovery.reporting import REPORT_SCOPE_RULES, ReportRequest, ReportScope, ReportType, ScheduleDefinition, new_share_token, parse_share_tenant, report_snapshot_sha256, render_report_csv, render_report_pdf, share_token_sha256
from recovery.reporting_service import build_report_snapshot
from recovery.internal_admin import FEATURE_KEYS, SAFE_INTERNAL_RETRY_JOB_TYPES, PlatformAuthorizationError, PlatformOperatorRole
from recovery.launch_control import LaunchMode, derive_launch_state, derive_launch_access, launch_email_sha256, launch_email_hint, normalize_launch_email, workspace_creation_allowed
from recovery.launch_gate import validate_launch_gate_report
from recovery.monitoring import (
    AlertSeverity,
    CampaignHealthObservation,
    MonitorSignal,
    campaign_health_signal,
    conversion_drop_signal,
    derive_alert_state,
    incident_observation_action,
    spend_anomaly_signal,
    validate_alert_transition,
)
from recovery.agency_operations import normalize_email,new_invite_token,invite_token_sha256,validate_access_shape,invitation_state,validate_owner_management,validate_member_transition
from recovery.measurement_integrity import (
    ConversionActionObservation,CustomerConversionGoalObservation,CampaignConversionGoalObservation,CampaignGoalConfigObservation,
    ConversionLagObservation,MeasurementMapping,assess_measurement_integrity,
)

from .idempotency import canonical_request_sha256
from .jobs import JobReceipt, JobStatus, JobType
from .policy import TenantRole


class ApiConflict(RuntimeError):
    pass


class ApiNotFound(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Membership:
    tenant_id: UUID
    role: TenantRole
    status: str
    account_access_mode: str = "all_accounts"
    client_portal: bool = False
    allowed_account_ids: frozenset[UUID] = frozenset()


class ApiRepository(Protocol):
    def touch_user(self, *, user_id: UUID, email: str | None) -> bool: ...
    def list_memberships(self, *, user_id: UUID) -> list[dict[str, Any]]: ...
    def membership(self, *, user_id: UUID, tenant_id: UUID) -> Membership | None: ...
    def list_accounts(self, *, tenant_id: UUID, user_id: UUID | None = None) -> list[dict[str, Any]]: ...
    def ensure_account(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID | None = None) -> None: ...
    def accessible_account_ids(self, *, tenant_id: UUID, user_id: UUID) -> frozenset[UUID]: ...
    def enqueue_job(self, *, tenant_id: UUID, user_id: UUID, endpoint: str,
                    idempotency_key: str, job_type: JobType, payload: dict[str, Any],
                    operation_key: str | None = None) -> JobReceipt: ...
    def save_business_truth(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID, endpoint: str,
                            idempotency_key: str, request_payload: dict[str, Any],
                            snapshot: BusinessTruthSnapshot) -> tuple[UUID, str, int, bool]: ...
    def business_truth_versions(self, *, tenant_id: UUID, account_id: UUID, limit: int) -> list[dict[str, Any]]: ...
    def business_truth_version(self, *, tenant_id: UUID, account_id: UUID, snapshot_id: UUID | None) -> dict[str, Any]: ...
    def validate_analysis_inputs(self, *, tenant_id: UUID, account_id: UUID,
                                 sync_run_id: UUID, truth_snapshot_id: UUID, as_of: date) -> None: ...
    def validate_shadow_inputs(self, *, tenant_id: UUID, account_id: UUID,
                               sync_run_id: UUID, truth_snapshot_id: UUID) -> None: ...
    def validate_shadow_inputs(self, *, tenant_id: UUID, account_id: UUID,
                               sync_run_id: UUID, truth_snapshot_id: UUID) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT s.status AS sync_status
                FROM recovery.sync_runs s
                WHERE s.tenant_id=%s AND s.id=%s AND s.account_id=%s
                """,
                (tenant_id, sync_run_id, account_id),
            )
            sync = cur.fetchone()
            if sync is None:
                raise ApiNotFound("sync run/account combination not found")
            if sync["sync_status"] != "completed":
                raise ApiConflict("semantic shadow requires a completed sync run")
            cur.execute(
                "SELECT 1 FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND id=%s AND account_id=%s",
                (tenant_id, truth_snapshot_id, account_id),
            )
            if cur.fetchone() is None:
                raise ApiNotFound("business truth snapshot not found for this Google Ads account")

    def list_findings(self, *, tenant_id: UUID, analysis_run_id: UUID | None,
                      kind: str | None, limit: int, account_id: UUID | None = None) -> list[dict[str, Any]]: ...
    def record_proposal_decision(self, *, tenant_id: UUID, proposal_artifact_id: UUID,
                                 proposal_fingerprint: str, decision: str,
                                 actor: str, note: str | None) -> UUID: ...
    def proposal_execution_payload(self, *, tenant_id: UUID, proposal_artifact_id: UUID) -> dict[str, Any]: ...
    def proposal_rollback_payload(self, *, tenant_id: UUID, proposal_artifact_id: UUID) -> dict[str, Any]: ...
    def get_job(self, *, tenant_id: UUID, user_id: UUID, job_id: UUID) -> dict[str, Any]: ...
    def list_ledger(self, *, tenant_id: UUID, limit: int, account_id: UUID | None = None) -> list[dict[str, Any]]: ...
    def workspace_summary(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def list_proposals(self, *, tenant_id: UUID, account_id: UUID, analysis_run_id: UUID | None, limit: int) -> list[dict[str, Any]]: ...
    def billing_current(self, *, tenant_id: UUID) -> dict[str, Any] | None: ...
    def billing_checkout_by_request(self, *, tenant_id: UUID, user_id: UUID, idempotency_key: str) -> dict[str, Any] | None: ...
    def prepare_billing_checkout(self, *, tenant_id: UUID, user_id: UUID, endpoint: str,
                                 idempotency_key: str, plan_key: str) -> tuple[dict[str, Any], bool]: ...
    def set_billing_checkout_state(self, *, tenant_id: UUID, intent_id: UUID, state: str,
                                   provider_subscription_id: str | None = None, provider_plan_id: str | None = None,
                                   checkout_url: str | None = None, failure_code: str | None = None) -> None: ...
    def billing_checkout_by_provider(self, *, tenant_id: UUID, provider_subscription_id: str) -> dict[str, Any] | None: ...
    def latest_billing_checkout(self, *, tenant_id: UUID) -> dict[str, Any] | None: ...
    def billing_webhook_has_result(self, *, webhook_event_id: UUID) -> bool: ...
    def claim_billing_webhook(self, *, provider_event_id: str, raw_body_sha256: str) -> tuple[UUID, bool]: ...
    def record_billing_webhook_result(self, *, webhook_event_id: UUID, tenant_id: UUID | None,
                                      provider_subscription_id: str | None, event_type: str | None,
                                      reconcile_status: str, error_code: str | None = None) -> None: ...
    def reconcile_billing_subscription(self, *, tenant_id: UUID, subscription: ProviderSubscription,
                                       plan: BillingPlan, entitlement_state: EntitlementState, grace_until: datetime | None = None) -> UUID: ...
    def billing_lifecycle_operation_by_request(self, *, tenant_id: UUID, user_id: UUID, idempotency_key: str) -> dict[str, Any] | None: ...
    def prepare_billing_lifecycle_operation(self, *, tenant_id: UUID, user_id: UUID, endpoint: str, idempotency_key: str, operation_type: str, provider_subscription_id: str, target_plan_key: str | None, effective_at: datetime | None) -> tuple[dict[str, Any], bool]: ...
    def append_billing_lifecycle_event(self, *, tenant_id: UUID, operation_id: UUID, event_type: str, actor: str, payload: dict[str, Any] | None = None) -> None: ...
    def billing_lifecycle_operation(self, *, tenant_id: UUID, operation_id: UUID) -> dict[str, Any]: ...
    def latest_billing_lifecycle_operations(self, *, tenant_id: UUID, provider_subscription_id: str, limit: int = 50) -> list[dict[str, Any]]: ...
    def record_billing_pending_change(self, *, tenant_id: UUID, subscription_id: str, pending: ProviderSubscription, target_plan: BillingPlan) -> UUID: ...
    def latest_billing_pending_change(self, *, tenant_id: UUID, subscription_id: str) -> dict[str, Any] | None: ...
    def record_billing_invoices(self, *, tenant_id: UUID, subscription_id: str, invoices: list[ProviderInvoice]) -> int: ...
    def list_billing_invoices(self, *, tenant_id: UUID, subscription_id: str, limit: int = 100) -> list[dict[str, Any]]: ...
    def save_billing_profile(self, *, tenant_id: UUID, user_id: UUID, legal_name: str, billing_email: str, tax_country: str, tax_region: str | None, gstin: str | None) -> dict[str, Any]: ...
    def billing_profile(self, *, tenant_id: UUID) -> dict[str, Any] | None: ...
    def billing_entitlement_history(self, *, tenant_id: UUID, limit: int = 100) -> list[dict[str, Any]]: ...
    def reserve_billing_account_slot(self, *, tenant_id: UUID, account_id: UUID, max_accounts: int) -> None: ...
    def billing_account_slot_allowed(self, *, tenant_id: UUID, account_id: UUID, max_accounts: int) -> bool: ...
    def list_billing_account_slots(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def release_billing_account_slot(self, *, tenant_id: UUID, account_id: UUID, actor: str) -> None: ...
    def command_center(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]: ...
    def list_portfolios(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def portfolio_detail(self, *, tenant_id: UUID, portfolio_id: UUID) -> dict[str, Any]: ...
    def create_portfolio(self, *, tenant_id: UUID, user_id: UUID, name: str, description: str | None) -> dict[str, Any]: ...
    def add_portfolio_account(self, *, tenant_id: UUID, user_id: UUID, portfolio_id: UUID, account_id: UUID) -> None: ...
    def remove_portfolio_account(self, *, tenant_id: UUID, portfolio_id: UUID, account_id: UUID) -> None: ...
    def list_tasks(self, *, tenant_id: UUID, user_id: UUID, scope: str, account_id: UUID | None, status: str | None, limit: int) -> list[dict[str, Any]]: ...
    def create_task(self, *, tenant_id: UUID, user_id: UUID, title: str, description: str | None, account_id: UUID | None, portfolio_id: UUID | None, priority: str, assigned_to: UUID | None, due_at: datetime | None) -> dict[str, Any]: ...
    def update_task_status(self, *, tenant_id: UUID, task_id: UUID, status: str) -> dict[str, Any]: ...
    def list_notifications(self, *, tenant_id: UUID, user_id: UUID, unread_only: bool, limit: int) -> list[dict[str, Any]]: ...
    def mark_notification_read(self, *, tenant_id: UUID, user_id: UUID, notification_id: UUID) -> dict[str, Any]: ...
    def global_search(self, *, tenant_id: UUID, user_id: UUID, query: str, limit: int) -> list[dict[str, Any]]: ...
    def search_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None) -> dict[str, Any]: ...
    def search_intelligence_terms(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, query: str | None, network: str | None, fit: str | None, sort: str, direction: str, page: int, page_size: int) -> dict[str, Any]: ...
    def search_intelligence_term_detail(self, *, tenant_id: UUID, account_id: UUID, normalized_query: str, start: date | None, end: date | None) -> dict[str, Any]: ...
    def search_intelligence_breakdown(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, dimension: str) -> dict[str, Any]: ...
    def search_intelligence_ngrams(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, n: int, sort: str, limit: int, without_conversions: bool) -> dict[str, Any]: ...
    def list_search_saved_views(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> list[dict[str, Any]]: ...
    def create_search_saved_view(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, name: str, filters: dict[str, Any], is_default: bool) -> dict[str, Any]: ...
    def delete_search_saved_view(self, *, tenant_id: UUID, user_id: UUID, view_id: UUID) -> None: ...
    def portfolio_search_ngrams(self, *, tenant_id: UUID, portfolio_id: UUID, start: date, end: date, n: int, limit: int) -> list[dict[str, Any]]: ...
    def waste_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None) -> dict[str, Any]: ...
    def waste_intelligence_query_leaks(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, family: str | None, disposition: str | None, page: int, page_size: int) -> dict[str, Any]: ...
    def waste_intelligence_dimension(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, dimension: str) -> dict[str, Any]: ...
    def waste_intelligence_geo(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None) -> dict[str, Any]: ...
    def measurement_integrity_overview(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def measurement_conversion_actions(self, *, tenant_id: UUID, account_id: UUID) -> list[dict[str, Any]]: ...
    def measurement_goals(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def measurement_lag(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def record_conversion_action_mapping(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID, conversion_action_resource: str, outcome_id: str | None) -> dict[str, Any]: ...
    def list_recovery_cases(self, *, tenant_id: UUID, account_id: UUID, state: str | None, risk: str | None, limit: int) -> list[dict[str, Any]]: ...
    def recovery_case_detail(self, *, tenant_id: UUID, case_id: UUID) -> dict[str, Any]: ...
    def append_recovery_case_event(self, *, tenant_id: UUID, case_id: UUID, actor: str, event_type: str, note: str | None, assigned_to: UUID | None) -> dict[str, Any]: ...
    def recovery_center_overview(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]: ...
    def recovery_center_cases(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, causal_status: str | None, limit: int) -> list[dict[str, Any]]: ...
    def recovery_center_breakdown(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, dimension: str) -> dict[str, Any]: ...
    def recovery_center_timeline(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]: ...

    def monitoring_overview(self, *, tenant_id: UUID, account_id: UUID | None) -> dict[str, Any]: ...
    def monitoring_alerts(self, *, tenant_id: UUID, account_id: UUID | None, state: str | None, severity: str | None, monitor_type: str | None, limit: int) -> list[dict[str, Any]]: ...
    def monitoring_alert_detail(self, *, tenant_id: UUID, alert_id: UUID) -> dict[str, Any]: ...
    def monitoring_alert_event(self, *, tenant_id: UUID, alert_id: UUID, actor: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def monitoring_policies(self, *, tenant_id: UUID, account_id: UUID | None) -> list[dict[str, Any]]: ...
    def monitoring_policy_event(self, *, tenant_id: UUID, account_id: UUID | None, actor: str, monitor_type: str, enabled: bool, severity_override: str | None, config: dict[str, Any]) -> dict[str, Any]: ...
    def monitoring_evaluate(self, *, tenant_id: UUID, account_id: UUID, actor: str) -> dict[str, Any]: ...
    def list_report_generations(self, *, tenant_id: UUID, report_type: str | None, scope_kind: str | None, scope_id: str | None, limit: int) -> list[dict[str, Any]]: ...
    def report_generation(self, *, tenant_id: UUID, generation_id: UUID) -> dict[str, Any]: ...
    def generate_report(self, *, tenant_id: UUID, generated_by: UUID, report_type: str, scope_kind: str, scope_id: str, period_start: date | None, period_end: date | None, source_job_id: UUID | None, schedule_id: UUID | None) -> dict[str, Any]: ...
    def report_artifact(self, *, tenant_id: UUID, generation_id: UUID, artifact_format: str) -> dict[str, Any]: ...
    def create_report_share(self, *, tenant_id: UUID, user_id: UUID, actor: str, generation_id: UUID, expires_days: int) -> dict[str, Any]: ...
    def revoke_report_share(self, *, tenant_id: UUID, actor: str, share_id: UUID) -> dict[str, Any]: ...
    def list_report_shares(self, *, tenant_id: UUID, generation_id: UUID | None) -> list[dict[str, Any]]: ...
    def public_report(self, *, token: str, record_access: bool = True) -> dict[str, Any]: ...
    def public_report_artifact(self, *, token: str, artifact_format: str) -> dict[str, Any]: ...
    def list_report_schedules(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def record_report_schedule(self, *, tenant_id: UUID, user_id: UUID, schedule_id: UUID | None, report_type: str, scope_kind: str, scope_id: str, frequency: str, timezone_name: str, hour: int, minute: int, weekday: int | None, day_of_month: int | None, recipients: list[str], enabled: bool) -> dict[str, Any]: ...
    def report_schedule(self, *, tenant_id: UUID, schedule_id: UUID) -> dict[str, Any]: ...
    def record_report_delivery(self, *, tenant_id: UUID, generation_id: UUID, schedule_id: UUID | None, recipient: str, event_type: str, detail: str | None) -> None: ...
    def platform_operator_role(self, *, user_id: UUID) -> str | None: ...
    def list_internal_tenants(self, *, user_id: UUID, query: str | None, limit: int) -> list[dict[str, Any]]: ...
    def internal_tenant_diagnostics(self, *, user_id: UUID, tenant_id: UUID) -> dict[str, Any]: ...
    def internal_jobs(self, *, user_id: UUID, tenant_id: UUID, status: str | None, limit: int) -> list[dict[str, Any]]: ...
    def internal_retry_job(self, *, user_id: UUID, tenant_id: UUID, job_id: UUID, reason: str) -> dict[str, Any]: ...
    def internal_support_cases(self, *, user_id: UUID, tenant_id: UUID, limit: int) -> list[dict[str, Any]]: ...
    def create_internal_support_case(self, *, user_id: UUID, tenant_id: UUID, title: str, category: str, severity: str, note: str | None) -> dict[str, Any]: ...
    def internal_support_case_event(self, *, user_id: UUID, tenant_id: UUID, case_id: UUID, event_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def internal_feature_controls(self, *, user_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def set_internal_feature_control(self, *, user_id: UUID, tenant_id: UUID, feature_key: str, enabled: bool, reason: str) -> dict[str, Any]: ...
    def internal_platform_incidents(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]: ...
    def internal_release_history(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]: ...
    def create_internal_platform_incident_event(self, *, user_id: UUID, incident_id: UUID | None, event_type: str, severity: str, title: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def internal_feature_enabled(self, *, tenant_id: UUID, feature_key: str) -> bool: ...
    def public_launch_status(self, *, user_id: UUID | None = None, email: str | None = None) -> dict[str, Any]: ...
    def launch_workspace_creation_allowed(self, *, user_id: UUID, email: str | None) -> bool: ...
    def internal_launch_status(self, *, user_id: UUID) -> dict[str, Any]: ...
    def import_launch_qualification(self, *, user_id: UUID, report: dict[str, Any]) -> dict[str, Any]: ...
    def set_internal_launch_mode(self, *, user_id: UUID, launch_mode: str, release_id: str | None, reason: str) -> dict[str, Any]: ...
    def list_internal_launch_access(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]: ...
    def record_internal_launch_access(self, *, user_id: UUID, email: str, event_type: str, expires_at: datetime | None, reason: str) -> dict[str, Any]: ...
    def list_organization_members(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def create_organization_invite(self, *, tenant_id: UUID, actor_user_id: UUID, actor_role: TenantRole, email: str, role: str, account_access_mode: str, client_portal: bool, expires_days: int) -> dict[str, Any]: ...
    def list_organization_invites(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def revoke_organization_invite(self, *, tenant_id: UUID, invite_id: UUID, actor_user_id: UUID, actor_role: TenantRole) -> dict[str, Any]: ...
    def accept_organization_invite(self, *, token: str, principal_user_id: UUID, principal_email: str | None) -> dict[str, Any]: ...
    def update_organization_member(self, *, tenant_id: UUID, actor_user_id: UUID, actor_role: TenantRole, user_id: UUID, role: str, status: str, account_access_mode: str, client_portal: bool) -> dict[str, Any]: ...
    def record_member_account_access(self, *, tenant_id: UUID, actor_user_id: UUID, user_id: UUID, account_id: UUID, action: str, reason: str | None) -> dict[str, Any]: ...
    def member_account_access_matrix(self, *, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]: ...
    def list_client_workspaces(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def client_workspace_detail(self, *, tenant_id: UUID, workspace_id: UUID) -> dict[str, Any]: ...
    def record_client_workspace(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID | None, action: str, name: str, external_reference: str | None, notes: str | None) -> dict[str, Any]: ...
    def record_client_workspace_account(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID, account_id: UUID, action: str) -> dict[str, Any]: ...
    def record_client_workspace_member(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID, user_id: UUID, action: str) -> dict[str, Any]: ...
    def account_assignments(self, *, tenant_id: UUID, account_id: UUID | None = None) -> list[dict[str, Any]]: ...
    def record_account_assignment(self, *, tenant_id: UUID, actor_user_id: UUID, account_id: UUID, user_id: UUID, responsibility: str, action: str, note: str | None) -> dict[str, Any]: ...
    def organization_activity(self, *, tenant_id: UUID, limit: int = 200) -> list[dict[str, Any]]: ...
    def customer_support_cases(self, *, tenant_id: UUID, user_id: UUID, include_all: bool, limit: int) -> list[dict[str, Any]]: ...
    def customer_support_case(self, *, tenant_id: UUID, user_id: UUID, case_id: UUID, include_all: bool) -> dict[str, Any]: ...
    def create_customer_support_case(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, category: str, subject: str, body: str) -> dict[str, Any]: ...
    def customer_support_case_event(self, *, tenant_id: UUID, user_id: UUID, case_id: UUID, include_all: bool, event_type: str, comment: str | None) -> dict[str, Any]: ...
    def security_data_overview(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]: ...
    def create_customer_data_request(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, request_type: str, reason: str) -> dict[str, Any]: ...
    def cancel_customer_data_request(self, *, tenant_id: UUID, user_id: UUID, request_id: UUID) -> dict[str, Any]: ...
    def security_configuration_export(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]: ...


class PostgresApiRepository:
    def __init__(self, core: PostgresRecoveryRepository) -> None:
        self.core = core

    def _connect(self):
        return self.core._connect()  # shared DSN/row factory; tenant context remains explicit

    @staticmethod
    def _set_user(cur: Any, user_id: UUID) -> None:
        cur.execute("SELECT set_config('recovery.user_id', %s, true)", (str(user_id),))

    def touch_user(self, *, user_id: UUID, email: str | None) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            cur.execute(
                """
                INSERT INTO recovery.app_users(id, email, last_seen_at)
                VALUES (%s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    email = COALESCE(EXCLUDED.email, recovery.app_users.email),
                    last_seen_at = now()
                RETURNING disabled
                """,
                (user_id, email),
            )
            return not bool(cur.fetchone()["disabled"])

    def list_memberships(self, *, user_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            cur.execute(
                """
                SELECT m.tenant_id, t.display_name AS tenant_name, t.slug AS tenant_slug, m.role, m.status,
                       m.account_access_mode, m.client_portal
                FROM recovery.tenant_memberships m
                JOIN recovery.tenants t ON t.id=m.tenant_id
                WHERE m.user_id=%s AND m.status='active'
                ORDER BY lower(t.display_name), m.tenant_id
                """,
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def accessible_account_ids(self, *, tenant_id: UUID, user_id: UUID) -> frozenset[UUID]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT role,status,account_access_mode FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s",(tenant_id,user_id))
            m=cur.fetchone()
            if m is None or m["status"]!="active": return frozenset()
            if m["role"] in {"owner","admin"} or m["account_access_mode"]=="all_accounts":
                cur.execute("SELECT id FROM recovery.google_ads_accounts WHERE tenant_id=%s",(tenant_id,))
                return frozenset(r["id"] for r in cur.fetchall())
            cur.execute(
                """
                WITH direct_latest AS (
                  SELECT DISTINCT ON (account_id) account_id,event_type
                  FROM recovery.member_account_access_events
                  WHERE tenant_id=%s AND user_id=%s
                  ORDER BY account_id,occurred_at DESC,id DESC
                ), member_ws AS (
                  SELECT workspace_id FROM (
                    SELECT DISTINCT ON (workspace_id) workspace_id,event_type
                    FROM recovery.client_workspace_member_events
                    WHERE tenant_id=%s AND user_id=%s
                    ORDER BY workspace_id,occurred_at DESC,id DESC
                  ) x WHERE event_type='grant'
                ), active_ws AS (
                  SELECT workspace_id FROM (
                    SELECT DISTINCT ON (workspace_id) workspace_id,event_type
                    FROM recovery.client_workspace_events
                    WHERE tenant_id=%s
                    ORDER BY workspace_id,occurred_at DESC,id DESC
                  ) x WHERE event_type<>'archived'
                ), ws_accounts AS (
                  SELECT workspace_id,account_id FROM (
                    SELECT DISTINCT ON (workspace_id,account_id) workspace_id,account_id,event_type
                    FROM recovery.client_workspace_account_events
                    WHERE tenant_id=%s
                    ORDER BY workspace_id,account_id,occurred_at DESC,id DESC
                  ) x WHERE event_type='link'
                )
                SELECT account_id FROM direct_latest WHERE event_type='grant'
                UNION
                SELECT wa.account_id FROM ws_accounts wa JOIN member_ws mw USING(workspace_id) JOIN active_ws aw USING(workspace_id)
                """,
                (tenant_id,user_id,tenant_id,user_id,tenant_id,tenant_id),
            )
            return frozenset(r["account_id"] for r in cur.fetchall())

    def membership(self, *, user_id: UUID, tenant_id: UUID) -> Membership | None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT role, status, account_access_mode, client_portal FROM recovery.tenant_memberships
                WHERE tenant_id=%s AND user_id=%s
                """,
                (tenant_id, user_id),
            )
            row = cur.fetchone()
            if row is None or row["status"] != "active":
                return None
        allowed=self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
        return Membership(tenant_id=tenant_id, role=TenantRole(row["role"]), status=row["status"], account_access_mode=row["account_access_mode"], client_portal=bool(row["client_portal"]), allowed_account_ids=allowed)

    def list_accounts(self, *, tenant_id: UUID, user_id: UUID | None = None) -> list[dict[str, Any]]:
        allowed=None if user_id is None else self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
        with self._connect() as conn, conn.cursor() as cur:
            if user_id is not None: self._set_user(cur,user_id)
            self.core._set_tenant(cur, tenant_id)
            if allowed is not None:
                if not allowed: return []
                cur.execute(
                    """SELECT id,customer_id,descriptive_name,currency_code,time_zone,account_status,test_account
                       FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id = ANY(%s) ORDER BY descriptive_name,customer_id""",
                    (tenant_id,list(allowed)),
                )
            else:
                cur.execute(
                    """SELECT id,customer_id,descriptive_name,currency_code,time_zone,account_status,test_account
                       FROM recovery.google_ads_accounts WHERE tenant_id=%s ORDER BY descriptive_name,customer_id""",
                    (tenant_id,),
                )
            return [dict(r) for r in cur.fetchall()]

    def ensure_account(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID | None = None) -> None:
        if user_id is not None and account_id not in self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id):
            raise ApiNotFound("Google Ads account not found")
        with self._connect() as conn, conn.cursor() as cur:
            if user_id is not None: self._set_user(cur,user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute("SELECT 1 FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id=%s",(tenant_id, account_id))
            if cur.fetchone() is None: raise ApiNotFound("Google Ads account not found")

    def enqueue_job(self, *, tenant_id: UUID, user_id: UUID, endpoint: str,
                    idempotency_key: str, job_type: JobType, payload: dict[str, Any],
                    operation_key: str | None = None) -> JobReceipt:
        request_hash = canonical_request_sha256(method="POST", path=endpoint, payload=payload)
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_user(cur, user_id)
                self.core._set_tenant(cur, tenant_id)
                self.core._advisory_xact_lock(cur, f"api-idem:{tenant_id}:{user_id}:{endpoint}:{idempotency_key}")
                cur.execute(
                    """
                    SELECT request_sha256, response_json
                    FROM recovery.api_idempotency_keys
                    WHERE tenant_id=%s AND user_id=%s AND endpoint=%s AND idempotency_key=%s
                    """,
                    (tenant_id, user_id, endpoint, idempotency_key),
                )
                existing = cur.fetchone()
                if existing is not None:
                    if existing["request_sha256"] != request_hash:
                        raise ApiConflict("Idempotency-Key was already used with a different request")
                    response = existing["response_json"]
                    return JobReceipt(
                        job_id=UUID(str(response["job_id"])),
                        job_type=JobType(response["job_type"]),
                        status=JobStatus(response["status"]),
                        idempotency_replay=True,
                    )

                if operation_key is not None:
                    op = operation_key.strip()
                    if not op or len(op) > 200:
                        raise ValueError("operation_key must be 1..200 characters when supplied")
                    self.core._advisory_xact_lock(cur, f"job-operation:{tenant_id}:{job_type.value}:{op}")
                    cur.execute(
                        """
                        SELECT id, status FROM recovery.api_jobs
                        WHERE tenant_id=%s AND job_type=%s AND operation_key=%s
                        LIMIT 1
                        """,
                        (tenant_id, job_type.value, op),
                    )
                    if cur.fetchone() is not None:
                        raise ApiConflict("this logical operation already has a durable job; reuse its original idempotency key")
                    operation_key = op

                job_id = uuid4()
                cur.execute(
                    """
                    INSERT INTO recovery.api_jobs(
                        id, tenant_id, job_type, status, payload, requested_by, endpoint, operation_key,
                        idempotency_key, request_sha256, available_at
                    ) VALUES (%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (job_id, tenant_id, job_type.value, self._json(payload), user_id, endpoint, operation_key,
                     idempotency_key, request_hash, now),
                )
                response = {"job_id": str(job_id), "job_type": job_type.value, "status": "queued"}
                cur.execute(
                    """
                    INSERT INTO recovery.api_idempotency_keys(
                        tenant_id, user_id, endpoint, idempotency_key, request_sha256,
                        response_status, response_json
                    ) VALUES (%s,%s,%s,%s,%s,202,%s)
                    """,
                    (tenant_id, user_id, endpoint, idempotency_key, request_hash,
                     self._json(response)),
                )
                return JobReceipt(job_id=job_id, job_type=job_type, status=JobStatus.QUEUED)

    @staticmethod
    def _json(value: Any):
        try:
            from psycopg.types.json import Jsonb
            return Jsonb(value)
        except ImportError:  # pragma: no cover
            return value

    @staticmethod
    def _truth_projection(row: dict[str, Any], previous_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload=dict(row["payload"] or {})
        submitted_at=datetime.fromisoformat(str(payload.get("created_at") or row["created_at"].isoformat()).replace("Z","+00:00"))
        truth=parse_business_truth_payload(payload,submitted_by=str(payload.get("created_by") or row["created_by"]),submitted_at=submitted_at)
        readiness={}
        for claim in TruthClaim:
            report=truth.readiness_for(claim)
            readiness[claim.value]={"ready":report.ready,"issues":[{"code":i.code,"message":i.message,"blocker":i.blocker} for i in report.issues]}
        ignored={"version","created_at","created_by","supersedes_version"}
        changed=[]
        if previous_payload is not None:
            for key in sorted((set(payload)|set(previous_payload))-ignored):
                if payload.get(key)!=previous_payload.get(key): changed.append(key)
        return {
            "id":row["id"],"account_id":row["account_id"],"truth_fingerprint":row["truth_fingerprint"],
            "schema_version":row["schema_version"],"version":int(payload.get("version") or row.get("business_version") or 0),
            "business_id":payload.get("business_id"),"business_name":payload.get("business_name"),
            "supersedes_version":payload.get("supersedes_version"),"created_by":row["created_by"],"created_at":row["created_at"],
            "offer_count":len(payload.get("offers") or []),"non_offer_count":len(payload.get("explicit_non_offers") or []),
            "intent_policy_count":len(payload.get("intent_policies") or []),"audience_policy_count":len(payload.get("audience_policies") or []),
            "service_area_count":len((payload.get("geo_policy") or {}).get("included_areas") or []),
            "outcome_count":len(payload.get("outcomes") or []),"protected_query_count":len(payload.get("protected_queries") or []),
            "readiness":readiness,"changed_sections":changed,"payload":payload,
        }

    def business_truth_versions(self, *, tenant_id: UUID, account_id: UUID, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200: raise ValueError("limit must be between 1 and 200")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT id,account_id,truth_fingerprint,schema_version,business_version,payload,created_by,created_at
                           FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s
                           ORDER BY business_version DESC,created_at DESC,id DESC LIMIT %s""",(tenant_id,account_id,limit))
            rows=[dict(r) for r in cur.fetchall()]
        projected=[]
        for idx,row in enumerate(rows):
            previous=rows[idx+1]["payload"] if idx+1 < len(rows) else None
            projected.append(self._truth_projection(row,dict(previous) if previous is not None else None))
        return projected

    def business_truth_version(self, *, tenant_id: UUID, account_id: UUID, snapshot_id: UUID | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            if snapshot_id is None:
                cur.execute("""SELECT id,account_id,truth_fingerprint,schema_version,business_version,payload,created_by,created_at
                               FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s
                               ORDER BY business_version DESC,created_at DESC,id DESC LIMIT 1""",(tenant_id,account_id))
            else:
                cur.execute("""SELECT id,account_id,truth_fingerprint,schema_version,business_version,payload,created_by,created_at
                               FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s AND id=%s""",(tenant_id,account_id,snapshot_id))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("Business Truth snapshot not found")
            payload=dict(row["payload"] or {})
            prev=None
            version=int(payload.get("version") or row["business_version"] or 0)
            if version>1:
                cur.execute("""SELECT payload FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s AND business_version=%s LIMIT 1""",(tenant_id,account_id,version-1))
                p=cur.fetchone(); prev=dict(p["payload"]) if p is not None else None
            return self._truth_projection(dict(row),prev)

    def save_business_truth(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID, endpoint: str,
                            idempotency_key: str, request_payload: dict[str, Any],
                            snapshot: BusinessTruthSnapshot) -> tuple[UUID, str, int, bool]:
        request_hash = canonical_request_sha256(method="POST", path=endpoint, payload=request_payload)
        payload = canonical_payload(snapshot)
        digest = payload_sha256(snapshot)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute("SELECT 1 FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id=%s", (tenant_id, account_id))
            if cur.fetchone() is None:
                raise ApiNotFound("Google Ads account not found")
            self.core._advisory_xact_lock(cur, f"api-idem:{tenant_id}:{user_id}:{endpoint}:{idempotency_key}")
            cur.execute(
                """
                SELECT request_sha256, response_json
                FROM recovery.api_idempotency_keys
                WHERE tenant_id=%s AND user_id=%s AND endpoint=%s AND idempotency_key=%s
                """,
                (tenant_id, user_id, endpoint, idempotency_key),
            )
            prior = cur.fetchone()
            if prior is not None:
                if prior["request_sha256"] != request_hash:
                    raise ApiConflict("Idempotency-Key was already used with a different request")
                response = prior["response_json"]
                return (
                    UUID(str(response["truth_snapshot_id"])),
                    str(response["truth_fingerprint"]),
                    int(response["version"]),
                    True,
                )

            self.core._advisory_xact_lock(cur, f"business-truth:{tenant_id}:{account_id}:{snapshot.business_id}")
            cur.execute(
                """
                SELECT id, truth_fingerprint, business_version
                FROM recovery.business_truth_snapshots
                WHERE tenant_id=%s AND account_id=%s AND business_id=%s
                ORDER BY business_version DESC LIMIT 1
                """,
                (tenant_id, account_id, snapshot.business_id),
            )
            latest = cur.fetchone()
            if latest is None:
                if snapshot.version != 1 or snapshot.supersedes_version is not None:
                    raise ApiConflict("first Business Truth snapshot must be version 1 without supersedes_version")
            else:
                expected_version = int(latest["business_version"]) + 1
                if snapshot.version != expected_version:
                    raise ApiConflict(f"Business Truth version must be {expected_version}")
                if snapshot.supersedes_version != int(latest["business_version"]):
                    raise ApiConflict("supersedes_version must reference the current Business Truth version")

            snapshot_id = uuid4()
            cur.execute(
                """
                INSERT INTO recovery.business_truth_snapshots(
                    id, tenant_id, account_id, truth_fingerprint, schema_version, payload_sha256,
                    payload, created_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (snapshot_id, tenant_id, account_id, snapshot.fingerprint_sha256, snapshot.schema_version,
                 digest, self._json(payload), snapshot.created_by),
            )
            response = {
                "truth_snapshot_id": str(snapshot_id),
                "truth_fingerprint": snapshot.fingerprint_sha256,
                "version": snapshot.version,
            }
            cur.execute(
                """
                INSERT INTO recovery.api_idempotency_keys(
                    tenant_id, user_id, endpoint, idempotency_key, request_sha256,
                    response_status, response_json
                ) VALUES (%s,%s,%s,%s,%s,201,%s)
                """,
                (tenant_id, user_id, endpoint, idempotency_key, request_hash, self._json(response)),
            )
            return snapshot_id, snapshot.fingerprint_sha256, snapshot.version, False

    def validate_analysis_inputs(self, *, tenant_id: UUID, account_id: UUID,
                                 sync_run_id: UUID, truth_snapshot_id: UUID, as_of: date) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT s.status AS sync_status, s.window_end
                FROM recovery.sync_runs s
                JOIN recovery.google_ads_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.account_id
                WHERE s.tenant_id=%s AND s.id=%s AND s.account_id=%s
                """,
                (tenant_id, sync_run_id, account_id),
            )
            sync = cur.fetchone()
            if sync is None:
                raise ApiNotFound("sync run/account combination not found")
            if sync["sync_status"] != "completed":
                raise ApiConflict("analysis requires a completed sync run")
            if as_of < sync["window_end"]:
                raise ApiConflict("analysis as_of cannot precede the synced observation window")
            cur.execute(
                "SELECT 1 FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND id=%s AND account_id=%s",
                (tenant_id, truth_snapshot_id, account_id),
            )
            if cur.fetchone() is None:
                raise ApiNotFound("business truth snapshot not found for this Google Ads account")

    def list_findings(self, *, tenant_id: UUID, analysis_run_id: UUID | None,
                      kind: str | None, limit: int, account_id: UUID | None = None) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        allowed = {"financial_finding", "negative_keyword_proposal", "semantic_assessment", "business_fit_decision"}
        if kind is not None and kind not in allowed:
            raise ValueError("unsupported finding kind")
        clauses = ["a.tenant_id=%s"]
        params: list[Any] = [tenant_id]
        if analysis_run_id is not None:
            clauses.append("a.analysis_run_id=%s")
            params.append(analysis_run_id)
        if account_id is not None:
            clauses.append("r.account_id=%s")
            params.append(account_id)
        if kind is not None:
            clauses.append("a.artifact_kind=%s")
            params.append(kind)
        else:
            clauses.append("a.artifact_kind IN ('financial_finding','negative_keyword_proposal')")
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                f"""
                SELECT a.id AS artifact_id, a.analysis_run_id, a.artifact_kind, a.external_id,
                       a.artifact_fingerprint, a.currency_code, a.money_micros, a.payload, a.created_at
                FROM recovery.analysis_artifacts a
                JOIN recovery.analysis_runs r
                  ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
                WHERE {' AND '.join(clauses)}
                ORDER BY a.created_at DESC, a.id DESC LIMIT %s
                """,
                tuple(params),
            )
            return [dict(r) for r in cur.fetchall()]

    def record_proposal_decision(self, *, tenant_id: UUID, proposal_artifact_id: UUID,
                                 proposal_fingerprint: str, decision: str,
                                 actor: str, note: str | None) -> UUID:
        if decision not in {"approved", "rejected"}:
            raise ValueError("unsupported decision")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"proposal-decision:{tenant_id}:{proposal_artifact_id}")
            cur.execute(
                """
                SELECT artifact_fingerprint, artifact_kind, payload, analysis_run_id
                FROM recovery.analysis_artifacts
                WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, proposal_artifact_id),
            )
            artifact = cur.fetchone()
            if artifact is None:
                raise ApiNotFound("proposal not found")
            if artifact["artifact_kind"] != "negative_keyword_proposal":
                raise ApiConflict("artifact is not a negative-keyword proposal")
            if artifact["artifact_fingerprint"] != proposal_fingerprint:
                raise ApiConflict("proposal fingerprint does not match stored artifact")
            if decision == "approved":
                cur.execute("SELECT account_id FROM recovery.analysis_runs WHERE tenant_id=%s AND id=%s",(tenant_id,artifact["analysis_run_id"]))
                run=cur.fetchone()
                if run is None: raise ApiConflict("proposal analysis source is missing")
                proposal_truth=str((artifact["payload"] or {}).get("truth_fingerprint") or "")
                cur.execute("SELECT truth_fingerprint FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s ORDER BY business_version DESC,created_at DESC,id DESC LIMIT 1",(tenant_id,run["account_id"]))
                latest_truth=cur.fetchone()
                if latest_truth is None or str(latest_truth["truth_fingerprint"]) != proposal_truth:
                    raise ApiConflict("cannot approve stale proposal after Business Truth changed")
                cur.execute("SELECT id FROM recovery.analysis_runs WHERE tenant_id=%s AND account_id=%s AND status='completed' ORDER BY completed_at DESC NULLS LAST,started_at DESC,id DESC LIMIT 1",(tenant_id,run["account_id"]))
                latest_analysis=cur.fetchone()
                if latest_analysis is None or latest_analysis["id"] != artifact["analysis_run_id"]:
                    raise ApiConflict("cannot approve stale proposal after newer analysis")
                cur.execute("SELECT event_type FROM recovery.recovery_case_events WHERE tenant_id=%s AND proposal_artifact_id=%s AND event_type IN ('closed','reopened') ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,proposal_artifact_id))
                case_state=cur.fetchone()
                if case_state and case_state["event_type"] == "closed":
                    raise ApiConflict("closed Recovery Case must be reopened before approval")
                gate=self._case_measurement_gate(cur,tenant_id=tenant_id,account_id=run["account_id"])
                if not gate["conversion_claims_allowed"]:
                    raise ApiConflict("Measurement Integrity does not currently allow conversion-dependent action approval")
            cur.execute(
                """
                SELECT id, decision, proposal_fingerprint FROM recovery.proposal_decision_events
                WHERE tenant_id=%s AND proposal_artifact_id=%s
                ORDER BY decided_at DESC, id DESC LIMIT 1
                """,
                (tenant_id, proposal_artifact_id),
            )
            existing = cur.fetchone()
            if existing is not None:
                if existing["decision"] == decision and existing["proposal_fingerprint"] == proposal_fingerprint:
                    return existing["id"]
                raise ApiConflict("proposal already has a different immutable decision event")

            event_id = uuid4()
            now = datetime.now(timezone.utc)
            payload = {
                "proposal_artifact_id": str(proposal_artifact_id),
                "proposal_fingerprint": proposal_fingerprint,
                "decision": decision,
                "decided_by": actor,
                "decided_at": now.isoformat(),
                "note": note,
            }
            event_fp = payload_sha256(payload)
            cur.execute(
                """
                INSERT INTO recovery.proposal_decision_events(
                    id, tenant_id, proposal_artifact_id, proposal_fingerprint,
                    decision, decided_by, decided_at, note, event_fingerprint, payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (event_id, tenant_id, proposal_artifact_id, proposal_fingerprint,
                 decision, actor, now, note, event_fp, self._json(payload)),
            )
            return event_id

    def proposal_execution_payload(self, *, tenant_id: UUID, proposal_artifact_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT a.artifact_fingerprint, a.payload, a.analysis_run_id,
                       r.account_id, d.id AS approval_event_id, d.decision
                FROM recovery.analysis_artifacts a
                JOIN recovery.analysis_runs r
                  ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
                LEFT JOIN LATERAL (
                    SELECT id, decision FROM recovery.proposal_decision_events d
                    WHERE d.tenant_id=a.tenant_id AND d.proposal_artifact_id=a.id
                    ORDER BY d.decided_at DESC, d.id DESC LIMIT 1
                ) d ON true
                WHERE a.tenant_id=%s AND a.id=%s AND a.artifact_kind='negative_keyword_proposal'
                """,
                (tenant_id, proposal_artifact_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ApiNotFound("proposal not found")
            if row["decision"] != "approved":
                raise ApiConflict("proposal must have an approved decision before execution")
            cur.execute("SELECT event_type FROM recovery.recovery_case_events WHERE tenant_id=%s AND proposal_artifact_id=%s AND event_type IN ('closed','reopened') ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,proposal_artifact_id))
            case_state=cur.fetchone()
            if case_state and case_state["event_type"] == "closed":
                raise ApiConflict("closed Recovery Case must be reopened before execution")
            proposal_truth=str((row["payload"] or {}).get("truth_fingerprint") or "")
            cur.execute(
                """SELECT truth_fingerprint FROM recovery.business_truth_snapshots
                   WHERE tenant_id=%s AND account_id=%s
                   ORDER BY business_version DESC,created_at DESC,id DESC LIMIT 1""",
                (tenant_id,row["account_id"]),
            )
            latest_truth=cur.fetchone()
            if latest_truth is None or str(latest_truth["truth_fingerprint"]) != proposal_truth:
                raise ApiConflict("proposal is stale because Business Truth changed; analyze again")
            cur.execute(
                """SELECT id FROM recovery.analysis_runs
                   WHERE tenant_id=%s AND account_id=%s AND status='completed'
                   ORDER BY completed_at DESC NULLS LAST,started_at DESC,id DESC LIMIT 1""",
                (tenant_id,row["account_id"]),
            )
            latest_analysis=cur.fetchone()
            if latest_analysis is None or latest_analysis["id"] != row["analysis_run_id"]:
                raise ApiConflict("proposal is stale because a newer completed analysis exists; review the latest evidence")
            gate=self._case_measurement_gate(cur,tenant_id=tenant_id,account_id=row["account_id"])
            if not gate["conversion_claims_allowed"]:
                raise ApiConflict("Measurement Integrity does not currently allow conversion-dependent Google Ads mutation")
            cur.execute(
                """
                SELECT 1 FROM recovery.mutation_events
                WHERE tenant_id=%s AND proposal_artifact_id=%s AND event_type='applied'
                LIMIT 1
                """,
                (tenant_id, proposal_artifact_id),
            )
            if cur.fetchone() is not None:
                raise ApiConflict("proposal has already been applied; create a new proposal for another application")
            return {
                "proposal_artifact_id": str(proposal_artifact_id),
                "proposal_fingerprint": row["artifact_fingerprint"],
                "approval_event_id": str(row["approval_event_id"]),
                "proposal": row["payload"],
            }

    def proposal_rollback_payload(self, *, tenant_id: UUID, proposal_artifact_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT m.id AS mutation_event_id, m.resource_name, m.payload, m.occurred_at
                FROM recovery.mutation_events m
                WHERE m.tenant_id=%s AND m.proposal_artifact_id=%s AND m.event_type='applied'
                ORDER BY m.occurred_at DESC, m.id DESC LIMIT 1
                """,
                (tenant_id, proposal_artifact_id),
            )
            applied = cur.fetchone()
            if applied is None or not applied["resource_name"]:
                raise ApiConflict("proposal has no applied Google resource to roll back")
            cur.execute(
                """
                SELECT 1 FROM recovery.mutation_events
                WHERE tenant_id=%s AND proposal_artifact_id=%s AND event_type='rolled_back'
                  AND occurred_at >= %s
                LIMIT 1
                """,
                (tenant_id, proposal_artifact_id, applied["occurred_at"]),
            )
            if cur.fetchone() is not None:
                raise ApiConflict("applied Google resource is already rolled back")
            return {
                "proposal_artifact_id": str(proposal_artifact_id),
                "applied_mutation_event_id": str(applied["mutation_event_id"]),
                "resource_name": applied["resource_name"],
            }

    def get_job(self, *, tenant_id: UUID, user_id: UUID, job_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT id AS job_id, job_type, status, attempts, max_attempts, result,
                       failure_code, created_at, started_at, completed_at
                FROM recovery.api_jobs WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, job_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ApiNotFound("job not found")
            return dict(row)

    def list_ledger(self, *, tenant_id: UUID, limit: int, account_id: UUID | None = None) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            if account_id is None:
                cur.execute(
                    """
                    SELECT id AS entry_id, analysis_run_id, currency_code,
                           historical_candidate_micros, projected_prevented_micros,
                           observed_post_action_query_spend_micros, verified_recovery_micros,
                           causal_status, created_at
                    FROM recovery.recovery_ledger_entries
                    WHERE tenant_id=%s
                    ORDER BY created_at DESC, id DESC LIMIT %s
                    """,
                    (tenant_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT l.id AS entry_id, l.analysis_run_id, l.currency_code,
                           l.historical_candidate_micros, l.projected_prevented_micros,
                           l.observed_post_action_query_spend_micros, l.verified_recovery_micros,
                           l.causal_status, l.created_at
                    FROM recovery.recovery_ledger_entries l
                    JOIN recovery.analysis_runs a
                      ON a.tenant_id=l.tenant_id AND a.id=l.analysis_run_id
                    WHERE l.tenant_id=%s AND a.account_id=%s
                    ORDER BY l.created_at DESC, l.id DESC LIMIT %s
                    """,
                    (tenant_id, account_id, limit),
                )
            return [dict(r) for r in cur.fetchall()]

    def list_proposals(self, *, tenant_id: UUID, account_id: UUID,
                       analysis_run_id: UUID | None, limit: int) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        clauses = ["a.tenant_id=%s", "r.account_id=%s", "a.artifact_kind='negative_keyword_proposal'"]
        params: list[Any] = [tenant_id, account_id]
        if analysis_run_id is not None:
            clauses.append("a.analysis_run_id=%s")
            params.append(analysis_run_id)
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                f"""
                SELECT a.id AS artifact_id, a.analysis_run_id, a.artifact_fingerprint,
                       a.currency_code, a.money_micros, a.payload, a.created_at,
                       d.id AS decision_event_id, d.decision, d.decided_at,
                       m.event_type AS mutation_event_type, m.resource_name,
                       m.occurred_at AS mutation_occurred_at
                FROM recovery.analysis_artifacts a
                JOIN recovery.analysis_runs r
                  ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
                LEFT JOIN LATERAL (
                    SELECT id, decision, decided_at
                    FROM recovery.proposal_decision_events d
                    WHERE d.tenant_id=a.tenant_id AND d.proposal_artifact_id=a.id
                    ORDER BY d.decided_at DESC, d.id DESC LIMIT 1
                ) d ON true
                LEFT JOIN LATERAL (
                    SELECT event_type, resource_name, occurred_at
                    FROM recovery.mutation_events m
                    WHERE m.tenant_id=a.tenant_id AND m.proposal_artifact_id=a.id
                    ORDER BY m.occurred_at DESC, m.id DESC LIMIT 1
                ) m ON true
                WHERE {' AND '.join(clauses)}
                ORDER BY a.created_at DESC, a.id DESC LIMIT %s
                """,
                tuple(params),
            )
            return [dict(r) for r in cur.fetchall()]

    def workspace_summary(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT id, customer_id, descriptive_name, currency_code, time_zone,
                       account_status, test_account
                FROM recovery.google_ads_accounts
                WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, account_id),
            )
            account = cur.fetchone()
            if account is None:
                raise ApiNotFound("Google Ads account not found")

            cur.execute(
                """
                SELECT id, status, started_at, completed_at, window_start, window_end,
                       currency_code, time_zone
                FROM recovery.sync_runs
                WHERE tenant_id=%s AND account_id=%s
                ORDER BY started_at DESC, id DESC LIMIT 1
                """,
                (tenant_id, account_id),
            )
            sync = cur.fetchone()

            cur.execute(
                """
                SELECT id, created_at, truth_fingerprint, business_version, business_id
                FROM recovery.business_truth_snapshots
                WHERE tenant_id=%s AND account_id=%s
                ORDER BY business_version DESC, created_at DESC, id DESC LIMIT 1
                """,
                (tenant_id, account_id),
            )
            truth = cur.fetchone()

            cur.execute(
                """
                SELECT id, status, started_at, completed_at, as_of, sync_run_id, truth_snapshot_id
                FROM recovery.analysis_runs
                WHERE tenant_id=%s AND account_id=%s
                ORDER BY started_at DESC, id DESC LIMIT 1
                """,
                (tenant_id, account_id),
            )
            analysis = cur.fetchone()

            summary = None
            if analysis is not None:
                cur.execute(
                    """
                    SELECT currency_code, potentially_avoidable_observed_micros,
                           visible_search_term_micros, unobserved_search_micros, coverage_band,
                           query_count, review_required_count, proposal_count, created_at
                    FROM recovery.analysis_summaries
                    WHERE tenant_id=%s AND analysis_run_id=%s
                    """,
                    (tenant_id, analysis["id"]),
                )
                summary = cur.fetchone()

            ready = 0
            if analysis is not None:
                cur.execute(
                    """
                    SELECT count(*) AS n
                    FROM recovery.analysis_artifacts a
                    WHERE a.tenant_id=%s AND a.analysis_run_id=%s
                      AND a.artifact_kind='negative_keyword_proposal'
                      AND a.payload->>'disposition'='ready_for_approval'
                      AND NOT EXISTS (
                          SELECT 1 FROM recovery.proposal_decision_events d
                          WHERE d.tenant_id=a.tenant_id AND d.proposal_artifact_id=a.id
                      )
                    """,
                    (tenant_id, analysis["id"]),
                )
                ready = int(cur.fetchone()["n"])

            cur.execute(
                """
                WITH latest_per_mutation AS (
                    SELECT DISTINCT ON (l.mutation_event_id)
                           l.mutation_event_id, l.verified_recovery_micros
                    FROM recovery.recovery_ledger_entries l
                    JOIN recovery.analysis_runs a
                      ON a.tenant_id=l.tenant_id AND a.id=l.analysis_run_id
                    WHERE l.tenant_id=%s AND a.account_id=%s AND l.mutation_event_id IS NOT NULL
                      AND l.causal_status='verified' AND l.verified_recovery_micros > 0
                    ORDER BY l.mutation_event_id, l.created_at DESC, l.id DESC
                )
                SELECT COALESCE(sum(verified_recovery_micros),0)::bigint AS total, count(*)::int AS n
                FROM latest_per_mutation
                """,
                (tenant_id, account_id),
            )
            recovery = cur.fetchone()

            def stage(row, *, kind):
                if row is None:
                    return {"id": None, "status": "not_started", "started_at": None, "completed_at": None, "detail": {}}
                if kind == "truth":
                    return {
                        "id": row["id"], "status": "available", "started_at": row["created_at"],
                        "completed_at": row["created_at"],
                        "detail": {"version": row["business_version"], "truth_fingerprint": row["truth_fingerprint"], "business_id": row["business_id"]},
                    }
                detail = {}
                if kind == "sync":
                    detail = {"window_start": row["window_start"].isoformat(), "window_end": row["window_end"].isoformat(), "currency_code": row["currency_code"], "time_zone": row["time_zone"]}
                elif kind == "analysis":
                    detail = {"as_of": row["as_of"].isoformat(), "sync_run_id": str(row["sync_run_id"]), "truth_snapshot_id": str(row["truth_snapshot_id"])}
                return {"id": row["id"], "status": row["status"], "started_at": row["started_at"], "completed_at": row["completed_at"], "detail": detail}

            return {
                "account": dict(account),
                "latest_sync": stage(sync, kind="sync"),
                "latest_truth": stage(truth, kind="truth"),
                "latest_analysis": stage(analysis, kind="analysis"),
                "currency_code": (summary["currency_code"] if summary else account["currency_code"]),
                "potentially_avoidable_observed_micros": int(summary["potentially_avoidable_observed_micros"] if summary else 0),
                "visible_search_term_micros": int(summary["visible_search_term_micros"] if summary else 0),
                "unobserved_search_micros": int(summary["unobserved_search_micros"] if summary else 0),
                "coverage_band": (summary["coverage_band"] if summary else None),
                "query_count": int(summary["query_count"] if summary else 0),
                "review_required_count": int(summary["review_required_count"] if summary else 0),
                "proposal_count": int(summary["proposal_count"] if summary else 0),
                "ready_for_approval_count": ready,
                "verified_recovery_micros": int(recovery["total"]),
                "verified_recovery_entries": int(recovery["n"]),
                "last_updated_at": (summary["created_at"] if summary else (analysis["completed_at"] if analysis else (sync["completed_at"] if sync else None))),
            }

    def billing_current(self, *, tenant_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT provider, provider_subscription_id, provider_plan_id, plan_key,
                       provider_status, entitlement_state, current_start, current_end,
                       provider_customer_id,payment_method,total_count,paid_count,remaining_count,
                       has_scheduled_changes,change_scheduled_at,charge_at,ended_at,grace_until,
                       reconciled_at, updated_at
                FROM recovery.billing_tenant_current
                WHERE tenant_id=%s
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def billing_checkout_by_request(self, *, tenant_id: UUID, user_id: UUID, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """SELECT * FROM recovery.billing_checkout_intents
                   WHERE tenant_id=%s AND requested_by=%s AND idempotency_key=%s""",
                (tenant_id, user_id, idempotency_key),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def prepare_billing_checkout(self, *, tenant_id: UUID, user_id: UUID, endpoint: str,
                                 idempotency_key: str, plan_key: str) -> tuple[dict[str, Any], bool]:
        request_hash = canonical_request_sha256(method="POST", path=endpoint, payload={"plan_key": plan_key})
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            self.core._advisory_xact_lock(cur, f"billing-checkout:{tenant_id}:{user_id}:{idempotency_key}")
            cur.execute(
                """
                SELECT * FROM recovery.billing_checkout_intents
                WHERE tenant_id=%s AND requested_by=%s AND idempotency_key=%s
                """, (tenant_id, user_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_hash:
                    raise ApiConflict("Idempotency-Key was already used with a different billing request")
                return dict(existing), True
            intent_id = uuid4()
            cur.execute(
                """
                INSERT INTO recovery.billing_checkout_intents(
                    id, tenant_id, requested_by, plan_key, idempotency_key, request_sha256, state
                ) VALUES (%s,%s,%s,%s,%s,%s,'prepared')
                RETURNING *
                """, (intent_id, tenant_id, user_id, plan_key, idempotency_key, request_hash),
            )
            return dict(cur.fetchone()), False

    def set_billing_checkout_state(self, *, tenant_id: UUID, intent_id: UUID, state: str,
                                   provider_subscription_id: str | None = None, provider_plan_id: str | None = None,
                                   checkout_url: str | None = None, failure_code: str | None = None) -> None:
        allowed = {"prepared", "in_flight", "provider_created", "ambiguous", "failed"}
        if state not in allowed:
            raise ValueError("invalid billing checkout state")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                UPDATE recovery.billing_checkout_intents
                SET state=%s,
                    provider_subscription_id=COALESCE(%s, provider_subscription_id),
                    provider_plan_id=COALESCE(%s, provider_plan_id),
                    checkout_url=COALESCE(%s, checkout_url),
                    failure_code=%s,
                    updated_at=now()
                WHERE tenant_id=%s AND id=%s
                """,
                (state, provider_subscription_id, provider_plan_id, checkout_url,
                 failure_code, tenant_id, intent_id),
            )
            if cur.rowcount != 1:
                raise ApiNotFound("billing checkout intent not found")

    def billing_checkout_by_provider(self, *, tenant_id: UUID, provider_subscription_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """SELECT * FROM recovery.billing_checkout_intents
                   WHERE tenant_id=%s AND provider_subscription_id=%s""",
                (tenant_id, provider_subscription_id),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def latest_billing_checkout(self, *, tenant_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """SELECT * FROM recovery.billing_checkout_intents
                   WHERE tenant_id=%s ORDER BY created_at DESC, id DESC LIMIT 1""",
                (tenant_id,),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def billing_webhook_has_result(self, *, webhook_event_id: UUID) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM recovery.billing_webhook_results WHERE webhook_event_id=%s",
                (webhook_event_id,),
            )
            return cur.fetchone() is not None

    def claim_billing_webhook(self, *, provider_event_id: str, raw_body_sha256: str) -> tuple[UUID, bool]:
        event_id = uuid4()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recovery.billing_webhook_events(
                    id, provider, provider_event_id, raw_body_sha256, signature_verified
                ) VALUES (%s,'razorpay',%s,%s,true)
                ON CONFLICT (provider, provider_event_id) DO NOTHING
                RETURNING id
                """, (event_id, provider_event_id, raw_body_sha256),
            )
            row = cur.fetchone()
            if row is not None:
                return UUID(str(row["id"])), True
            cur.execute(
                "SELECT id, raw_body_sha256 FROM recovery.billing_webhook_events WHERE provider='razorpay' AND provider_event_id=%s",
                (provider_event_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("webhook deduplication invariant failed")
            if existing["raw_body_sha256"] != raw_body_sha256:
                raise ApiConflict("Razorpay event id was reused with different raw content")
            return UUID(str(existing["id"])), False

    def record_billing_webhook_result(self, *, webhook_event_id: UUID, tenant_id: UUID | None,
                                      provider_subscription_id: str | None, event_type: str | None,
                                      reconcile_status: str, error_code: str | None = None) -> None:
        if reconcile_status not in {"ignored", "reconciled", "unknown_subscription", "failed"}:
            raise ValueError("invalid billing webhook reconcile status")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recovery.billing_webhook_results(
                    id, webhook_event_id, tenant_id, provider_subscription_id,
                    event_type, reconcile_status, error_code
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (webhook_event_id) DO NOTHING
                """,
                (uuid4(), webhook_event_id, tenant_id, provider_subscription_id,
                 event_type, reconcile_status, error_code),
            )

    def reconcile_billing_subscription(self, *, tenant_id: UUID, subscription: ProviderSubscription,
                                       plan: BillingPlan, entitlement_state: EntitlementState, grace_until: datetime | None = None) -> UUID:
        import hashlib
        raw=json.dumps(subscription.raw,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        digest=hashlib.sha256(raw).hexdigest()
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            self.core._advisory_xact_lock(cur,f"billing-reconcile:{tenant_id}:{subscription.id}")
            snapshot_id=uuid4()
            cur.execute(
                """
                INSERT INTO recovery.billing_subscription_snapshots(
                    id,tenant_id,provider_subscription_id,provider_plan_id,plan_key,
                    provider_status,entitlement_state,current_start,current_end,quantity,
                    provider_payload,provider_payload_sha256,provider_customer_id,payment_method,
                    total_count,paid_count,remaining_count,has_scheduled_changes,change_scheduled_at,
                    charge_at,ended_at,grace_until
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,provider_subscription_id,provider_payload_sha256) DO NOTHING
                RETURNING id
                """,
                (snapshot_id,tenant_id,subscription.id,subscription.plan_id,plan.key,
                 subscription.status,entitlement_state.value,subscription.current_start,subscription.current_end,subscription.quantity,
                 self._json(subscription.raw),digest,subscription.customer_id,subscription.payment_method,
                 subscription.total_count,subscription.paid_count,subscription.remaining_count,subscription.has_scheduled_changes,
                 subscription.change_scheduled_at,subscription.charge_at,subscription.ended_at,grace_until),
            )
            inserted=cur.fetchone()
            if inserted is None:
                cur.execute("SELECT id FROM recovery.billing_subscription_snapshots WHERE tenant_id=%s AND provider_subscription_id=%s AND provider_payload_sha256=%s",(tenant_id,subscription.id,digest))
                inserted=cur.fetchone()
                if inserted is None: raise ApiConflict("billing snapshot deduplication failed")
            snapshot_id=UUID(str(inserted["id"]))
            cur.execute(
                """
                INSERT INTO recovery.billing_tenant_current(
                    tenant_id,provider_subscription_id,provider_plan_id,plan_key,provider_status,entitlement_state,
                    current_start,current_end,reconciled_snapshot_id,reconciled_at,updated_at,provider_customer_id,payment_method,
                    total_count,paid_count,remaining_count,has_scheduled_changes,change_scheduled_at,charge_at,ended_at,grace_until
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id) DO UPDATE SET
                    provider_subscription_id=EXCLUDED.provider_subscription_id,provider_plan_id=EXCLUDED.provider_plan_id,
                    plan_key=EXCLUDED.plan_key,provider_status=EXCLUDED.provider_status,entitlement_state=EXCLUDED.entitlement_state,
                    current_start=EXCLUDED.current_start,current_end=EXCLUDED.current_end,reconciled_snapshot_id=EXCLUDED.reconciled_snapshot_id,
                    provider_customer_id=EXCLUDED.provider_customer_id,payment_method=EXCLUDED.payment_method,total_count=EXCLUDED.total_count,
                    paid_count=EXCLUDED.paid_count,remaining_count=EXCLUDED.remaining_count,has_scheduled_changes=EXCLUDED.has_scheduled_changes,
                    change_scheduled_at=EXCLUDED.change_scheduled_at,charge_at=EXCLUDED.charge_at,ended_at=EXCLUDED.ended_at,grace_until=EXCLUDED.grace_until,
                    reconciled_at=now(),updated_at=now()
                """,
                (tenant_id,subscription.id,subscription.plan_id,plan.key,subscription.status,entitlement_state.value,
                 subscription.current_start,subscription.current_end,snapshot_id,subscription.customer_id,subscription.payment_method,
                 subscription.total_count,subscription.paid_count,subscription.remaining_count,subscription.has_scheduled_changes,
                 subscription.change_scheduled_at,subscription.charge_at,subscription.ended_at,grace_until),
            )
            return snapshot_id


    def billing_lifecycle_operation_by_request(self, *, tenant_id: UUID, user_id: UUID, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT id FROM recovery.billing_lifecycle_operations WHERE tenant_id=%s AND requested_by=%s AND idempotency_key=%s",(tenant_id,user_id,idempotency_key))
            row=cur.fetchone()
            return self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=UUID(str(row["id"]))) if row else None

    def prepare_billing_lifecycle_operation(self, *, tenant_id: UUID, user_id: UUID, endpoint: str, idempotency_key: str, operation_type: str, provider_subscription_id: str, target_plan_key: str | None, effective_at: datetime | None) -> tuple[dict[str, Any], bool]:
        allowed={"plan_change_cycle_end","cancel_plan_change","cancel_cycle_end"}
        if operation_type not in allowed: raise ValueError("invalid billing lifecycle operation")
        payload={"operation_type":operation_type,"provider_subscription_id":provider_subscription_id,"target_plan_key":target_plan_key,"effective_at":effective_at.isoformat() if effective_at else None}
        request_hash=canonical_request_sha256(method="POST",path=endpoint,payload=payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            self.core._advisory_xact_lock(cur,f"billing-lifecycle:{tenant_id}:{user_id}:{idempotency_key}")
            cur.execute("SELECT id,request_sha256 FROM recovery.billing_lifecycle_operations WHERE tenant_id=%s AND requested_by=%s AND idempotency_key=%s",(tenant_id,user_id,idempotency_key))
            existing=cur.fetchone()
            if existing:
                if existing["request_sha256"]!=request_hash: raise ApiConflict("Idempotency-Key was already used with a different billing lifecycle request")
                op_id=UUID(str(existing["id"])); replay=True
            else:
                op_id=uuid4(); replay=False
                cur.execute("""INSERT INTO recovery.billing_lifecycle_operations(id,tenant_id,requested_by,operation_type,provider_subscription_id,target_plan_key,idempotency_key,request_sha256,effective_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(op_id,tenant_id,user_id,operation_type,provider_subscription_id,target_plan_key,idempotency_key,request_hash,effective_at))
                cur.execute("INSERT INTO recovery.billing_lifecycle_events(tenant_id,operation_id,event_type,actor,payload) VALUES (%s,%s,'prepared',%s,%s)",(tenant_id,op_id,str(user_id),self._json(payload)))
        return self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=op_id),replay

    def append_billing_lifecycle_event(self, *, tenant_id: UUID, operation_id: UUID, event_type: str, actor: str, payload: dict[str, Any] | None = None) -> None:
        allowed={"prepared","in_flight","provider_observed","ambiguous","failed","reconciled"}
        if event_type not in allowed: raise ValueError("invalid billing lifecycle event")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT 1 FROM recovery.billing_lifecycle_operations WHERE tenant_id=%s AND id=%s",(tenant_id,operation_id))
            if cur.fetchone() is None: raise ApiNotFound("billing lifecycle operation not found")
            cur.execute("INSERT INTO recovery.billing_lifecycle_events(tenant_id,operation_id,event_type,actor,payload) VALUES (%s,%s,%s,%s,%s)",(tenant_id,operation_id,event_type,actor,self._json(payload or {})))

    def billing_lifecycle_operation(self, *, tenant_id: UUID, operation_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT * FROM recovery.billing_lifecycle_operations WHERE tenant_id=%s AND id=%s",(tenant_id,operation_id)); op=cur.fetchone()
            if op is None: raise ApiNotFound("billing lifecycle operation not found")
            cur.execute("SELECT id,event_type,actor,payload,occurred_at FROM recovery.billing_lifecycle_events WHERE tenant_id=%s AND operation_id=%s ORDER BY occurred_at,id",(tenant_id,operation_id)); events=[dict(r) for r in cur.fetchall()]
            state=events[-1]["event_type"] if events else "prepared"
            out=dict(op); out["state"]=state; out["events"]=events
            return out

    def latest_billing_lifecycle_operations(self, *, tenant_id: UUID, provider_subscription_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not 1<=limit<=200: raise ValueError("billing lifecycle limit must be between 1 and 200")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT id FROM recovery.billing_lifecycle_operations WHERE tenant_id=%s AND provider_subscription_id=%s ORDER BY created_at DESC,id DESC LIMIT %s",(tenant_id,provider_subscription_id,limit))
            ids=[UUID(str(r["id"])) for r in cur.fetchall()]
        return [self.billing_lifecycle_operation(tenant_id=tenant_id,operation_id=x) for x in ids]

    def record_billing_pending_change(self, *, tenant_id: UUID, subscription_id: str, pending: ProviderSubscription, target_plan: BillingPlan) -> UUID:
        raw=json.dumps(pending.raw,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); import hashlib; digest=hashlib.sha256(raw).hexdigest(); sid=uuid4()
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.billing_pending_change_snapshots(id,tenant_id,provider_subscription_id,provider_plan_id,target_plan_key,provider_payload,provider_payload_sha256)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (tenant_id,provider_subscription_id,provider_payload_sha256) DO NOTHING RETURNING id""",(sid,tenant_id,subscription_id,pending.plan_id,target_plan.key,self._json(pending.raw),digest))
            row=cur.fetchone()
            if row is None:
                cur.execute("SELECT id FROM recovery.billing_pending_change_snapshots WHERE tenant_id=%s AND provider_subscription_id=%s AND provider_payload_sha256=%s",(tenant_id,subscription_id,digest)); row=cur.fetchone()
                if row is None: raise ApiConflict("pending billing change deduplication failed")
            return UUID(str(row["id"]))

    def latest_billing_pending_change(self, *, tenant_id: UUID, subscription_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT * FROM recovery.billing_pending_change_snapshots WHERE tenant_id=%s AND provider_subscription_id=%s ORDER BY observed_at DESC,id DESC LIMIT 1",(tenant_id,subscription_id)); row=cur.fetchone()
            return dict(row) if row else None

    def record_billing_invoices(self, *, tenant_id: UUID, subscription_id: str, invoices: list[ProviderInvoice]) -> int:
        inserted=0
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            for inv in invoices:
                if inv.subscription_id!=subscription_id: raise ApiConflict("provider invoice belongs to another subscription")
                raw=json.dumps(inv.raw,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); import hashlib; digest=hashlib.sha256(raw).hexdigest()
                cur.execute("""INSERT INTO recovery.billing_invoice_snapshots(id,tenant_id,provider_subscription_id,provider_invoice_id,provider_payment_id,status,currency,amount,amount_paid,amount_due,issued_at,paid_at,provider_payload,provider_payload_sha256)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (tenant_id,provider_invoice_id,provider_payload_sha256) DO NOTHING RETURNING id""",(uuid4(),tenant_id,subscription_id,inv.id,inv.payment_id,inv.status,inv.currency,inv.amount,inv.amount_paid,inv.amount_due,inv.issued_at,inv.paid_at,self._json(inv.raw),digest))
                if cur.fetchone() is not None: inserted+=1
        return inserted

    def list_billing_invoices(self, *, tenant_id: UUID, subscription_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("invoice limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT DISTINCT ON (provider_invoice_id) provider_invoice_id,provider_payment_id,status,currency,amount,amount_paid,amount_due,issued_at,paid_at,observed_at
                           FROM recovery.billing_invoice_snapshots WHERE tenant_id=%s AND provider_subscription_id=%s
                           ORDER BY provider_invoice_id,observed_at DESC,id DESC""",(tenant_id,subscription_id)); rows=[dict(r) for r in cur.fetchall()]
        rows.sort(key=lambda r:(r.get("issued_at") or r["observed_at"],r["provider_invoice_id"]),reverse=True)
        return rows[:limit]

    def save_billing_profile(self, *, tenant_id: UUID, user_id: UUID, legal_name: str, billing_email: str, tax_country: str, tax_region: str | None, gstin: str | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.billing_profile_events(tenant_id,actor_user_id,legal_name,billing_email,tax_country,tax_region,gstin)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(tenant_id,user_id,legal_name,billing_email,tax_country,tax_region,gstin))
            return dict(cur.fetchone())

    def billing_profile(self, *, tenant_id: UUID) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT id,legal_name,billing_email,tax_country,tax_region,gstin,actor_user_id,occurred_at FROM recovery.billing_profile_events WHERE tenant_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,)); row=cur.fetchone()
            return dict(row) if row else None

    def billing_entitlement_history(self, *, tenant_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("history limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT id,provider_subscription_id,provider_plan_id,plan_key,provider_status,entitlement_state,current_start,current_end,payment_method,has_scheduled_changes,change_scheduled_at,grace_until,observed_at
                           FROM recovery.billing_subscription_snapshots WHERE tenant_id=%s ORDER BY observed_at DESC,id DESC LIMIT %s""",(tenant_id,limit))
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _active_billing_slots_with_cursor(cur: Any, *, tenant_id: UUID) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT DISTINCT ON (e.account_id) e.account_id,e.event_type,e.occurred_at,a.customer_id,a.descriptive_name
            FROM recovery.billing_account_slot_events e
            JOIN recovery.google_ads_accounts a ON a.tenant_id=e.tenant_id AND a.id=e.account_id
            WHERE e.tenant_id=%s
            ORDER BY e.account_id,e.occurred_at DESC,e.id DESC
            """,(tenant_id,),
        )
        return [dict(r) for r in cur.fetchall() if r["event_type"]=="assign"]

    def reserve_billing_account_slot(self, *, tenant_id: UUID, account_id: UUID, max_accounts: int) -> None:
        if max_accounts<=0: raise ValueError("max_accounts must be positive")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"billing-slots:{tenant_id}")
            active=self._active_billing_slots_with_cursor(cur,tenant_id=tenant_id)
            if any(UUID(str(x["account_id"]))==account_id for x in active):
                if len(active)>max_accounts:
                    ordered=sorted(active,key=lambda x:(x["occurred_at"],str(x["account_id"])))
                    allowed={UUID(str(x["account_id"])) for x in ordered[:max_accounts]}
                    if account_id not in allowed: raise ApiConflict("this Google Ads account is outside the current billing plan account limit")
                return
            if len(active)>=max_accounts: raise ApiConflict("billing plan Google Ads account limit reached")
            cur.execute("SELECT 1 FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id=%s",(tenant_id,account_id))
            if cur.fetchone() is None: raise ApiNotFound("Google Ads account not found")
            cur.execute("INSERT INTO recovery.billing_account_slot_events(tenant_id,account_id,event_type,actor,payload) VALUES (%s,%s,'assign','system:entitlement','{}'::jsonb)",(tenant_id,account_id))

    def billing_account_slot_allowed(self, *, tenant_id: UUID, account_id: UUID, max_accounts: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            active=sorted(self._active_billing_slots_with_cursor(cur,tenant_id=tenant_id),key=lambda x:(x["occurred_at"],str(x["account_id"])))
            allowed={UUID(str(x["account_id"])) for x in active[:max_accounts]}
            return account_id in allowed

    def list_billing_account_slots(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            rows=sorted(self._active_billing_slots_with_cursor(cur,tenant_id=tenant_id),key=lambda x:(x["occurred_at"],str(x["account_id"])))
            return rows

    def release_billing_account_slot(self, *, tenant_id: UUID, account_id: UUID, actor: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"billing-slots:{tenant_id}")
            active=self._active_billing_slots_with_cursor(cur,tenant_id=tenant_id)
            if not any(UUID(str(x["account_id"]))==account_id for x in active): raise ApiConflict("billing account slot is not active")
            cur.execute("INSERT INTO recovery.billing_account_slot_events(tenant_id,account_id,event_type,actor,payload) VALUES (%s,%s,'release',%s,'{}'::jsonb)",(tenant_id,account_id,actor))


    # --- Epic 1 product-shell repository methods ---

    def command_center(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        allowed=self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
        membership=self.membership(user_id=user_id,tenant_id=tenant_id)
        restricted=bool(membership and membership.account_access_mode!="all_accounts")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur, user_id)
            self.core._set_tenant(cur, tenant_id)
            cur.execute("SELECT display_name FROM recovery.tenants WHERE id=%s", (tenant_id,))
            tenant = cur.fetchone()
            if tenant is None:
                raise ApiNotFound("tenant not found")

            cur.execute(
                """
                SELECT a.id, a.customer_id, a.descriptive_name, a.currency_code, a.time_zone,
                       s.completed_at AS latest_sync_at,
                       an.completed_at AS latest_analysis_at,
                       sm.potentially_avoidable_observed_micros,
                       COALESCE(rr.verified_recovery_micros,0)::bigint AS verified_recovery_micros,
                       COALESCE(pr.ready_for_approval_count,0)::int AS ready_for_approval_count
                FROM recovery.google_ads_accounts a
                LEFT JOIN LATERAL (
                    SELECT completed_at FROM recovery.sync_runs s
                    WHERE s.tenant_id=a.tenant_id AND s.account_id=a.id AND s.status='completed'
                    ORDER BY completed_at DESC NULLS LAST, id DESC LIMIT 1
                ) s ON true
                LEFT JOIN LATERAL (
                    SELECT id, completed_at FROM recovery.analysis_runs r
                    WHERE r.tenant_id=a.tenant_id AND r.account_id=a.id AND r.status='completed'
                    ORDER BY completed_at DESC NULLS LAST, id DESC LIMIT 1
                ) an ON true
                LEFT JOIN LATERAL (
                    SELECT potentially_avoidable_observed_micros
                    FROM recovery.analysis_summaries x
                    WHERE x.tenant_id=a.tenant_id AND x.analysis_run_id=an.id
                    LIMIT 1
                ) sm ON true
                LEFT JOIN LATERAL (
                    SELECT COALESCE(sum(z.verified_recovery_micros),0)::bigint AS verified_recovery_micros
                    FROM (
                        SELECT DISTINCT ON (l.mutation_event_id)
                               l.mutation_event_id, l.verified_recovery_micros
                        FROM recovery.recovery_ledger_entries l
                        JOIN recovery.analysis_runs ar
                          ON ar.tenant_id=l.tenant_id AND ar.id=l.analysis_run_id
                        WHERE l.tenant_id=a.tenant_id AND ar.account_id=a.id
                          AND l.mutation_event_id IS NOT NULL
                          AND l.causal_status='verified' AND l.verified_recovery_micros > 0
                        ORDER BY l.mutation_event_id, l.created_at DESC, l.id DESC
                    ) z
                ) rr ON true
                LEFT JOIN LATERAL (
                    SELECT count(*)::int AS ready_for_approval_count
                    FROM recovery.analysis_artifacts f
                    JOIN recovery.analysis_runs ar ON ar.tenant_id=f.tenant_id AND ar.id=f.analysis_run_id
                    WHERE f.tenant_id=a.tenant_id AND ar.account_id=a.id
                      AND f.artifact_kind='negative_keyword_proposal'
                      AND f.payload->>'disposition'='ready_for_approval'
                      AND NOT EXISTS (
                          SELECT 1 FROM recovery.proposal_decision_events d
                          WHERE d.tenant_id=f.tenant_id AND d.proposal_artifact_id=f.id
                      )
                ) pr ON true
                WHERE a.tenant_id=%s
                ORDER BY a.descriptive_name, a.customer_id
                """,
                (tenant_id,),
            )
            accounts=[]
            money: dict[str, dict[str, int]] = {}
            stale=0
            ready_total=0
            for row in cur.fetchall():
                if row["id"] not in allowed: continue
                last=row["latest_sync_at"]
                if last is None:
                    data_status="unavailable"
                    stale += 1
                else:
                    age=now-last
                    if age <= timedelta(hours=24): data_status="current"
                    elif age <= timedelta(hours=72): data_status="delayed"
                    else:
                        data_status="stale"; stale += 1
                cand=int(row["potentially_avoidable_observed_micros"] or 0)
                ver=int(row["verified_recovery_micros"] or 0)
                ready=int(row["ready_for_approval_count"] or 0)
                ready_total += ready
                bucket=money.setdefault(row["currency_code"], {"potentially_avoidable_observed_micros":0,"verified_recovery_micros":0})
                bucket["potentially_avoidable_observed_micros"] += cand
                bucket["verified_recovery_micros"] += ver
                accounts.append({
                    "id":row["id"], "customer_id":row["customer_id"],
                    "descriptive_name":row["descriptive_name"], "currency_code":row["currency_code"],
                    "time_zone":row["time_zone"], "latest_sync_at":row["latest_sync_at"],
                    "latest_analysis_at":row["latest_analysis_at"], "data_status":data_status,
                    "potentially_avoidable_observed_micros":cand, "verified_recovery_micros":ver,
                    "ready_for_approval_count":ready,
                })

            if restricted:
                portfolio_count=0
                if allowed:
                    cur.execute("SELECT count(*)::int AS n FROM recovery.shell_tasks WHERE tenant_id=%s AND status NOT IN ('done','cancelled') AND ((account_id = ANY(%s)) OR (account_id IS NULL AND assigned_to=%s))",(tenant_id,list(allowed),user_id))
                    open_tasks=int(cur.fetchone()["n"])
                else:
                    cur.execute("SELECT count(*)::int AS n FROM recovery.shell_tasks WHERE tenant_id=%s AND status NOT IN ('done','cancelled') AND account_id IS NULL AND assigned_to=%s",(tenant_id,user_id))
                    open_tasks=int(cur.fetchone()["n"])
            else:
                cur.execute("SELECT count(*)::int AS n FROM recovery.portfolios WHERE tenant_id=%s", (tenant_id,))
                portfolio_count=int(cur.fetchone()["n"])
                cur.execute("SELECT count(*)::int AS n FROM recovery.shell_tasks WHERE tenant_id=%s AND status NOT IN ('done','cancelled')",(tenant_id,))
                open_tasks=int(cur.fetchone()["n"])
            cur.execute(
                "SELECT count(*)::int AS n FROM recovery.user_notifications WHERE tenant_id=%s AND user_id=%s AND read_at IS NULL",
                (tenant_id,user_id),
            )
            unread=int(cur.fetchone()["n"])

            return {
                "tenant_id":tenant_id, "tenant_name":tenant["display_name"],
                "account_count":len(accounts), "portfolio_count":portfolio_count,
                "open_task_count":open_tasks, "unread_notification_count":unread,
                "ready_for_approval_count":ready_total,
                "current_account_count":len(accounts)-stale,
                "stale_account_count":stale,
                "money_by_currency":[
                    {"currency_code":cc, **vals} for cc, vals in sorted(money.items())
                ],
                "accounts":accounts, "generated_at":now,
            }

    def list_portfolios(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """
                SELECT p.id, p.name, p.description, p.created_at, p.updated_at,
                       count(pa.account_id)::int AS account_count
                FROM recovery.portfolios p
                LEFT JOIN recovery.portfolio_accounts pa
                  ON pa.tenant_id=p.tenant_id AND pa.portfolio_id=p.id
                WHERE p.tenant_id=%s
                GROUP BY p.id
                ORDER BY lower(p.name), p.id
                """, (tenant_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def portfolio_detail(self, *, tenant_id: UUID, portfolio_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur, tenant_id)
            cur.execute(
                """SELECT p.id,p.name,p.description,p.created_at,p.updated_at,
                          (SELECT count(*)::int FROM recovery.portfolio_accounts pa WHERE pa.tenant_id=p.tenant_id AND pa.portfolio_id=p.id) AS account_count
                   FROM recovery.portfolios p WHERE p.tenant_id=%s AND p.id=%s""",
                (tenant_id,portfolio_id),
            )
            p=cur.fetchone()
            if p is None: raise ApiNotFound("portfolio not found")
            cur.execute(
                """SELECT a.id,a.customer_id,a.descriptive_name,a.currency_code,a.time_zone,a.account_status
                   FROM recovery.portfolio_accounts pa
                   JOIN recovery.google_ads_accounts a ON a.tenant_id=pa.tenant_id AND a.id=pa.account_id
                   WHERE pa.tenant_id=%s AND pa.portfolio_id=%s
                   ORDER BY lower(a.descriptive_name),a.customer_id""",
                (tenant_id,portfolio_id),
            )
            out=dict(p); out["accounts"]=[dict(r) for r in cur.fetchall()]; return out

    def create_portfolio(self, *, tenant_id: UUID, user_id: UUID, name: str, description: str | None) -> dict[str, Any]:
        name=name.strip()
        if not name: raise ValueError("portfolio name is required")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            try:
                cur.execute(
                    """INSERT INTO recovery.portfolios(tenant_id,name,description,created_by)
                       VALUES (%s,%s,%s,%s)
                       RETURNING id,name,description,created_at,updated_at""",
                    (tenant_id,name,description,user_id),
                )
            except Exception as exc:
                if getattr(exc,"sqlstate",None)=="23505": raise ApiConflict("portfolio name already exists") from exc
                raise
            row=dict(cur.fetchone()); row["account_count"]=0; return row

    def add_portfolio_account(self, *, tenant_id: UUID, user_id: UUID, portfolio_id: UUID, account_id: UUID) -> None:
        self.ensure_account(tenant_id=tenant_id, account_id=account_id)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT 1 FROM recovery.portfolios WHERE tenant_id=%s AND id=%s", (tenant_id,portfolio_id))
            if cur.fetchone() is None: raise ApiNotFound("portfolio not found")
            cur.execute(
                """INSERT INTO recovery.portfolio_accounts(tenant_id,portfolio_id,account_id,added_by)
                   VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (tenant_id,portfolio_id,account_id,user_id),
            )

    def remove_portfolio_account(self, *, tenant_id: UUID, portfolio_id: UUID, account_id: UUID) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                "DELETE FROM recovery.portfolio_accounts WHERE tenant_id=%s AND portfolio_id=%s AND account_id=%s",
                (tenant_id,portfolio_id,account_id),
            )

    def list_tasks(self, *, tenant_id: UUID, user_id: UUID, scope: str, account_id: UUID | None, status: str | None, limit: int) -> list[dict[str, Any]]:
        if scope not in {"all","mine"}: raise ValueError("scope must be all or mine")
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        clauses=["tenant_id=%s"]; params:list[Any]=[tenant_id]
        membership=self.membership(user_id=user_id,tenant_id=tenant_id)
        if membership is None: return []
        if membership.account_access_mode!="all_accounts":
            allowed=self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
            if account_id is not None and account_id not in allowed: return []
            if allowed:
                clauses.append("((account_id = ANY(%s)) OR (account_id IS NULL AND assigned_to=%s))"); params.extend([list(allowed),user_id])
            else:
                clauses.append("account_id IS NULL AND assigned_to=%s"); params.append(user_id)
        if scope=="mine": clauses.append("assigned_to=%s"); params.append(user_id)
        if account_id is not None: clauses.append("account_id=%s"); params.append(account_id)
        if status: clauses.append("status=%s"); params.append(status)
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute(
                f"""SELECT id,account_id,portfolio_id,title,description,source_type,source_id,priority,status,
                           assigned_to,due_at,created_by,created_at,updated_at,completed_at
                    FROM recovery.shell_tasks WHERE {' AND '.join(clauses)}
                    ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                             due_at NULLS LAST, created_at DESC LIMIT %s""",
                tuple(params),
            )
            return [dict(r) for r in cur.fetchall()]

    def create_task(self, *, tenant_id: UUID, user_id: UUID, title: str, description: str | None, account_id: UUID | None, portfolio_id: UUID | None, priority: str, assigned_to: UUID | None, due_at: datetime | None) -> dict[str, Any]:
        if account_id is not None: self.ensure_account(tenant_id=tenant_id, account_id=account_id)
        if priority not in {"low","normal","high","urgent"}: raise ValueError("invalid priority")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            if portfolio_id is not None:
                cur.execute("SELECT 1 FROM recovery.portfolios WHERE tenant_id=%s AND id=%s",(tenant_id,portfolio_id))
                if cur.fetchone() is None: raise ApiNotFound("portfolio not found")
            if assigned_to is not None:
                cur.execute("SELECT 1 FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s AND status='active'",(tenant_id,assigned_to))
                if cur.fetchone() is None: raise ApiConflict("assignee is not an active tenant member")
            cur.execute(
                """INSERT INTO recovery.shell_tasks(
                       tenant_id,account_id,portfolio_id,title,description,priority,assigned_to,due_at,created_by
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id,account_id,portfolio_id,title,description,source_type,source_id,priority,status,
                             assigned_to,due_at,created_by,created_at,updated_at,completed_at""",
                (tenant_id,account_id,portfolio_id,title.strip(),description,priority,assigned_to,due_at,user_id),
            )
            return dict(cur.fetchone())

    def update_task_status(self, *, tenant_id: UUID, task_id: UUID, status: str) -> dict[str, Any]:
        if status not in {"open","in_progress","blocked","done","cancelled"}: raise ValueError("invalid task status")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """UPDATE recovery.shell_tasks SET status=%s, updated_at=now(),
                       completed_at=CASE WHEN %s='done' THEN COALESCE(completed_at,now()) ELSE NULL END
                   WHERE tenant_id=%s AND id=%s
                   RETURNING id,account_id,portfolio_id,title,description,source_type,source_id,priority,status,
                             assigned_to,due_at,created_by,created_at,updated_at,completed_at""",
                (status,status,tenant_id,task_id),
            )
            row=cur.fetchone()
            if row is None: raise ApiNotFound("task not found")
            return dict(row)

    def list_notifications(self, *, tenant_id: UUID, user_id: UUID, unread_only: bool, limit: int) -> list[dict[str, Any]]:
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            clause="AND read_at IS NULL" if unread_only else ""
            cur.execute(
                f"""SELECT id,kind,severity,title,body,href,source_type,source_id,read_at,created_at
                     FROM recovery.user_notifications
                     WHERE tenant_id=%s AND user_id=%s {clause}
                     ORDER BY created_at DESC,id DESC LIMIT %s""",
                (tenant_id,user_id,limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_notification_read(self, *, tenant_id: UUID, user_id: UUID, notification_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """UPDATE recovery.user_notifications SET read_at=COALESCE(read_at,now())
                   WHERE tenant_id=%s AND user_id=%s AND id=%s
                   RETURNING id,kind,severity,title,body,href,source_type,source_id,read_at,created_at""",
                (tenant_id,user_id,notification_id),
            )
            row=cur.fetchone()
            if row is None: raise ApiNotFound("notification not found")
            return dict(row)

    def global_search(self, *, tenant_id: UUID, user_id: UUID, query: str, limit: int) -> list[dict[str, Any]]:
        q=query.strip()
        if len(q)<2: return []
        membership=self.membership(user_id=user_id,tenant_id=tenant_id)
        if membership is None: return []
        allowed=self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
        restricted=membership.account_access_mode!="all_accounts"
        if limit<1 or limit>50: raise ValueError("limit must be between 1 and 50")
        like=f"%{q}%"
        results=[]
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """SELECT id,descriptive_name,customer_id FROM recovery.google_ads_accounts
                   WHERE tenant_id=%s AND (descriptive_name ILIKE %s OR customer_id ILIKE %s)
                     AND (%s=false OR id = ANY(%s))
                   ORDER BY descriptive_name LIMIT %s""",
                (tenant_id,like,like,restricted,list(allowed),limit),
            )
            for r in cur.fetchall():
                results.append({"kind":"account","id":str(r["id"]),"title":r["descriptive_name"] or r["customer_id"],"subtitle":r["customer_id"],"href":f"/app/accounts/{r['id']}?tenant={tenant_id}&account={r['id']}"})
            remaining=max(0,limit-len(results))
            if remaining and not restricted:
                cur.execute(
                    """SELECT id,name,description FROM recovery.portfolios
                       WHERE tenant_id=%s AND name ILIKE %s ORDER BY name LIMIT %s""",
                    (tenant_id,like,remaining),
                )
                for r in cur.fetchall():
                    results.append({"kind":"portfolio","id":str(r["id"]),"title":r["name"],"subtitle":r["description"],"href":f"/app/portfolios/{r['id']}?tenant={tenant_id}"})
            remaining=max(0,limit-len(results))
            if remaining:
                cur.execute(
                    """SELECT id,title,status FROM recovery.shell_tasks
                       WHERE tenant_id=%s AND title ILIKE %s
                         AND (%s=false OR account_id = ANY(%s) OR (account_id IS NULL AND assigned_to=%s))
                       ORDER BY created_at DESC LIMIT %s""",
                    (tenant_id,like,restricted,list(allowed),user_id,remaining),
                )
                for r in cur.fetchall():
                    results.append({"kind":"task","id":str(r["id"]),"title":r["title"],"subtitle":r["status"],"href":f"/app/tasks?tenant={tenant_id}"})
        return results[:limit]

    # --- Epic 3 Search Intelligence ---

    def _search_window(self, cur: Any, *, tenant_id: UUID, account_id: UUID,
                       start: date | None, end: date | None) -> dict[str, Any]:
        cur.execute(
            """
            SELECT a.currency_code,
                   min(k.observation_date) AS min_available,
                   max(k.observation_date) AS max_available
            FROM recovery.google_ads_accounts a
            LEFT JOIN recovery.search_term_observation_keys k
              ON k.tenant_id=a.tenant_id AND k.account_id=a.id
             AND EXISTS (
                SELECT 1
                FROM recovery.search_term_observation_versions v
                JOIN recovery.search_term_version_occurrences o
                  ON o.tenant_id=v.tenant_id AND o.version_id=v.id
                JOIN recovery.sync_chunks c
                  ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id AND c.status='completed'
                JOIN recovery.sync_runs sr
                  ON sr.tenant_id=c.tenant_id AND sr.id=c.sync_run_id AND sr.status='completed'
                WHERE v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
             )
            WHERE a.tenant_id=%s AND a.id=%s
            GROUP BY a.currency_code
            """, (tenant_id,account_id),
        )
        available=cur.fetchone()
        if available is None:
            raise ApiNotFound("Google Ads account not found")
        if available["min_available"] is None or available["max_available"] is None:
            raise ApiConflict("no completed Search query observations are available for this account")
        if (start is None) != (end is None):
            raise ValueError("start and end must be supplied together")
        if start is None:
            cur.execute(
                """
                SELECT sr.window_start, sr.window_end
                FROM recovery.analysis_runs ar
                JOIN recovery.sync_runs sr
                  ON sr.tenant_id=ar.tenant_id AND sr.id=ar.sync_run_id AND sr.status='completed'
                WHERE ar.tenant_id=%s AND ar.account_id=%s AND ar.status='completed'
                ORDER BY ar.completed_at DESC NULLS LAST, ar.id DESC LIMIT 1
                """, (tenant_id,account_id),
            )
            chosen=cur.fetchone()
            if chosen is None:
                cur.execute(
                    """SELECT window_start,window_end FROM recovery.sync_runs
                       WHERE tenant_id=%s AND account_id=%s AND status='completed'
                       ORDER BY completed_at DESC NULLS LAST,id DESC LIMIT 1""",
                    (tenant_id,account_id),
                )
                chosen=cur.fetchone()
            if chosen is not None:
                start,end=chosen["window_start"],chosen["window_end"]
            else:
                end=available["max_available"]
                start=max(available["min_available"],end-timedelta(days=29))
        assert start is not None and end is not None
        if start>end:
            raise ValueError("start must be <= end")
        if (end-start).days > 1095:
            raise ValueError("Search Intelligence date range cannot exceed 1096 days")
        return {
            "start":start,"end":end,"min_available":available["min_available"],
            "max_available":available["max_available"],"currency_code":available["currency_code"],
        }

    def _search_analysis_meta(self, cur: Any, *, tenant_id: UUID, account_id: UUID,
                              start: date, end: date) -> dict[str, Any]:
        cur.execute(
            """
            SELECT ar.id,ar.completed_at,sr.window_start,sr.window_end
            FROM recovery.analysis_runs ar
            JOIN recovery.sync_runs sr ON sr.tenant_id=ar.tenant_id AND sr.id=ar.sync_run_id
            WHERE ar.tenant_id=%s AND ar.account_id=%s AND ar.status='completed'
            ORDER BY ar.completed_at DESC NULLS LAST,ar.id DESC LIMIT 1
            """, (tenant_id,account_id),
        )
        row=cur.fetchone()
        if row is None:
            return {"id":None,"completed_at":None,"window_matches":False}
        return {"id":row["id"],"completed_at":row["completed_at"],
                "window_matches":row["window_start"]==start and row["window_end"]==end}

    @staticmethod
    def _coverage_band(ratio: Decimal | None) -> str:
        if ratio is None: return "unknown"
        if ratio >= Decimal("0.80"): return "high"
        if ratio >= Decimal("0.50"): return "medium"
        return "low"

    def _search_coverage(self, cur: Any, *, tenant_id: UUID, account_id: UUID,
                         start: date, end: date, currency_code: str) -> dict[str, Any]:
        cur.execute(
            """
            WITH latest_terms AS (
              SELECT k.id,v.cost_micros
              FROM recovery.search_term_observation_keys k
              JOIN LATERAL (
                SELECT v.cost_micros
                FROM recovery.search_term_observation_versions v
                JOIN recovery.search_term_version_occurrences o ON o.tenant_id=v.tenant_id AND o.version_id=v.id
                JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id AND c.status='completed'
                JOIN recovery.sync_runs sr ON sr.tenant_id=c.tenant_id AND sr.id=c.sync_run_id AND sr.status='completed'
                WHERE v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
                ORDER BY o.observed_at DESC,v.first_seen_at DESC,v.id DESC LIMIT 1
              ) v ON true
              WHERE k.tenant_id=%s AND k.account_id=%s AND k.observation_date BETWEEN %s AND %s
            ), latest_campaign AS (
              SELECT k.id,v.cost_micros
              FROM recovery.campaign_spend_observation_keys k
              JOIN LATERAL (
                SELECT v.cost_micros
                FROM recovery.campaign_spend_observation_versions v
                JOIN recovery.campaign_spend_version_occurrences o ON o.tenant_id=v.tenant_id AND o.version_id=v.id
                JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id AND c.status='completed'
                JOIN recovery.sync_runs sr ON sr.tenant_id=c.tenant_id AND sr.id=c.sync_run_id AND sr.status='completed'
                WHERE v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
                ORDER BY o.observed_at DESC,v.first_seen_at DESC,v.id DESC LIMIT 1
              ) v ON true
              WHERE k.tenant_id=%s AND k.account_id=%s AND k.observation_date BETWEEN %s AND %s
            )
            SELECT COALESCE((SELECT sum(cost_micros) FROM latest_terms),0)::bigint AS visible,
                   COALESCE((SELECT sum(cost_micros) FROM latest_campaign),0)::bigint AS comparable
            """, (tenant_id,account_id,start,end,tenant_id,account_id,start,end),
        )
        r=cur.fetchone(); visible=int(r["visible"]); comparable=int(r["comparable"])
        if visible>comparable and comparable>0:
            # Reporting surfaces can have different processing, but the synced Search
            # denominator should never support a >100% coverage claim.
            ratio=Decimal("1")
        elif comparable>0:
            ratio=Decimal(visible)/Decimal(comparable)
        else:
            ratio=None
        unobserved=max(comparable-visible,0)
        return {
            "currency_code":currency_code,"visible_search_term_micros":visible,
            "comparable_search_campaign_micros":comparable,"unobserved_search_micros":unobserved,
            "coverage_ratio":str(ratio) if ratio is not None else None,
            "coverage_band":self._coverage_band(ratio),
            "note":"Unobserved Search spend is a coverage limitation. Recovery OS does not extrapolate hidden-query waste from this amount.",
        }

    @staticmethod
    def _search_obs_cte() -> str:
        return """
        WITH latest_obs AS (
          SELECT k.normalized_query,k.customer_id,k.campaign_id,k.ad_group_id,k.observation_date,
                 k.network,k.match_source,k.search_term_match_type,k.targeting_status,
                 k.triggering_keyword,k.triggering_keyword_match_type,
                 v.campaign_name,v.ad_group_name,v.raw_search_term,v.impressions,v.clicks,v.cost_micros,
                 v.conversions,v.conversions_value,v.all_conversions,v.all_conversions_value,v.currency_code
          FROM recovery.search_term_observation_keys k
          JOIN LATERAL (
            SELECT v.*
            FROM recovery.search_term_observation_versions v
            JOIN recovery.search_term_version_occurrences o ON o.tenant_id=v.tenant_id AND o.version_id=v.id
            JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id AND c.status='completed'
            JOIN recovery.sync_runs sr ON sr.tenant_id=c.tenant_id AND sr.id=c.sync_run_id AND sr.status='completed'
            WHERE v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
            ORDER BY o.observed_at DESC,v.first_seen_at DESC,v.id DESC LIMIT 1
          ) v ON true
          WHERE k.tenant_id=%s AND k.account_id=%s AND k.observation_date BETWEEN %s AND %s
        )
        """

    @staticmethod
    def _search_classification_cte() -> str:
        return """
        , semantic_raw AS (
          SELECT sa.payload->>'normalized_query' AS normalized_query,
                 sa.payload->>'status' AS semantic_status,
                 (
                   SELECT i->>'category'
                   FROM jsonb_array_elements(COALESCE(sa.payload->'intents','[]'::jsonb)) i
                   ORDER BY COALESCE((i->>'confidence')::numeric,0) DESC,i->>'category' LIMIT 1
                 ) AS primary_intent,
                 fit.payload->>'disposition' AS fit_disposition
          FROM recovery.analysis_artifacts sa
          LEFT JOIN recovery.analysis_artifacts fit
            ON fit.tenant_id=sa.tenant_id AND fit.analysis_run_id=sa.analysis_run_id
           AND fit.artifact_kind='business_fit_decision'
           AND regexp_replace(fit.external_id,'^fit:','')=regexp_replace(sa.external_id,'^sem:','')
          WHERE sa.tenant_id=%s AND sa.analysis_run_id=%s AND sa.artifact_kind='semantic_assessment'
        ), class_by_query AS (
          SELECT normalized_query,
                 CASE WHEN count(DISTINCT semantic_status)=1 THEN min(semantic_status) ELSE 'conflicting' END AS semantic_status,
                 CASE WHEN count(DISTINCT fit_disposition)=1 THEN min(fit_disposition) ELSE 'conflicting' END AS fit_disposition,
                 CASE WHEN count(DISTINCT primary_intent) FILTER (WHERE primary_intent IS NOT NULL)=1
                      THEN min(primary_intent) FILTER (WHERE primary_intent IS NOT NULL)
                      WHEN count(DISTINCT primary_intent) FILTER (WHERE primary_intent IS NOT NULL)>1 THEN 'mixed'
                      ELSE NULL END AS primary_intent
          FROM semantic_raw GROUP BY normalized_query
        ), evidence_by_query AS (
          SELECT payload->'key'->>'normalized_query' AS normalized_query,
                 CASE
                   WHEN bool_or(payload->>'disposition'='potentially_avoidable') THEN 'potentially_avoidable'
                   WHEN bool_or(payload->>'disposition'='review_required') THEN 'review_required'
                   WHEN bool_or(payload->>'disposition'='already_addressed') THEN 'already_addressed'
                   WHEN bool_or(payload->>'disposition'='supported') THEN 'supported'
                   ELSE min(payload->>'disposition')
                 END AS evidence_status,
                 COALESCE(sum(CASE WHEN payload->>'disposition'='potentially_avoidable'
                                   THEN (payload->>'mature_cost_micros')::bigint ELSE 0 END),0)::bigint AS candidate,
                 COALESCE(sum(CASE WHEN payload->>'disposition'='review_required'
                                   THEN (payload->>'mature_cost_micros')::bigint+(payload->>'immature_cost_micros')::bigint ELSE 0 END),0)::bigint AS review_required
          FROM recovery.analysis_artifacts
          WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='financial_finding'
          GROUP BY payload->'key'->>'normalized_query'
        )
        """

    def search_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID,
                                     start: date | None, end: date | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            window=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=window["start"],end=window["end"])
            params=[tenant_id,account_id,window["start"],window["end"]]
            sql=self._search_obs_cte()
            if analysis["id"] is not None:
                sql+=self._search_classification_cte()
                params += [tenant_id,analysis["id"],tenant_id,analysis["id"]]
                class_join="LEFT JOIN class_by_query c USING(normalized_query)"
                ev_join="LEFT JOIN evidence_by_query e USING(normalized_query)"
                class_cols="c.fit_disposition,c.semantic_status,c.primary_intent,e.evidence_status,e.candidate,e.review_required"
            else:
                class_join=ev_join=""
                class_cols="NULL::text AS fit_disposition,NULL::text AS semantic_status,NULL::text AS primary_intent,NULL::text AS evidence_status,0::bigint AS candidate,0::bigint AS review_required"
            sql+=f"""
            , term_base AS (
              SELECT o.normalized_query,sum(o.impressions)::bigint AS impressions,sum(o.clicks)::bigint AS clicks,
                     sum(o.cost_micros)::bigint AS cost_micros,sum(o.conversions)::numeric AS conversions,
                     sum(o.conversions_value)::numeric AS conversions_value,
                     {class_cols}
              FROM latest_obs o {class_join} {ev_join}
              GROUP BY o.normalized_query{',c.fit_disposition,c.semantic_status,c.primary_intent,e.evidence_status,e.candidate,e.review_required' if analysis['id'] is not None else ''}
            )
            SELECT count(*)::int AS distinct_queries,COALESCE(sum(impressions),0)::bigint AS impressions,
                   COALESCE(sum(clicks),0)::bigint AS clicks,COALESCE(sum(cost_micros),0)::bigint AS cost_micros,
                   COALESCE(sum(conversions),0)::numeric AS conversions,COALESCE(sum(conversions_value),0)::numeric AS conversions_value,
                   COALESCE(sum(candidate),0)::bigint AS candidate,COALESCE(sum(review_required),0)::bigint AS review_required
            FROM term_base
            """
            cur.execute(sql,tuple(params)); totals=cur.fetchone()
            fit_counts:dict[str,int]={}; evidence_counts:dict[str,int]={}
            if analysis["id"] is not None:
                # Classification counts are query counts, not row counts.
                cur.execute(
                    self._search_obs_cte()+self._search_classification_cte()+"""
                    , q AS (SELECT DISTINCT normalized_query FROM latest_obs)
                    SELECT COALESCE(c.fit_disposition,'unclassified') AS k,count(*)::int AS n
                    FROM q LEFT JOIN class_by_query c USING(normalized_query) GROUP BY 1 ORDER BY 1
                    """,
                    (tenant_id,account_id,window["start"],window["end"],tenant_id,analysis["id"],tenant_id,analysis["id"]),
                )
                fit_counts={r["k"]:int(r["n"]) for r in cur.fetchall()}
                if analysis["window_matches"]:
                    cur.execute(
                        self._search_obs_cte()+self._search_classification_cte()+"""
                        , q AS (SELECT DISTINCT normalized_query FROM latest_obs)
                        SELECT COALESCE(e.evidence_status,'no_finding') AS k,count(*)::int AS n
                        FROM q LEFT JOIN evidence_by_query e USING(normalized_query) GROUP BY 1 ORDER BY 1
                        """,
                        (tenant_id,account_id,window["start"],window["end"],tenant_id,analysis["id"],tenant_id,analysis["id"]),
                    )
                    evidence_counts={r["k"]:int(r["n"]) for r in cur.fetchall()}
            coverage=self._search_coverage(cur,tenant_id=tenant_id,account_id=account_id,start=window["start"],end=window["end"],currency_code=window["currency_code"])
            return {
                "account_id":account_id,"currency_code":window["currency_code"],
                "window":{k:window[k] for k in ("start","end","min_available","max_available")},
                "distinct_queries":int(totals["distinct_queries"]),"impressions":int(totals["impressions"]),
                "clicks":int(totals["clicks"]),"cost_micros":int(totals["cost_micros"]),
                "conversions":str(totals["conversions"]),"conversions_value":str(totals["conversions_value"]),
                "potentially_avoidable_observed_micros":int(totals["candidate"]) if analysis["window_matches"] else 0,
                "review_required_observed_micros":int(totals["review_required"]) if analysis["window_matches"] else 0,
                "latest_analysis_run_id":analysis["id"],"latest_analysis_completed_at":analysis["completed_at"],
                "analysis_window_matches":analysis["window_matches"],"fit_counts":fit_counts,"evidence_counts":evidence_counts,
                "coverage":coverage,
            }

    def search_intelligence_terms(self, *, tenant_id: UUID, account_id: UUID,
                                  start: date | None, end: date | None, query: str | None,
                                  network: str | None, fit: str | None, sort: str,
                                  direction: str, page: int, page_size: int) -> dict[str, Any]:
        validate_sort(sort)
        if direction not in {"asc","desc"}: raise ValueError("direction must be asc or desc")
        if page<1: raise ValueError("page must be >= 1")
        if page_size<1 or page_size>200: raise ValueError("page_size must be between 1 and 200")
        if network is not None and network not in {"SEARCH","SEARCH_PARTNERS"}: raise ValueError("unsupported network")
        if fit is not None and fit not in {"relevant","irrelevant","conditional","unknown","conflicting","unclassified"}: raise ValueError("unsupported fit filter")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            window=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=window["start"],end=window["end"])
            params:list[Any]=[tenant_id,account_id,window["start"],window["end"]]
            sql=self._search_obs_cte()
            if analysis["id"] is not None:
                sql+=self._search_classification_cte(); params += [tenant_id,analysis["id"],tenant_id,analysis["id"]]
                joins="LEFT JOIN class_by_query c USING(normalized_query) LEFT JOIN evidence_by_query e USING(normalized_query)"
                class_select="c.fit_disposition,c.semantic_status,c.primary_intent,e.evidence_status,e.candidate,e.review_required"
                group_extra=",c.fit_disposition,c.semantic_status,c.primary_intent,e.evidence_status,e.candidate,e.review_required"
            else:
                joins=""; group_extra=""
                class_select="NULL::text AS fit_disposition,NULL::text AS semantic_status,NULL::text AS primary_intent,NULL::text AS evidence_status,0::bigint AS candidate,0::bigint AS review_required"
            obs_where=[]
            if network is not None:
                obs_where.append("o.network=%s"); params.append(network)
            where_clause=("WHERE "+" AND ".join(obs_where)) if obs_where else ""
            sql+=f"""
            , term_base AS (
              SELECT o.normalized_query,(array_agg(o.raw_search_term ORDER BY o.observation_date DESC,o.raw_search_term))[1] AS raw_query_example,
                     sum(o.impressions)::bigint AS impressions,sum(o.clicks)::bigint AS clicks,sum(o.cost_micros)::bigint AS cost_micros,
                     sum(o.conversions)::numeric AS conversions,sum(o.conversions_value)::numeric AS conversions_value,
                     sum(o.all_conversions)::numeric AS all_conversions,sum(o.all_conversions_value)::numeric AS all_conversions_value,
                     count(DISTINCT o.campaign_id)::int AS campaign_count,count(DISTINCT o.ad_group_id)::int AS ad_group_count,
                     min(o.observation_date) AS first_observation_date,max(o.observation_date) AS last_observation_date,
                     array_agg(DISTINCT o.network ORDER BY o.network) AS networks,
                     array_agg(DISTINCT o.match_source ORDER BY o.match_source) AS match_sources,
                     {class_select}
              FROM latest_obs o {joins} {where_clause}
              GROUP BY o.normalized_query{group_extra}
            ), filtered AS (SELECT * FROM term_base WHERE true
            """
            if query:
                sql += " AND (normalized_query ILIKE %s OR raw_query_example ILIKE %s)"; like=f"%{query.strip()}%"; params += [like,like]
            if fit:
                if fit=="unclassified": sql += " AND fit_disposition IS NULL"
                else: sql += " AND fit_disposition=%s"; params.append(fit)
            sql += ")\n"
            sort_col={"cost":"cost_micros","clicks":"clicks","impressions":"impressions","conversions":"conversions","query":"normalized_query"}[sort]
            sql += f"""SELECT *,count(*) OVER()::int AS total FROM filtered
                       ORDER BY {sort_col} {direction.upper()},normalized_query ASC LIMIT %s OFFSET %s"""
            params += [page_size,(page-1)*page_size]
            cur.execute(sql,tuple(params)); result=cur.fetchall(); total=int(result[0]["total"]) if result else 0
            rows=[]
            for r in result:
                rows.append({
                    "normalized_query":r["normalized_query"],"raw_query_example":r["raw_query_example"],
                    "impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),
                    "conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),
                    "all_conversions":str(r["all_conversions"]),"all_conversions_value":str(r["all_conversions_value"]),
                    "campaign_count":int(r["campaign_count"]),"ad_group_count":int(r["ad_group_count"]),
                    "first_observation_date":r["first_observation_date"],"last_observation_date":r["last_observation_date"],
                    "networks":list(r["networks"] or []),"match_sources":list(r["match_sources"] or []),
                    "fit_disposition":r["fit_disposition"],"semantic_status":r["semantic_status"],"primary_intent":r["primary_intent"],
                    "evidence_status":r["evidence_status"] if analysis["window_matches"] else None,
                    "potentially_avoidable_observed_micros":int(r["candidate"] or 0) if analysis["window_matches"] else 0,
                    "review_required_observed_micros":int(r["review_required"] or 0) if analysis["window_matches"] else 0,
                    "analysis_run_id":analysis["id"],"financial_evidence_in_window":analysis["window_matches"],
                })
            return {"window":{k:window[k] for k in ("start","end","min_available","max_available")},
                    "currency_code":window["currency_code"],"page":page,"page_size":page_size,"total":total,"rows":rows}

    def search_intelligence_term_detail(self, *, tenant_id: UUID, account_id: UUID,
                                        normalized_query: str, start: date | None, end: date | None) -> dict[str, Any]:
        normalized_query=normalize_query(normalized_query)
        if not normalized_query: raise ValueError("query is required")
        page=self.search_intelligence_terms(tenant_id=tenant_id,account_id=account_id,start=start,end=end,
            query=normalized_query,network=None,fit=None,sort="query",direction="asc",page=1,page_size=200)
        term=next((r for r in page["rows"] if r["normalized_query"]==normalized_query),None)
        if term is None: raise ApiNotFound("search term not found in selected window")
        w=page["window"]
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            base=self._search_obs_cte()
            cur.execute(base+"""
                SELECT campaign_id,campaign_name,ad_group_id,ad_group_name,network,match_source,
                       triggering_keyword,triggering_keyword_match_type,
                       sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,sum(cost_micros)::bigint AS cost_micros,
                       sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value,
                       min(observation_date) AS first_observation_date,max(observation_date) AS last_observation_date
                FROM latest_obs WHERE normalized_query=%s
                GROUP BY campaign_id,campaign_name,ad_group_id,ad_group_name,network,match_source,triggering_keyword,triggering_keyword_match_type
                ORDER BY cost_micros DESC,campaign_name,ad_group_name,network
                """,(tenant_id,account_id,w["start"],w["end"],normalized_query))
            scopes=[{**dict(r),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"])} for r in cur.fetchall()]
            cur.execute(base+"""
                SELECT observation_date AS date,sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                       sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                FROM latest_obs WHERE normalized_query=%s GROUP BY observation_date ORDER BY observation_date
                """,(tenant_id,account_id,w["start"],w["end"],normalized_query))
            daily=[{"date":r["date"],"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"])} for r in cur.fetchall()]
            semantic=fit=None; findings=[]
            if analysis["id"] is not None:
                cur.execute("""SELECT payload FROM recovery.analysis_artifacts WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='semantic_assessment' AND payload->>'normalized_query'=%s ORDER BY created_at DESC LIMIT 1""",(tenant_id,analysis["id"],normalized_query)); r=cur.fetchone(); semantic=r["payload"] if r else None
                if semantic is not None:
                    cur.execute("""SELECT payload FROM recovery.analysis_artifacts WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='business_fit_decision' AND payload->>'raw_query'=%s ORDER BY created_at DESC LIMIT 1""",(tenant_id,analysis["id"],semantic.get("raw_query"))); r=cur.fetchone(); fit=r["payload"] if r else None
                if analysis["window_matches"]:
                    cur.execute("""SELECT payload FROM recovery.analysis_artifacts WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='financial_finding' AND payload->'key'->>'normalized_query'=%s ORDER BY created_at,id""",(tenant_id,analysis["id"],normalized_query)); findings=[r["payload"] for r in cur.fetchall()]
            return {"account_id":account_id,"currency_code":page["currency_code"],"window":w,"term":term,
                    "scope_breakdown":scopes,"daily":daily,"semantic_assessment":semantic,"business_fit":fit,
                    "financial_findings":findings,"coverage_note":"Visible query detail contains only search terms exposed by Google Ads reporting. Privacy-hidden demand is not reconstructed into individual queries."}

    def search_intelligence_breakdown(self, *, tenant_id: UUID, account_id: UUID,
                                      start: date | None, end: date | None, dimension: str) -> dict[str, Any]:
        if dimension not in {"network","match_source","intent","fit"}: raise ValueError("unsupported breakdown dimension")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            base=self._search_obs_cte(); params:list[Any]=[tenant_id,account_id,w["start"],w["end"]]
            if dimension in {"network","match_source"}:
                col="network" if dimension=="network" else "match_source"
                sql=base+f"""SELECT {col} AS key,count(DISTINCT normalized_query)::int AS query_count,
                    sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,sum(cost_micros)::bigint AS cost_micros,
                    sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                    FROM latest_obs GROUP BY {col} ORDER BY cost_micros DESC,{col}"""
                cur.execute(sql,tuple(params)); rows=[{"key":r["key"],"query_count":int(r["query_count"]),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),"potentially_avoidable_observed_micros":0} for r in cur.fetchall()]
            else:
                if analysis["id"] is None:
                    rows=[]
                else:
                    sql=base+self._search_classification_cte()+"""
                    , q AS (
                      SELECT normalized_query,sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                             sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                      FROM latest_obs GROUP BY normalized_query
                    )
                    SELECT COALESCE("""+("c.primary_intent" if dimension=="intent" else "c.fit_disposition")+""",'unclassified') AS key,
                           count(*)::int AS query_count,sum(q.impressions)::bigint AS impressions,sum(q.clicks)::bigint AS clicks,
                           sum(q.cost_micros)::bigint AS cost_micros,sum(q.conversions)::numeric AS conversions,sum(q.conversions_value)::numeric AS conversions_value,
                           COALESCE(sum(e.candidate),0)::bigint AS candidate
                    FROM q LEFT JOIN class_by_query c USING(normalized_query) LEFT JOIN evidence_by_query e USING(normalized_query)
                    GROUP BY 1 ORDER BY cost_micros DESC,key
                    """
                    params += [tenant_id,analysis["id"],tenant_id,analysis["id"]]
                    cur.execute(sql,tuple(params)); rows=[{"key":r["key"],"query_count":int(r["query_count"]),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),"potentially_avoidable_observed_micros":int(r["candidate"] or 0) if analysis["window_matches"] else 0} for r in cur.fetchall()]
            return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"dimension":dimension,"rows":rows}

    def search_intelligence_ngrams(self, *, tenant_id: UUID, account_id: UUID,
                                   start: date | None, end: date | None, n: int,
                                   sort: str, limit: int, without_conversions: bool) -> dict[str, Any]:
        if n<1 or n>6: raise ValueError("n must be between 1 and 6")
        if sort not in {"cost","clicks","impressions","conversions"}: raise ValueError("unsupported n-gram sort")
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            params:list[Any]=[tenant_id,account_id,w["start"],w["end"]]
            sql=self._search_obs_cte()
            if analysis["id"] is not None:
                sql+=self._search_classification_cte(); params += [tenant_id,analysis["id"],tenant_id,analysis["id"]]
                ev="LEFT JOIN evidence_by_query e USING(normalized_query)"; candidate="COALESCE(e.candidate,0)::bigint AS candidate"; group_extra=",e.candidate"
            else:
                ev=""; candidate="0::bigint AS candidate"; group_extra=""
            sql+=f"""
            , q AS (
              SELECT o.normalized_query,sum(o.impressions)::bigint AS impressions,sum(o.clicks)::bigint AS clicks,
                     sum(o.cost_micros)::bigint AS cost_micros,sum(o.conversions)::numeric AS conversions,
                     sum(o.conversions_value)::numeric AS conversions_value,{candidate}
              FROM latest_obs o {ev} GROUP BY o.normalized_query{group_extra}
            ), tokenized AS (
              SELECT q.*,regexp_split_to_array(q.normalized_query,E'\\s+') AS tokens FROM q
              {'WHERE q.conversions=0' if without_conversions else ''}
            ), grams AS (
              SELECT DISTINCT normalized_query,impressions,clicks,cost_micros,conversions,conversions_value,candidate,
                     array_to_string(tokens[i:i+%s-1],' ') AS ngram
              FROM tokenized CROSS JOIN LATERAL generate_series(1,array_length(tokens,1)-%s+1) AS i
              WHERE array_length(tokens,1)>=%s
            )
            SELECT ngram,count(*)::int AS query_count,sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                   sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value,
                   sum(candidate)::bigint AS candidate
            FROM grams GROUP BY ngram ORDER BY """+{"cost":"cost_micros","clicks":"clicks","impressions":"impressions","conversions":"conversions"}[sort]+" DESC,query_count DESC,ngram LIMIT %s"
            params += [n,n,n,limit]
            cur.execute(sql,tuple(params)); rows=[{"ngram":r["ngram"],"query_count":int(r["query_count"]),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),"potentially_avoidable_observed_micros":int(r["candidate"] or 0) if analysis["window_matches"] else 0} for r in cur.fetchall()]
            return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"n":n,"sort":sort,"without_conversions":without_conversions,"rows":rows}

    def list_search_saved_views(self, *, tenant_id: UUID, user_id: UUID,
                                account_id: UUID | None, portfolio_id: UUID | None) -> list[dict[str, Any]]:
        if account_id is not None and portfolio_id is not None: raise ValueError("choose account or portfolio scope")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            if account_id is not None:
                cur.execute("""SELECT id,account_id,portfolio_id,name,filters,is_default,created_at,updated_at FROM recovery.search_saved_views WHERE tenant_id=%s AND user_id=%s AND account_id=%s ORDER BY is_default DESC,lower(name)""",(tenant_id,user_id,account_id))
            elif portfolio_id is not None:
                cur.execute("""SELECT id,account_id,portfolio_id,name,filters,is_default,created_at,updated_at FROM recovery.search_saved_views WHERE tenant_id=%s AND user_id=%s AND portfolio_id=%s ORDER BY is_default DESC,lower(name)""",(tenant_id,user_id,portfolio_id))
            else:
                cur.execute("""SELECT id,account_id,portfolio_id,name,filters,is_default,created_at,updated_at FROM recovery.search_saved_views WHERE tenant_id=%s AND user_id=%s ORDER BY updated_at DESC LIMIT 200""",(tenant_id,user_id))
            return [dict(r) for r in cur.fetchall()]

    def create_search_saved_view(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None,
                                 portfolio_id: UUID | None, name: str, filters: dict[str, Any], is_default: bool) -> dict[str, Any]:
        if (account_id is None)==(portfolio_id is None): raise ValueError("saved view requires exactly one account or portfolio scope")
        if len(json.dumps(canonical_payload(filters),ensure_ascii=False,separators=(",",":")))>16_384: raise ValueError("saved view filters exceed 16 KB")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            if account_id is not None:
                cur.execute("SELECT 1 FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id=%s",(tenant_id,account_id))
            else:
                cur.execute("SELECT 1 FROM recovery.portfolios WHERE tenant_id=%s AND id=%s",(tenant_id,portfolio_id))
            if cur.fetchone() is None: raise ApiNotFound("saved-view scope not found")
            if is_default:
                cur.execute("""UPDATE recovery.search_saved_views SET is_default=false,updated_at=now() WHERE tenant_id=%s AND user_id=%s AND account_id IS NOT DISTINCT FROM %s AND portfolio_id IS NOT DISTINCT FROM %s AND is_default=true""",(tenant_id,user_id,account_id,portfolio_id))
            try:
                cur.execute("""INSERT INTO recovery.search_saved_views(tenant_id,user_id,account_id,portfolio_id,name,filters,is_default) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id,account_id,portfolio_id,name,filters,is_default,created_at,updated_at""",(tenant_id,user_id,account_id,portfolio_id,name.strip(),self._json(canonical_payload(filters)),is_default))
            except Exception as exc:
                if getattr(exc,"sqlstate",None)=="23505": raise ApiConflict("saved view name already exists in this scope") from exc
                raise
            return dict(cur.fetchone())

    def delete_search_saved_view(self, *, tenant_id: UUID, user_id: UUID, view_id: UUID) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("DELETE FROM recovery.search_saved_views WHERE tenant_id=%s AND user_id=%s AND id=%s",(tenant_id,user_id,view_id))
            if cur.rowcount!=1: raise ApiNotFound("saved view not found")

    def portfolio_search_ngrams(self, *, tenant_id: UUID, portfolio_id: UUID, start: date, end: date,
                                n: int, limit: int) -> list[dict[str, Any]]:
        if n<1 or n>6: raise ValueError("n must be between 1 and 6")
        if start>end: raise ValueError("start must be <= end")
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT 1 FROM recovery.portfolios WHERE tenant_id=%s AND id=%s",(tenant_id,portfolio_id))
            if cur.fetchone() is None: raise ApiNotFound("portfolio not found")
            cur.execute(
                """
                WITH latest_obs AS (
                  SELECT k.account_id,k.normalized_query,v.currency_code,v.impressions,v.clicks,v.cost_micros,v.conversions,v.conversions_value
                  FROM recovery.portfolio_accounts pa
                  JOIN recovery.search_term_observation_keys k ON k.tenant_id=pa.tenant_id AND k.account_id=pa.account_id
                  JOIN LATERAL (
                    SELECT v.* FROM recovery.search_term_observation_versions v
                    JOIN recovery.search_term_version_occurrences o ON o.tenant_id=v.tenant_id AND o.version_id=v.id
                    JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id AND c.status='completed'
                    JOIN recovery.sync_runs sr ON sr.tenant_id=c.tenant_id AND sr.id=c.sync_run_id AND sr.status='completed'
                    WHERE v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
                    ORDER BY o.observed_at DESC,v.first_seen_at DESC,v.id DESC LIMIT 1
                  ) v ON true
                  WHERE pa.tenant_id=%s AND pa.portfolio_id=%s AND k.observation_date BETWEEN %s AND %s
                ), q AS (
                  SELECT account_id,normalized_query,currency_code,sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                         sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                  FROM latest_obs GROUP BY account_id,normalized_query,currency_code
                ), t AS (SELECT q.*,regexp_split_to_array(normalized_query,E'\\s+') tokens FROM q), grams AS (
                  SELECT DISTINCT account_id,normalized_query,currency_code,impressions,clicks,cost_micros,conversions,conversions_value,
                         array_to_string(tokens[i:i+%s-1],' ') AS ngram
                  FROM t CROSS JOIN LATERAL generate_series(1,array_length(tokens,1)-%s+1) i WHERE array_length(tokens,1)>=%s
                )
                SELECT currency_code,ngram,count(DISTINCT account_id)::int AS account_count,count(*)::int AS query_count,
                       sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,sum(cost_micros)::bigint AS cost_micros,
                       sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                FROM grams GROUP BY currency_code,ngram ORDER BY cost_micros DESC,account_count DESC,ngram LIMIT %s
                """,(tenant_id,portfolio_id,start,end,n,n,n,limit),
            )
            return [{"currency_code":r["currency_code"],"ngram":r["ngram"],"account_count":int(r["account_count"]),"query_count":int(r["query_count"]),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"])} for r in cur.fetchall()]

    @staticmethod
    def _waste_classification_cte() -> str:
        return """
        , waste_fit_raw AS (
          SELECT sa.payload->>'normalized_query' AS normalized_query,
                 fit.payload->>'disposition' AS fit_disposition,
                 CASE
                   WHEN fit.payload->>'disposition' <> 'irrelevant' THEN NULL
                   WHEN COALESCE(jsonb_array_length(fit.payload->'decisive_non_offer_ids'),0) > 0 THEN 'wrong_service'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'employment' THEN 'employment'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'free' THEN 'free'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'diy' THEN 'diy'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'support' THEN 'support'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'training' THEN 'training'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'competitor' THEN 'competitor'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'informational'
                     OR COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'research' THEN 'informational'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'second_hand' THEN 'second_hand'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'rental' THEN 'rental'
                   WHEN COALESCE(fit.payload->'decisive_intents','[]'::jsonb) ? 'wholesale' THEN 'wholesale'
                   WHEN COALESCE(jsonb_array_length(fit.payload->'decisive_intents'),0) > 0 THEN 'other_denied_intent'
                   ELSE 'irrelevant_intent'
                 END AS leak_family
          FROM recovery.analysis_artifacts sa
          LEFT JOIN recovery.analysis_artifacts fit
            ON fit.tenant_id=sa.tenant_id AND fit.analysis_run_id=sa.analysis_run_id
           AND fit.artifact_kind='business_fit_decision'
           AND regexp_replace(fit.external_id,'^fit:','')=regexp_replace(sa.external_id,'^sem:','')
          WHERE sa.tenant_id=%s AND sa.analysis_run_id=%s AND sa.artifact_kind='semantic_assessment'
        ), waste_family_by_query AS (
          SELECT normalized_query,
                 CASE WHEN count(DISTINCT fit_disposition)=1 THEN min(fit_disposition) ELSE 'conflicting' END AS fit_disposition,
                 CASE WHEN count(DISTINCT leak_family) FILTER (WHERE leak_family IS NOT NULL)=1
                      THEN min(leak_family) FILTER (WHERE leak_family IS NOT NULL)
                      WHEN count(DISTINCT leak_family) FILTER (WHERE leak_family IS NOT NULL)>1 THEN 'irrelevant_intent'
                      ELSE NULL END AS leak_family
          FROM waste_fit_raw GROUP BY normalized_query
        ), waste_evidence_by_query AS (
          SELECT payload->'key'->>'normalized_query' AS normalized_query,
                 COALESCE(sum(CASE WHEN payload->>'disposition'='potentially_avoidable'
                                   THEN (payload->>'mature_cost_micros')::bigint ELSE 0 END),0)::bigint AS candidate,
                 COALESCE(sum(CASE WHEN payload->>'disposition'='review_required'
                                   THEN (payload->>'mature_cost_micros')::bigint+(payload->>'immature_cost_micros')::bigint ELSE 0 END),0)::bigint AS review_required,
                 COALESCE(sum(CASE WHEN payload->>'disposition'='already_addressed'
                                   THEN (payload->>'mature_cost_micros')::bigint+(payload->>'immature_cost_micros')::bigint ELSE 0 END),0)::bigint AS already_addressed,
                 count(*)::int AS finding_count
          FROM recovery.analysis_artifacts
          WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='financial_finding'
          GROUP BY payload->'key'->>'normalized_query'
        )
        """

    def waste_intelligence_query_leaks(self, *, tenant_id: UUID, account_id: UUID,
                                       start: date | None, end: date | None, family: str | None,
                                       disposition: str | None, page: int, page_size: int) -> dict[str, Any]:
        families={"wrong_service","employment","free","diy","support","training","competitor","informational","second_hand","rental","wholesale","other_denied_intent","irrelevant_intent"}
        dispositions={"potentially_avoidable","review_required","already_addressed","not_supported"}
        if family is not None and family not in families: raise ValueError("unsupported leak family")
        if disposition is not None and disposition not in dispositions: raise ValueError("unsupported waste disposition")
        if page<1 or page_size<1 or page_size>200: raise ValueError("invalid page or page_size")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            if analysis["id"] is None:
                return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"analysis_run_id":None,"financial_evidence_in_window":False,"page":page,"page_size":page_size,"total":0,"rows":[]}
            sql=self._search_obs_cte()+self._waste_classification_cte()+"""
            , q AS (
              SELECT o.normalized_query,min(o.raw_search_term) AS raw_query_example,
                     sum(o.impressions)::bigint AS impressions,sum(o.clicks)::bigint AS clicks,
                     sum(o.cost_micros)::bigint AS cost_micros,sum(o.conversions)::numeric AS conversions,
                     array_agg(DISTINCT o.network ORDER BY o.network) AS networks
              FROM latest_obs o GROUP BY o.normalized_query
            ), rows AS (
              SELECT q.*,f.leak_family,f.fit_disposition,
                     CASE WHEN COALESCE(e.candidate,0)>0 THEN 'potentially_avoidable'
                          WHEN COALESCE(e.review_required,0)>0 THEN 'review_required'
                          WHEN COALESCE(e.already_addressed,0)>0 THEN 'already_addressed'
                          ELSE 'not_supported' END AS disposition,
                     COALESCE(e.candidate,0)::bigint AS candidate,
                     COALESCE(e.review_required,0)::bigint AS review_required,
                     COALESCE(e.already_addressed,0)::bigint AS already_addressed,
                     COALESCE(e.finding_count,0)::int AS finding_count
              FROM q LEFT JOIN waste_family_by_query f USING(normalized_query)
                     LEFT JOIN waste_evidence_by_query e USING(normalized_query)
              WHERE f.fit_disposition='irrelevant'
            )
            SELECT *,count(*) OVER()::int AS total FROM rows
            WHERE (%s::text IS NULL OR leak_family=%s)
              AND (%s::text IS NULL OR disposition=%s)
            ORDER BY candidate DESC,review_required DESC,cost_micros DESC,normalized_query
            LIMIT %s OFFSET %s
            """
            params=[tenant_id,account_id,w["start"],w["end"],tenant_id,analysis["id"],tenant_id,analysis["id"],family,family,disposition,disposition,page_size,(page-1)*page_size]
            cur.execute(sql,tuple(params)); result=cur.fetchall(); total=int(result[0]["total"]) if result else 0
            rows=[]
            for r in result:
                rows.append({
                    "normalized_query":r["normalized_query"],"raw_query_example":r["raw_query_example"],"leak_family":r["leak_family"] or "irrelevant_intent",
                    "disposition":r["disposition"] if analysis["window_matches"] else "not_supported",
                    "impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),
                    "networks":list(r["networks"] or []),"finding_count":int(r["finding_count"]),
                    "potentially_avoidable_observed_micros":int(r["candidate"] or 0) if analysis["window_matches"] else 0,
                    "review_required_observed_micros":int(r["review_required"] or 0) if analysis["window_matches"] else 0,
                    "already_addressed_observed_micros":int(r["already_addressed"] or 0) if analysis["window_matches"] else 0,
                })
            return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"analysis_run_id":analysis["id"],"financial_evidence_in_window":analysis["window_matches"],"page":page,"page_size":page_size,"total":total,"rows":rows}

    def waste_intelligence_dimension(self, *, tenant_id: UUID, account_id: UUID,
                                     start: date | None, end: date | None, dimension: str) -> dict[str, Any]:
        if dimension not in {"network","device","daypart"}: raise ValueError("unsupported waste dimension")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            if dimension=="network":
                cur.execute(self._search_obs_cte()+"""
                    SELECT network AS key,count(DISTINCT normalized_query)::int AS query_count,
                           sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                           sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,
                           sum(conversions_value)::numeric AS conversions_value
                    FROM latest_obs GROUP BY network ORDER BY cost_micros DESC,network
                """,(tenant_id,account_id,w["start"],w["end"]))
                base={r["key"]:{"key":r["key"],"query_count":int(r["query_count"]),"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),"potentially_avoidable_observed_micros":0,"review_required_observed_micros":0,"financial_claim_supported":analysis["window_matches"]} for r in cur.fetchall()}
                if analysis["id"] is not None and analysis["window_matches"]:
                    cur.execute("""
                      SELECT payload->'key'->>'network' AS key,
                        COALESCE(sum(CASE WHEN payload->>'disposition'='potentially_avoidable' THEN (payload->>'mature_cost_micros')::bigint ELSE 0 END),0)::bigint AS candidate,
                        COALESCE(sum(CASE WHEN payload->>'disposition'='review_required' THEN (payload->>'mature_cost_micros')::bigint+(payload->>'immature_cost_micros')::bigint ELSE 0 END),0)::bigint AS review
                      FROM recovery.analysis_artifacts WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='financial_finding'
                      GROUP BY 1
                    """,(tenant_id,analysis["id"]))
                    for r in cur.fetchall():
                        if r["key"] in base:
                            base[r["key"]]["potentially_avoidable_observed_micros"]=int(r["candidate"] or 0)
                            base[r["key"]]["review_required_observed_micros"]=int(r["review"] or 0)
                rows=list(base.values())
            else:
                key_expr="device" if dimension=="device" else "day_of_week || ' ' || lpad(hour::text,2,'0') || ':00'"
                cur.execute(f"""
                  WITH ranked AS (
                    SELECT s.*,row_number() OVER(PARTITION BY s.campaign_id,s.observation_date,s.network,s.device,s.day_of_week,s.hour ORDER BY sr.completed_at DESC NULLS LAST,sr.id DESC) AS rn
                    FROM recovery.campaign_performance_segments s
                    JOIN recovery.sync_runs sr ON sr.tenant_id=s.tenant_id AND sr.id=s.sync_run_id AND sr.status='completed'
                    WHERE s.tenant_id=%s AND s.account_id=%s AND s.observation_date BETWEEN %s AND %s
                  )
                  SELECT {key_expr} AS key,0::int AS query_count,sum(impressions)::bigint AS impressions,sum(clicks)::bigint AS clicks,
                         sum(cost_micros)::bigint AS cost_micros,sum(conversions)::numeric AS conversions,sum(conversions_value)::numeric AS conversions_value
                  FROM ranked WHERE rn=1 GROUP BY 1 ORDER BY cost_micros DESC,key
                """,(tenant_id,account_id,w["start"],w["end"]))
                rows=[{"key":r["key"],"query_count":0,"impressions":int(r["impressions"]),"clicks":int(r["clicks"]),"cost_micros":int(r["cost_micros"]),"conversions":str(r["conversions"]),"conversions_value":str(r["conversions_value"]),"potentially_avoidable_observed_micros":0,"review_required_observed_micros":0,"financial_claim_supported":False} for r in cur.fetchall()]
            return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"dimension":dimension,"rows":rows,"note":("Confirmed query mismatch money is shown by network without double counting leak families." if dimension=="network" else "Observed performance only. Device/daypart zero conversions or weak ratios are not, by themselves, proof of waste.")}

    def waste_intelligence_geo(self, *, tenant_id: UUID, account_id: UUID,
                               start: date | None, end: date | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            cur.execute("""
              SELECT ar.id AS analysis_run_id,ar.as_of,ar.engine_versions,bt.id AS truth_snapshot_id,bt.payload
              FROM recovery.analysis_runs ar
              JOIN recovery.business_truth_snapshots bt ON bt.tenant_id=ar.tenant_id AND bt.id=ar.truth_snapshot_id
              WHERE ar.tenant_id=%s AND ar.account_id=%s AND ar.status='completed' AND ar.as_of >= %s
              ORDER BY ar.completed_at DESC NULLS LAST,ar.id DESC LIMIT 1
            """,(tenant_id,account_id,w["end"]))
            meta=cur.fetchone()
            cur.execute("""
              WITH ranked AS (
                SELECT l.*,row_number() OVER(PARTITION BY l.campaign_id,l.observation_date,l.network,l.location_resource,l.targeting_location ORDER BY sr.completed_at DESC NULLS LAST,sr.id DESC) AS rn
                FROM recovery.user_location_observations l
                JOIN recovery.sync_runs sr ON sr.tenant_id=l.tenant_id AND sr.id=l.sync_run_id AND sr.status='completed'
                WHERE l.tenant_id=%s AND l.account_id=%s AND l.observation_date BETWEEN %s AND %s
              ) SELECT * FROM ranked WHERE rn=1 ORDER BY cost_micros DESC,location_resource
            """,(tenant_id,account_id,w["start"],w["end"]))
            raw=cur.fetchall()
            if meta is None:
                rows=[{"location_resource":r["location_resource"],"location_name":r["location_name"] or r["location_resource"],"canonical_name":r["canonical_name"],"country_code":r["country_code"],"target_type":r["target_type"],"disposition":"not_evaluated","reason":"No completed analysis with a conversion-lag policy covers this window.","mature_cost_micros":0,"immature_cost_micros":int(r["cost_micros"]),"potentially_avoidable_observed_micros":0,"review_required_observed_micros":0,"mature_conversions":"0","row_count":1} for r in raw]
                return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"evaluation_ready":False,"analysis_run_id":None,"truth_snapshot_id":None,"rows":rows,"note":"Geo leakage requires actual user-location evidence, confirmed Business Truth, and an explicit conversion-lag policy."}
            payload=dict(meta["payload"]); created_at=payload.get("created_at")
            submitted_at=datetime.fromisoformat(str(created_at).replace("Z","+00:00")) if created_at else datetime.now(timezone.utc)
            truth=parse_business_truth_payload(payload,submitted_by=str(payload.get("created_by") or "stored"),submitted_at=submitted_at)
            lag=int((meta["engine_versions"] or {}).get("conversion_lag_days",0))
            policy=AccuracyPolicy(conversion_lag_days=lag)
            observations=[UserLocationObservation(customer_id=r["customer_id"],campaign_id=r["campaign_id"],campaign_name=r["campaign_name"],date=r["observation_date"],network=r["network"],targeting_location=bool(r["targeting_location"]),country_criterion_id=r["country_criterion_id"],location_resource=r["location_resource"],location_name=r["location_name"],canonical_name=r["canonical_name"],country_code=r["country_code"],target_type=r["target_type"],impressions=int(r["impressions"]),clicks=int(r["clicks"]),cost_micros=int(r["cost_micros"]),conversions=Decimal(str(r["conversions"])),conversions_value=Decimal(str(r["conversions_value"])),all_conversions=Decimal(str(r["all_conversions"])),all_conversions_value=Decimal(str(r["all_conversions_value"])),currency_code=r["currency_code"]) for r in raw]
            evaluated=evaluate_geo_leaks(truth=truth,rows=observations,policy=policy,as_of=meta["as_of"])
            rows=[{"location_resource":x.location_resource,"location_name":x.location_name,"canonical_name":x.canonical_name,"country_code":x.country_code,"target_type":x.target_type,"disposition":x.disposition,"reason":x.reason,"mature_cost_micros":x.mature_cost_micros,"immature_cost_micros":x.immature_cost_micros,"potentially_avoidable_observed_micros":x.potentially_avoidable_observed_micros,"review_required_observed_micros":x.review_required_observed_micros,"mature_conversions":str(x.mature_conversions),"row_count":x.row_count} for x in evaluated]
            geo_policy=truth.geo_policy
            physical_policy_ready=bool(
                raw and geo_policy is not None and geo_policy.basis.is_confirmed
                and geo_policy.requirement in {
                    CustomerLocationRequirement.CUSTOMER_MUST_BE_IN_SERVICE_AREA,
                    CustomerLocationRequirement.NO_RESTRICTION,
                }
            )
            note=(
                "Geo candidates use actual physical user-location reporting. Campaign targeting configuration is not treated as proof of user location."
                if physical_policy_ready else
                "Physical user-location evidence is present, but current Business Truth is not directly comparable to customer-presence reporting; rows remain review/diagnostic evidence."
            )
            return {"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"evaluation_ready":physical_policy_ready,"analysis_run_id":meta["analysis_run_id"],"truth_snapshot_id":meta["truth_snapshot_id"],"rows":rows,"note":note}

    def waste_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID,
                                    start: date | None, end: date | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            w=self._search_window(cur,tenant_id=tenant_id,account_id=account_id,start=start,end=end)
            analysis=self._search_analysis_meta(cur,tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
            families=[]
            if analysis["id"] is not None:
                cur.execute(self._waste_classification_cte()+"""
                  SELECT COALESCE(f.leak_family,'irrelevant_intent') AS leak_family,count(*)::int AS query_count,
                         COALESCE(sum(e.candidate),0)::bigint AS candidate,
                         COALESCE(sum(e.review_required),0)::bigint AS review_required,
                         COALESCE(sum(e.already_addressed),0)::bigint AS already_addressed
                  FROM waste_family_by_query f LEFT JOIN waste_evidence_by_query e USING(normalized_query)
                  WHERE f.fit_disposition='irrelevant' GROUP BY 1 ORDER BY candidate DESC,review_required DESC,leak_family
                """,(tenant_id,analysis["id"],tenant_id,analysis["id"]))
                families=[{"leak_family":r["leak_family"],"query_count":int(r["query_count"]),"potentially_avoidable_observed_micros":int(r["candidate"] or 0) if analysis["window_matches"] else 0,"review_required_observed_micros":int(r["review_required"] or 0) if analysis["window_matches"] else 0,"already_addressed_observed_micros":int(r["already_addressed"] or 0) if analysis["window_matches"] else 0} for r in cur.fetchall()]
            cur.execute("""SELECT EXISTS(SELECT 1 FROM recovery.campaign_performance_segments s JOIN recovery.sync_runs sr ON sr.tenant_id=s.tenant_id AND sr.id=s.sync_run_id AND sr.status='completed' WHERE s.tenant_id=%s AND s.account_id=%s AND s.observation_date BETWEEN %s AND %s) AS segment_ready,
                                  EXISTS(SELECT 1 FROM recovery.user_location_observations l JOIN recovery.sync_runs sr ON sr.tenant_id=l.tenant_id AND sr.id=l.sync_run_id AND sr.status='completed' WHERE l.tenant_id=%s AND l.account_id=%s AND l.observation_date BETWEEN %s AND %s) AS geo_ready""",(tenant_id,account_id,w["start"],w["end"],tenant_id,account_id,w["start"],w["end"]))
            readiness=cur.fetchone()
        geo=self.waste_intelligence_geo(tenant_id=tenant_id,account_id=account_id,start=w["start"],end=w["end"])
        geo_candidate=sum(int(r["potentially_avoidable_observed_micros"]) for r in geo["rows"])
        geo_review=sum(int(r["review_required_observed_micros"]) for r in geo["rows"])
        query_candidate=sum(int(x["potentially_avoidable_observed_micros"]) for x in families)
        query_review=sum(int(x["review_required_observed_micros"]) for x in families)
        return {"account_id":account_id,"window":{k:w[k] for k in ("start","end","min_available","max_available")},"currency_code":w["currency_code"],"analysis_run_id":analysis["id"],"analysis_window_matches":analysis["window_matches"],"query_potentially_avoidable_observed_micros":query_candidate,"query_review_required_observed_micros":query_review,"geo_potentially_avoidable_observed_micros":geo_candidate,"geo_review_required_observed_micros":geo_review,"families":families,"dimension_data_ready":bool(readiness["segment_ready"]),"geo_data_ready":bool(readiness["geo_ready"]),"geo_evaluation_ready":bool(geo["evaluation_ready"]),"financial_note":"Query leak families are mutually exclusive. Network/device/daypart are dimensions and are never added again to the leak-family total. Geo is a separate physical-location Business Truth claim and can overlap the same paid clicks, so it is not added to the query-family total."}

    # --- Epic 5 Measurement Integrity ---

    def _latest_measurement_snapshot(self, cur: Any, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any] | None:
        cur.execute(
            """SELECT ms.*,sr.window_start,sr.window_end,sr.completed_at AS sync_completed_at
               FROM recovery.measurement_snapshots ms
               JOIN recovery.sync_runs sr ON sr.tenant_id=ms.tenant_id AND sr.id=ms.sync_run_id AND sr.status='completed'
               WHERE ms.tenant_id=%s AND ms.account_id=%s
               ORDER BY sr.completed_at DESC NULLS LAST,ms.created_at DESC,ms.id DESC LIMIT 1""",
            (tenant_id,account_id),
        )
        row=cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _action_from_row(r: dict[str, Any]) -> ConversionActionObservation:
        return ConversionActionObservation(
            customer_id=r["customer_id"],resource_name=r["resource_name"],action_id=r["action_id"],name=r["name"],status=r["status"],
            action_type=r["action_type"],category=r["category"],origin=r["origin"],owner_customer=r["owner_customer"],
            primary_for_goal=bool(r["primary_for_goal"]),counting_type=r["counting_type"],click_through_lookback_days=int(r["click_through_lookback_days"]),
            view_through_lookback_days=int(r["view_through_lookback_days"]),attribution_model=r["attribution_model"],data_driven_model_status=r["data_driven_model_status"],
            default_value=Decimal(str(r["default_value"])),default_currency_code=r["default_currency_code"],always_use_default_value=bool(r["always_use_default_value"]),
            all_conversions=Decimal(str(r["all_conversions"])),all_conversions_value=Decimal(str(r["all_conversions_value"])),last_conversion_date=r["last_conversion_date"],
            last_received_request_at=r["last_received_request_at"],
        )

    def _measurement_context(self, cur: Any, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        snap=self._latest_measurement_snapshot(cur,tenant_id=tenant_id,account_id=account_id)
        if snap is None:
            return {"snapshot":None,"actions":[],"customer_goals":[],"campaign_goals":[],"campaign_configs":[],"lag":[],"mappings":{},"truth_snapshot_id":None,"profile_days":None}
        sid=snap["id"]
        cur.execute("SELECT * FROM recovery.conversion_action_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s ORDER BY lower(name),action_id",(tenant_id,sid))
        action_rows=[dict(r) for r in cur.fetchall()]
        actions=[self._action_from_row(r) for r in action_rows]
        cur.execute("SELECT * FROM recovery.customer_conversion_goal_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s ORDER BY category,origin",(tenant_id,sid))
        customer_goals=[CustomerConversionGoalObservation(customer_id=r["customer_id"],resource_name=r["resource_name"],category=r["category"],origin=r["origin"],biddable=bool(r["biddable"])) for r in cur.fetchall()]
        cur.execute("SELECT * FROM recovery.campaign_conversion_goal_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s ORDER BY campaign_name,category,origin",(tenant_id,sid))
        campaign_goals=[CampaignConversionGoalObservation(customer_id=r["customer_id"],campaign_id=r["campaign_id"],campaign_name=r["campaign_name"],campaign_status=r["campaign_status"],resource_name=r["resource_name"],category=r["category"],origin=r["origin"],biddable=bool(r["biddable"])) for r in cur.fetchall()]
        cur.execute("SELECT * FROM recovery.campaign_goal_config_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s ORDER BY campaign_name",(tenant_id,sid))
        campaign_configs=[CampaignGoalConfigObservation(customer_id=r["customer_id"],campaign_id=r["campaign_id"],campaign_name=r["campaign_name"],campaign_status=r["campaign_status"],resource_name=r["resource_name"],goal_config_level=r["goal_config_level"],custom_conversion_goal=r["custom_conversion_goal"]) for r in cur.fetchall()]
        cur.execute("SELECT * FROM recovery.conversion_lag_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s ORDER BY conversion_action_name,lag_bucket",(tenant_id,sid))
        lag=[ConversionLagObservation(customer_id=r["customer_id"],conversion_action_resource=r["conversion_action_resource"],conversion_action_name=r["conversion_action_name"],category=r["category"],lag_bucket=r["lag_bucket"],conversions=Decimal(str(r["conversions"])),all_conversions=Decimal(str(r["all_conversions"])),conversions_value=Decimal(str(r["conversions_value"])),all_conversions_value=Decimal(str(r["all_conversions_value"])) ) for r in cur.fetchall()]
        cur.execute("SELECT id,payload FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s ORDER BY version DESC,created_at DESC,id DESC LIMIT 1",(tenant_id,account_id))
        truth=cur.fetchone(); truth_id=truth["id"] if truth else None
        outcome_by_id={}
        if truth:
            for o in (truth["payload"] or {}).get("outcomes",[]):
                outcome_by_id[str(o.get("outcome_id"))]=o
        cur.execute(
            """SELECT DISTINCT ON (conversion_action_resource) conversion_action_resource,truth_snapshot_id,outcome_id,mapping_status,created_at,id
               FROM recovery.conversion_action_mapping_events
               WHERE tenant_id=%s AND account_id=%s
               ORDER BY conversion_action_resource,created_at DESC,id DESC""",
            (tenant_id,account_id),
        )
        mappings={}
        mapping_rows={}
        for r in cur.fetchall():
            mapping_rows[r["conversion_action_resource"]]=dict(r)
            if r["mapping_status"]!="mapped" or not r["outcome_id"]:
                continue
            o=outcome_by_id.get(str(r["outcome_id"])) if r["truth_snapshot_id"]==truth_id else None
            role=(o or {}).get("role")
            basis=(o or {}).get("basis") or {}
            mappings[r["conversion_action_resource"]]=MeasurementMapping(
                conversion_action_resource=r["conversion_action_resource"],truth_snapshot_id=str(r["truth_snapshot_id"]),outcome_id=str(r["outcome_id"]),
                outcome_role=role,outcome_confirmed=(basis.get("status")=="confirmed"),
            )
        cur.execute("SELECT conversion_lag_days FROM recovery.account_measurement_profiles WHERE tenant_id=%s AND account_id=%s",(tenant_id,account_id))
        profile=cur.fetchone(); profile_days=int(profile["conversion_lag_days"]) if profile else None
        return {"snapshot":snap,"actions":actions,"action_rows":action_rows,"customer_goals":customer_goals,"campaign_goals":campaign_goals,"campaign_configs":campaign_configs,
                "lag":lag,"mappings":mappings,"mapping_rows":mapping_rows,"truth_snapshot_id":truth_id,"outcomes":list(outcome_by_id.values()),"profile_days":profile_days}

    def measurement_integrity_overview(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            ctx=self._measurement_context(cur,tenant_id=tenant_id,account_id=account_id)
        assessment=assess_measurement_integrity(actions=ctx["actions"],customer_goals=ctx["customer_goals"],campaign_goals=ctx["campaign_goals"],campaign_configs=ctx["campaign_configs"],lag_observations=ctx["lag"],mappings=ctx["mappings"],configured_conversion_lag_days=ctx["profile_days"])
        snap=ctx["snapshot"]
        return {
            "account_id":account_id,"measurement_snapshot_id":snap["id"] if snap else None,"sync_run_id":snap["sync_run_id"] if snap else None,
            "sync_completed_at":snap["sync_completed_at"] if snap else None,"window_start":snap["window_start"] if snap else None,"window_end":snap["window_end"] if snap else None,
            "confidence":assessment.confidence.value,"enabled_actions":assessment.enabled_actions,"primary_actions":assessment.primary_actions,"mapped_primary_actions":assessment.mapped_primary_actions,
            "conversion_dependent_claims_allowed":assessment.conversion_dependent_claims_allowed,"recovery_verification_allowed":assessment.recovery_verification_allowed,
            "configured_conversion_lag_days":ctx["profile_days"],"customer_goal_count":len(ctx["customer_goals"]),"campaign_goal_count":len(ctx["campaign_goals"]),
            "campaign_specific_goal_config_count":sum(1 for x in ctx["campaign_configs"] if x.goal_config_level.upper()=="CAMPAIGN" or x.custom_conversion_goal),
            "issues":[{"code":i.code,"severity":i.severity.value,"message":i.message,"conversion_action_resource":i.conversion_action_resource,"campaign_id":i.campaign_id} for i in assessment.issues],
            "available_outcomes":[{"outcome_id":str(o.get("outcome_id")),"name":str(o.get("name") or o.get("outcome_id")),"role":str(o.get("role") or "unknown"),"confirmed":((o.get("basis") or {}).get("status")=="confirmed")} for o in ctx.get("outcomes",[]) if o.get("outcome_id")],
            "note":"Measurement Confidence is an evidence state, not a 0–100 score. It constrains conversion-dependent claims when Google configuration and confirmed Business Truth do not support them.",
        }

    def measurement_conversion_actions(self, *, tenant_id: UUID, account_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); ctx=self._measurement_context(cur,tenant_id=tenant_id,account_id=account_id)
            customer_goal={(g.category.upper(),g.origin.upper()):g.biddable for g in ctx["customer_goals"]}
            out=[]
            for r,a in zip(ctx.get("action_rows",[]),ctx["actions"]):
                m=ctx["mappings"].get(a.resource_name); raw=ctx.get("mapping_rows",{}).get(a.resource_name)
                out.append({
                    "resource_name":a.resource_name,"action_id":a.action_id,"name":a.name,"status":a.status,"action_type":a.action_type,"category":a.category,"origin":a.origin,
                    "owner_customer":a.owner_customer,"primary_for_goal":a.primary_for_goal,"account_default_goal_biddable":customer_goal.get((a.category.upper(),a.origin.upper())),
                    "counting_type":a.counting_type,"click_through_lookback_days":a.click_through_lookback_days,"view_through_lookback_days":a.view_through_lookback_days,
                    "attribution_model":a.attribution_model,"data_driven_model_status":a.data_driven_model_status,"default_value":str(a.default_value),"default_currency_code":a.default_currency_code,
                    "always_use_default_value":a.always_use_default_value,"all_conversions":str(a.all_conversions),"all_conversions_value":str(a.all_conversions_value),
                    "last_conversion_date":a.last_conversion_date,"last_received_request_at":a.last_received_request_at,
                    "mapped_outcome_id":m.outcome_id if m else None,"mapped_outcome_role":m.outcome_role if m else None,"mapping_confirmed":m.outcome_confirmed if m else False,
                    "mapping_is_current_truth":bool(m),"mapping_status":raw["mapping_status"] if raw else None,
                    "enhanced_conversions_status":"not_observable_from_conversion_action_resource",
                })
            return out

    def measurement_goals(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); ctx=self._measurement_context(cur,tenant_id=tenant_id,account_id=account_id)
        return {
            "customer_goals":[{"resource_name":x.resource_name,"category":x.category,"origin":x.origin,"biddable":x.biddable} for x in ctx["customer_goals"]],
            "campaign_goals":[{"campaign_id":x.campaign_id,"campaign_name":x.campaign_name,"campaign_status":x.campaign_status,"resource_name":x.resource_name,"category":x.category,"origin":x.origin,"biddable":x.biddable} for x in ctx["campaign_goals"]],
            "campaign_configs":[{"campaign_id":x.campaign_id,"campaign_name":x.campaign_name,"campaign_status":x.campaign_status,"resource_name":x.resource_name,"goal_config_level":x.goal_config_level,"custom_conversion_goal":x.custom_conversion_goal} for x in ctx["campaign_configs"]],
            "note":"Campaign-level and custom goals can override account-level assumptions; Recovery OS surfaces them rather than flattening them into one primary/secondary flag.",
        }

    def measurement_lag(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); ctx=self._measurement_context(cur,tenant_id=tenant_id,account_id=account_id)
        rows=[{"conversion_action_resource":x.conversion_action_resource,"conversion_action_name":x.conversion_action_name,"category":x.category,"lag_bucket":x.lag_bucket,
               "conversions":str(x.conversions),"all_conversions":str(x.all_conversions),"conversions_value":str(x.conversions_value),"all_conversions_value":str(x.all_conversions_value)} for x in ctx["lag"]]
        return {"configured_conversion_lag_days":ctx["profile_days"],"rows":rows,"note":"Observed lag buckets are provider evidence. Recovery OS does not infer a universal maturity window; it flags when the configured policy is shorter than observed conversion arrival."}

    def record_conversion_action_mapping(self, *, tenant_id: UUID, account_id: UUID, user_id: UUID,
                                         conversion_action_resource: str, outcome_id: str | None) -> dict[str, Any]:
        resource=conversion_action_resource.strip()
        if not resource.startswith("customers/") or "/conversionActions/" not in resource:
            raise ValueError("invalid conversion action resource")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            snap=self._latest_measurement_snapshot(cur,tenant_id=tenant_id,account_id=account_id)
            if snap is None: raise ApiConflict("measurement snapshot is required before mapping conversion actions")
            cur.execute("SELECT 1 FROM recovery.conversion_action_observations WHERE tenant_id=%s AND measurement_snapshot_id=%s AND resource_name=%s",(tenant_id,snap["id"],resource))
            if cur.fetchone() is None: raise ApiNotFound("conversion action not found in latest measurement snapshot")
            cur.execute("SELECT id,payload FROM recovery.business_truth_snapshots WHERE tenant_id=%s AND account_id=%s ORDER BY version DESC,created_at DESC,id DESC LIMIT 1",(tenant_id,account_id))
            truth=cur.fetchone()
            if truth is None: raise ApiConflict("Business Truth is required before mapping conversion actions")
            status="cleared" if outcome_id is None else "mapped"
            if outcome_id is not None:
                outcomes=(truth["payload"] or {}).get("outcomes",[])
                if not any(str(o.get("outcome_id"))==outcome_id for o in outcomes):
                    raise ApiNotFound("Business Truth outcome not found in latest truth snapshot")
            event_id=uuid4()
            cur.execute(
                """INSERT INTO recovery.conversion_action_mapping_events(
                     id,tenant_id,account_id,conversion_action_resource,truth_snapshot_id,outcome_id,mapping_status,created_by
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING created_at""",
                (event_id,tenant_id,account_id,resource,truth["id"],outcome_id,status,user_id),
            )
            created=cur.fetchone()["created_at"]
            return {"id":event_id,"conversion_action_resource":resource,"truth_snapshot_id":truth["id"],"outcome_id":outcome_id,"mapping_status":status,"created_at":created}

    # --- Epic 6 Recovery Cases + Action Center ---

    @staticmethod
    def _proposal_candidate_key(payload: dict[str, Any]) -> tuple[str, str | None, str | None]:
        c = payload.get("candidate") or {}
        return (str(c.get("text") or ""), str(c.get("campaign_id")) if c.get("campaign_id") is not None else None,
                str(c.get("ad_group_id")) if c.get("ad_group_id") is not None else None)

    def _case_source(self, cur, *, tenant_id: UUID, case_id: UUID) -> dict[str, Any]:
        cur.execute(
            """
            SELECT a.id AS case_id, a.analysis_run_id, a.artifact_fingerprint, a.currency_code,
                   a.money_micros, a.payload AS proposal, a.created_at,
                   r.account_id, r.truth_snapshot_id,
                   acc.customer_id, acc.descriptive_name AS account_name,
                   bt.truth_fingerprint AS analysis_truth_fingerprint
            FROM recovery.analysis_artifacts a
            JOIN recovery.analysis_runs r ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
            JOIN recovery.google_ads_accounts acc ON acc.tenant_id=r.tenant_id AND acc.id=r.account_id
            JOIN recovery.business_truth_snapshots bt ON bt.tenant_id=r.tenant_id AND bt.id=r.truth_snapshot_id
            WHERE a.tenant_id=%s AND a.id=%s AND a.artifact_kind='negative_keyword_proposal'
            """,
            (tenant_id, case_id),
        )
        row=cur.fetchone()
        if row is None: raise ApiNotFound("Recovery Case not found")
        return dict(row)

    def _case_measurement_gate(self, cur, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
        ctx=self._measurement_context(cur,tenant_id=tenant_id,account_id=account_id)
        assessment=assess_measurement_integrity(
            actions=ctx["actions"],customer_goals=ctx["customer_goals"],campaign_goals=ctx["campaign_goals"],
            campaign_configs=ctx["campaign_configs"],lag_observations=ctx["lag"],mappings=ctx["mappings"],
            configured_conversion_lag_days=ctx["profile_days"],
        )
        return {
            "confidence":assessment.confidence.value,
            "conversion_claims_allowed":assessment.conversion_dependent_claims_allowed,
            "recovery_verification_allowed":assessment.recovery_verification_allowed,
            "issue_codes":[i.code for i in assessment.issues],
        }

    def _case_related(self, cur, *, tenant_id: UUID, source: dict[str, Any], measurement_gate: dict[str, Any] | None = None) -> dict[str, Any]:
        case_id=source["case_id"]; account_id=source["account_id"]
        measurement_gate=measurement_gate or self._case_measurement_gate(cur,tenant_id=tenant_id,account_id=account_id)
        cur.execute(
            """SELECT id,decision,proposal_fingerprint,decided_by,decided_at,note,payload
               FROM recovery.proposal_decision_events WHERE tenant_id=%s AND proposal_artifact_id=%s
               ORDER BY decided_at,id""", (tenant_id,case_id))
        decisions=[dict(x) for x in cur.fetchall()]
        decision=decisions[-1] if decisions else None
        cur.execute(
            """SELECT id,event_type,resource_name,api_request_id,actor,occurred_at,payload
               FROM recovery.mutation_events WHERE tenant_id=%s AND proposal_artifact_id=%s
               ORDER BY occurred_at,id""", (tenant_id,case_id))
        mutations=[dict(x) for x in cur.fetchall()]
        cur.execute(
            """SELECT id AS entry_id,analysis_run_id,mutation_event_id,currency_code,historical_candidate_micros,
                      projected_prevented_micros,observed_post_action_query_spend_micros,verified_recovery_micros,
                      causal_status,payload,created_at
               FROM recovery.recovery_ledger_entries
               WHERE tenant_id=%s AND mutation_event_id IN (
                   SELECT id FROM recovery.mutation_events WHERE tenant_id=%s AND proposal_artifact_id=%s
               ) ORDER BY created_at,id""",
            (tenant_id,tenant_id,case_id),)
        ledger=[dict(x) for x in cur.fetchall()]
        cur.execute(
            """SELECT id,event_type,actor,occurred_at,payload FROM recovery.recovery_case_events
               WHERE tenant_id=%s AND proposal_artifact_id=%s ORDER BY occurred_at,id""",
            (tenant_id,case_id),)
        case_events=[dict(x) for x in cur.fetchall()]
        cur.execute(
            """SELECT truth_fingerprint FROM recovery.business_truth_snapshots
               WHERE tenant_id=%s AND account_id=%s ORDER BY business_version DESC,created_at DESC,id DESC LIMIT 1""",
            (tenant_id,account_id),)
        latest_truth=cur.fetchone()
        cur.execute(
            """SELECT id FROM recovery.analysis_runs WHERE tenant_id=%s AND account_id=%s AND status='completed'
               ORDER BY completed_at DESC NULLS LAST,started_at DESC,id DESC LIMIT 1""",
            (tenant_id,account_id),)
        latest_analysis=cur.fetchone()
        cur.execute(
            """SELECT id AS job_id,job_type,status,result,failure_code,failure_detail,created_at,started_at,completed_at
               FROM recovery.api_jobs WHERE tenant_id=%s AND operation_key IN (%s,%s)
               ORDER BY created_at,id""",
            (tenant_id,f"proposal:{case_id}:apply",f"proposal:{case_id}:rollback"),)
        execution_jobs=[dict(x) for x in cur.fetchall()]
        apply_jobs=[x for x in execution_jobs if x["job_type"]=='apply_negative']
        latest_apply=apply_jobs[-1] if apply_jobs else None
        cur.execute(
            """SELECT id AS effect_id,job_id,effect_kind,state,resource_name,google_request_id,reconciliation_detail,
                      prepared_at,in_flight_at,committed_at,reconciled_at,result_payload
               FROM recovery.external_effects WHERE tenant_id=%s AND proposal_artifact_id=%s
               ORDER BY prepared_at,id""", (tenant_id,case_id),)
        external_effects=[dict(x) for x in cur.fetchall()]
        latest_apply_effect=next((x for x in reversed(external_effects) if x["effect_kind"]=='apply_negative'),None)
        queued=bool(latest_apply and latest_apply["status"] in {"queued","running","needs_reconciliation"})
        projection=derive_case_projection(
            proposal=dict(source["proposal"]), proposal_analysis_run_id=str(source["analysis_run_id"]),
            latest_completed_analysis_run_id=str(latest_analysis["id"]) if latest_analysis else None,
            latest_truth_fingerprint=str(latest_truth["truth_fingerprint"]) if latest_truth else None,
            decision=decision, mutation_events=mutations, ledger_entries=ledger,
            case_events=case_events, queued_execution=queued,
            execution_job_status=str(latest_apply["status"]) if latest_apply else None,
            external_effect_state=str(latest_apply_effect["state"]) if latest_apply_effect else None,
        )
        return {"decisions":decisions,"decision":decision,"mutations":mutations,"ledger":ledger,
                "case_events":case_events,"projection":projection,"execution_jobs":execution_jobs,"external_effects":external_effects,
                "execution_job_status":str(latest_apply["status"]) if latest_apply else None,
                "external_effect_state":str(latest_apply_effect["state"]) if latest_apply_effect else None,
                "latest_truth_fingerprint":latest_truth["truth_fingerprint"] if latest_truth else None,
                "latest_analysis_run_id":latest_analysis["id"] if latest_analysis else None,
                "measurement_gate":measurement_gate}

    def _case_summary(self, source: dict[str, Any], related: dict[str, Any]) -> dict[str, Any]:
        p=dict(source["proposal"]); c=p.get("candidate") or {}; projection=related["projection"]
        collisions=len(p.get("protected_query_collisions") or [])+len(p.get("positive_keyword_collisions") or [])
        return {
            "case_id":source["case_id"],"account_id":source["account_id"],"account_name":source["account_name"],
            "analysis_run_id":source["analysis_run_id"],"proposal_fingerprint":source["artifact_fingerprint"],
            "proposal_id":p.get("proposal_id"),"query":c.get("text"),"match_type":c.get("match_type"),
            "scope":c.get("scope"),"campaign_id":c.get("campaign_id"),"ad_group_id":c.get("ad_group_id"),
            "risk":p.get("risk"),"disposition":p.get("disposition"),"currency_code":source["currency_code"] or p.get("currency_code"),
            "candidate_exposure_micros":int(source["money_micros"] or p.get("potentially_avoidable_cost_micros") or 0),
            "collision_count":collisions,"state":projection.state.value,"stale":projection.stale,
            "stale_reasons":list(projection.stale_reasons),
            "execution_allowed":bool(projection.execution_allowed and related["measurement_gate"]["conversion_claims_allowed"]),
            "rollback_allowed":projection.rollback_allowed,"verification_status":projection.verification_status,
            "measurement_confidence":related["measurement_gate"]["confidence"],
            "conversion_claims_allowed":bool(related["measurement_gate"]["conversion_claims_allowed"]),
            "recovery_verification_allowed":bool(related["measurement_gate"]["recovery_verification_allowed"]),
            "measurement_issue_codes":list(related["measurement_gate"]["issue_codes"]),
            "assigned_to":projection.assigned_to,"closed":projection.closed,
            "execution_job_status":related.get("execution_job_status"),"external_effect_state":related.get("external_effect_state"),
            "created_at":source["created_at"],
        }

    def list_recovery_cases(self, *, tenant_id: UUID, account_id: UUID, state: str | None, risk: str | None, limit: int) -> list[dict[str, Any]]:
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        self.ensure_account(tenant_id=tenant_id,account_id=account_id)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """SELECT a.id AS case_id FROM recovery.analysis_artifacts a
                   JOIN recovery.analysis_runs r ON r.tenant_id=a.tenant_id AND r.id=a.analysis_run_id
                   WHERE a.tenant_id=%s AND r.account_id=%s AND a.artifact_kind='negative_keyword_proposal'
                   ORDER BY a.created_at DESC,a.id DESC LIMIT 500""",
                (tenant_id,account_id),)
            ids=[x["case_id"] for x in cur.fetchall()]
            out=[]
            measurement_gate=self._case_measurement_gate(cur,tenant_id=tenant_id,account_id=account_id)
            for cid in ids:
                src=self._case_source(cur,tenant_id=tenant_id,case_id=cid); rel=self._case_related(cur,tenant_id=tenant_id,source=src,measurement_gate=measurement_gate)
                row=self._case_summary(src,rel)
                if state and row["state"]!=state: continue
                if risk and row["risk"]!=risk: continue
                out.append(row)
                if len(out) >= limit: break
            return out

    def recovery_case_detail(self, *, tenant_id: UUID, case_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            src=self._case_source(cur,tenant_id=tenant_id,case_id=case_id); rel=self._case_related(cur,tenant_id=tenant_id,source=src)
            p=dict(src["proposal"]); text,campaign_id,ad_group_id=self._proposal_candidate_key(p)
            cur.execute(
                """SELECT id AS artifact_id,external_id,artifact_fingerprint,currency_code,money_micros,payload,created_at
                   FROM recovery.analysis_artifacts
                   WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind='financial_finding'
                     AND payload->'key'->>'normalized_query'=%s
                     AND (%s IS NULL OR payload->'key'->>'campaign_id'=%s)
                     AND (%s IS NULL OR payload->'key'->>'ad_group_id'=%s)
                   ORDER BY created_at,id""",
                (tenant_id,src["analysis_run_id"],text,campaign_id,campaign_id,ad_group_id,ad_group_id),)
            findings=[dict(x) for x in cur.fetchall()]
            summary=self._case_summary(src,rel)
            return {**summary,"proposal":p,"financial_findings":findings,"decision_events":rel["decisions"],
                    "mutation_events":rel["mutations"],"recovery_ledger":rel["ledger"],"case_events":rel["case_events"],
                    "latest_truth_fingerprint":rel["latest_truth_fingerprint"],"latest_analysis_run_id":rel["latest_analysis_run_id"],
                    "analysis_truth_fingerprint":src["analysis_truth_fingerprint"],
                    "execution_jobs":rel["execution_jobs"],"external_effects":rel["external_effects"]}

    def append_recovery_case_event(self, *, tenant_id: UUID, case_id: UUID, actor: str,
                                   event_type: str, note: str | None, assigned_to: UUID | None) -> dict[str, Any]:
        allowed={"assigned","unassigned","commented","review_requested","closed","reopened"}
        if event_type not in allowed: raise ValueError("unsupported Recovery Case event")
        note=(note or "").strip() or None
        if note and len(note)>4000: raise ValueError("case note exceeds 4000 characters")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            src=self._case_source(cur,tenant_id=tenant_id,case_id=case_id)
            payload:dict[str,Any]={}
            if event_type=="assigned":
                if assigned_to is None: raise ValueError("assigned_to is required for assignment")
                cur.execute("SELECT 1 FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s AND status='active'",(tenant_id,assigned_to))
                if cur.fetchone() is None: raise ApiConflict("assignee is not an active tenant member")
                payload["assigned_to"]=str(assigned_to)
            elif assigned_to is not None:
                raise ValueError("assigned_to is only valid for assigned event")
            if event_type in {"commented","review_requested","closed","reopened"} and not note:
                raise ValueError(f"note is required for {event_type}")
            if note: payload["note"]=note
            now=datetime.now(timezone.utc); body={"proposal_artifact_id":str(case_id),"event_type":event_type,"actor":actor,"occurred_at":now.isoformat(),"payload":payload}
            fp=payload_sha256(body); eid=uuid4()
            cur.execute(
                """INSERT INTO recovery.recovery_case_events(id,tenant_id,proposal_artifact_id,event_type,actor,occurred_at,event_fingerprint,payload)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,event_type,actor,occurred_at,payload""",
                (eid,tenant_id,case_id,event_type,actor,now,fp,self._json(payload)),)
            return dict(cur.fetchone())

    # --- Epic 7: Recovery Center financial-proof projections ---

    def _recovery_scope(self, cur, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> tuple[str,str,str,list[UUID]]:
        if account_id is not None and portfolio_id is not None:
            raise ValueError("account_id and portfolio_id are mutually exclusive")
        if account_id is not None:
            cur.execute("SELECT id,descriptive_name,customer_id FROM recovery.google_ads_accounts WHERE tenant_id=%s AND id=%s",(tenant_id,account_id))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("Google Ads account not found")
            return "account",str(account_id),str(row["descriptive_name"] or row["customer_id"]),[account_id]
        if portfolio_id is not None:
            cur.execute("SELECT id,name FROM recovery.portfolios WHERE tenant_id=%s AND id=%s",(tenant_id,portfolio_id))
            p=cur.fetchone()
            if p is None: raise ApiNotFound("portfolio not found")
            cur.execute("SELECT account_id FROM recovery.portfolio_accounts WHERE tenant_id=%s AND portfolio_id=%s ORDER BY account_id",(tenant_id,portfolio_id))
            return "portfolio",str(portfolio_id),str(p["name"]),[r["account_id"] for r in cur.fetchall()]
        cur.execute("SELECT display_name FROM recovery.tenants WHERE id=%s",(tenant_id,)); tenant=cur.fetchone()
        if tenant is None: raise ApiNotFound("tenant not found")
        cur.execute("SELECT id FROM recovery.google_ads_accounts WHERE tenant_id=%s ORDER BY id",(tenant_id,))
        return "organization",str(tenant_id),str(tenant["display_name"]),[r["id"] for r in cur.fetchall()]

    def _recovery_proof_rows(self, cur, *, tenant_id: UUID, account_ids: list[UUID]) -> list[dict[str, Any]]:
        if not account_ids: return []
        cur.execute(
            """WITH latest AS (
                   SELECT DISTINCT ON (l.mutation_event_id)
                          l.id AS entry_id,l.analysis_run_id,l.mutation_event_id,l.currency_code,
                          l.historical_candidate_micros,l.projected_prevented_micros,
                          l.observed_post_action_query_spend_micros,l.verified_recovery_micros,
                          l.causal_status,l.payload,l.created_at
                   FROM recovery.recovery_ledger_entries l
                   JOIN recovery.analysis_runs ar ON ar.tenant_id=l.tenant_id AND ar.id=l.analysis_run_id
                   WHERE l.tenant_id=%s AND ar.account_id=ANY(%s) AND l.mutation_event_id IS NOT NULL
                   ORDER BY l.mutation_event_id,l.created_at DESC,l.id DESC
               )
               SELECT latest.*,m.proposal_artifact_id,m.occurred_at AS applied_at,
                      ar.account_id,acc.descriptive_name AS account_name,acc.customer_id,
                      a.payload AS proposal,
                      cname.campaign_name,
                      sem.payload AS semantic_payload,fit.payload AS fit_payload,
                      lm.event_type AS latest_mutation_type
               FROM latest
               JOIN recovery.mutation_events m ON m.tenant_id=%s AND m.id=latest.mutation_event_id
               JOIN recovery.analysis_artifacts a ON a.tenant_id=m.tenant_id AND a.id=m.proposal_artifact_id
               JOIN recovery.analysis_runs ar ON ar.tenant_id=a.tenant_id AND ar.id=a.analysis_run_id
               JOIN recovery.google_ads_accounts acc ON acc.tenant_id=ar.tenant_id AND acc.id=ar.account_id
               LEFT JOIN LATERAL (
                   SELECT v.campaign_name FROM recovery.search_term_observation_keys k
                   JOIN recovery.search_term_observation_versions v ON v.tenant_id=k.tenant_id AND v.observation_key_id=k.id
                   WHERE k.tenant_id=a.tenant_id AND k.account_id=ar.account_id
                     AND k.campaign_id=a.payload->'candidate'->>'campaign_id'
                   ORDER BY v.first_seen_at DESC,v.id DESC LIMIT 1
               ) cname ON true
               LEFT JOIN LATERAL (
                   SELECT f.external_id FROM recovery.analysis_artifacts f
                   WHERE f.tenant_id=a.tenant_id AND f.analysis_run_id=a.analysis_run_id
                     AND f.artifact_kind='financial_finding'
                     AND f.payload->'key'->>'normalized_query'=a.payload->'candidate'->>'text'
                     AND f.payload->'key'->>'campaign_id'=a.payload->'candidate'->>'campaign_id'
                     AND f.payload->'key'->>'ad_group_id'=a.payload->'candidate'->>'ad_group_id'
                   ORDER BY f.created_at DESC,f.id DESC LIMIT 1
               ) ff ON true
               LEFT JOIN recovery.analysis_artifacts sem ON sem.tenant_id=a.tenant_id AND sem.analysis_run_id=a.analysis_run_id
                   AND sem.artifact_kind='semantic_assessment' AND sem.external_id=('sem:'||split_part(ff.external_id,':',2))
               LEFT JOIN recovery.analysis_artifacts fit ON fit.tenant_id=a.tenant_id AND fit.analysis_run_id=a.analysis_run_id
                   AND fit.artifact_kind='business_fit_decision' AND fit.external_id=('fit:'||split_part(ff.external_id,':',2))
               LEFT JOIN LATERAL (
                   SELECT mm.event_type FROM recovery.mutation_events mm
                   WHERE mm.tenant_id=m.tenant_id AND mm.proposal_artifact_id=m.proposal_artifact_id
                   ORDER BY mm.occurred_at DESC,mm.id DESC LIMIT 1
               ) lm ON true
               ORDER BY latest.created_at DESC,latest.entry_id DESC""",
            (tenant_id,account_ids,tenant_id),
        )
        out=[]
        for row in cur.fetchall():
            x=dict(row); p=dict(x.get("proposal") or {}); candidate=p.get("candidate") or {}
            family=query_leak_family(semantic=dict(x.get("semantic_payload") or {}) or None,fit=dict(x.get("fit_payload") or {}) or None)
            x["case_id"]=x["proposal_artifact_id"]
            x["query"]=candidate.get("text"); x["campaign_id"]=candidate.get("campaign_id")
            x["leak_family"]=family.value if family is not None else "unclassified_query_mismatch"
            x["state"]=("rolled_back" if x.get("latest_mutation_type")=="rolled_back" else
                        "verified" if x.get("causal_status")=="verified" else
                        "inconclusive" if x.get("causal_status")=="inconclusive" else "verification_pending")
            x["observed_difference_vs_projection_micros"]=max(int(x.get("projected_prevented_micros") or 0)-int(x.get("observed_post_action_query_spend_micros") or 0),0)
            out.append(x)
        return out

    def recovery_center_overview(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            scope_kind,scope_id,scope_name,account_ids=self._recovery_scope(cur,tenant_id=tenant_id,account_id=account_id,portfolio_id=portfolio_id)
            current:dict[str,dict[str,int]]={}
            if account_ids:
                cur.execute(
                    """SELECT DISTINCT ON (s.account_id) s.account_id,s.currency_code,s.potentially_avoidable_observed_micros,s.unobserved_search_micros
                       FROM recovery.analysis_summaries s
                       JOIN recovery.analysis_runs r ON r.tenant_id=s.tenant_id AND r.id=s.analysis_run_id
                       WHERE s.tenant_id=%s AND s.account_id=ANY(%s) AND r.status='completed'
                       ORDER BY s.account_id,r.completed_at DESC NULLS LAST,s.created_at DESC,s.id DESC""",
                    (tenant_id,account_ids),)
                for r in cur.fetchall():
                    b=current.setdefault(str(r["currency_code"]),{"current_observed_candidate_micros":0,"current_unobserved_search_micros":0})
                    b["current_observed_candidate_micros"]+=int(r["potentially_avoidable_observed_micros"] or 0)
                    b["current_unobserved_search_micros"]+=int(r["unobserved_search_micros"] or 0)
            proof=self._recovery_proof_rows(cur,tenant_id=tenant_id,account_ids=account_ids)
            ledger_buckets=aggregate_latest_ledger(proof)
            currencies=sorted(set(current)|set(ledger_buckets))
            money=[]
            for cc in currencies:
                a=current.get(cc,{"current_observed_candidate_micros":0,"current_unobserved_search_micros":0}); b=ledger_buckets.get(cc,{})
                projected=int(b.get("projected_prevented_micros",0)); observed=int(b.get("observed_post_action_query_spend_micros",0))
                money.append({"currency_code":cc,**a,
                    "acted_on_historical_candidate_micros":int(b.get("acted_on_historical_candidate_micros",0)),
                    "projected_prevented_micros":projected,
                    "observed_post_action_query_spend_micros":observed,
                    "observed_difference_vs_projection_micros":max(projected-observed,0),
                    "verified_recovery_micros":int(b.get("verified_recovery_micros",0)),
                    "ledger_action_count":int(b.get("ledger_action_count",0)),"verified_action_count":int(b.get("verified_action_count",0)),
                    "inconclusive_action_count":int(b.get("inconclusive_action_count",0)),"verification_pending_action_count":int(b.get("verification_pending_action_count",0))})
            counts={"total":len(proof),"verified":0,"inconclusive":0,"verification_pending":0,"rolled_back":0}
            for row in proof: counts[row["state"]]=counts.get(row["state"],0)+1
            return {"scope_kind":scope_kind,"scope_id":scope_id,"scope_name":scope_name,"account_count":len(account_ids),
                    "money_by_currency":money,"case_counts":counts,"generated_at":datetime.now(timezone.utc),
                    "financial_classes_are_non_additive":True,"verified_recovery_requires_causal_evidence":True,
                    "note":"Current observed candidate, historical acted-on exposure, projection, post-action observed spend and verified recovery answer different questions and must never be added together. Unobserved search spend remains a coverage limitation, never inferred waste."}

    def recovery_center_cases(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, causal_status: str | None, limit: int) -> list[dict[str, Any]]:
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        if causal_status and causal_status not in {"not_evaluated","ineligible","inconclusive","verified"}: raise ValueError("invalid causal_status")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); _,_,_,ids=self._recovery_scope(cur,tenant_id=tenant_id,account_id=account_id,portfolio_id=portfolio_id)
            rows=self._recovery_proof_rows(cur,tenant_id=tenant_id,account_ids=ids)
            out=[]
            for x in rows:
                if causal_status and x["causal_status"]!=causal_status: continue
                out.append({k:x.get(k) for k in ("case_id","account_id","account_name","query","campaign_id","campaign_name","leak_family","state","currency_code","historical_candidate_micros","projected_prevented_micros","observed_post_action_query_spend_micros","observed_difference_vs_projection_micros","verified_recovery_micros","causal_status","created_at","mutation_event_id","applied_at")})
                out[-1]["ledger_created_at"]=out[-1].pop("created_at")
                if len(out)>=limit: break
            return out

    def recovery_center_breakdown(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, dimension: str) -> dict[str, Any]:
        if dimension not in {"account","campaign","leak_type"}: raise ValueError("dimension must be account, campaign or leak_type")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); _,_,_,ids=self._recovery_scope(cur,tenant_id=tenant_id,account_id=account_id,portfolio_id=portfolio_id)
            rows=self._recovery_proof_rows(cur,tenant_id=tenant_id,account_ids=ids)
        grouped:dict[tuple[str,str,str],dict[str,Any]]={}
        for x in rows:
            if dimension=="account": key,label=str(x["account_id"]),str(x["account_name"] or x["account_id"])
            elif dimension=="campaign": key=str(x.get("campaign_id") or "unknown"); label=str(x.get("campaign_name") or key)
            else: key=label=str(x.get("leak_family") or "unclassified_query_mismatch")
            g=grouped.setdefault((key,label,str(x["currency_code"])),{"key":key,"label":label,"currency_code":str(x["currency_code"]),"action_count":0,"historical_candidate_micros":0,"projected_prevented_micros":0,"observed_post_action_query_spend_micros":0,"verified_recovery_micros":0})
            g["action_count"]+=1
            for f in ("historical_candidate_micros","projected_prevented_micros","observed_post_action_query_spend_micros","verified_recovery_micros"): g[f]+=int(x.get(f) or 0)
        out=sorted(grouped.values(),key=lambda r:(r["currency_code"],-r["verified_recovery_micros"],-r["historical_candidate_micros"],r["label"]))
        return {"dimension":dimension,"rows":out,"note":"Breakdowns use only the latest Recovery Ledger snapshot for each exact mutation event. Currency buckets are never combined."}

    def recovery_center_timeline(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id); _,_,_,ids=self._recovery_scope(cur,tenant_id=tenant_id,account_id=account_id,portfolio_id=portfolio_id)
            if not ids: return {"rows":[],"note":"No accounts in scope."}
            cur.execute(
                """SELECT l.id AS entry_id,l.mutation_event_id,l.currency_code,l.historical_candidate_micros,l.projected_prevented_micros,
                          l.observed_post_action_query_spend_micros,l.verified_recovery_micros,l.causal_status,l.created_at
                   FROM recovery.recovery_ledger_entries l JOIN recovery.analysis_runs r ON r.tenant_id=l.tenant_id AND r.id=l.analysis_run_id
                   WHERE l.tenant_id=%s AND r.account_id=ANY(%s) AND l.mutation_event_id IS NOT NULL
                   ORDER BY l.created_at,l.id""",(tenant_id,ids),)
            source=[dict(r) for r in cur.fetchall()]
        latest:dict[str,dict[str,Any]]={}; by_day:dict[date,list[dict[str,Any]]]={}
        for r in source: by_day.setdefault(r["created_at"].date(),[]).append(r)
        points=[]
        for day in sorted(by_day):
            for r in by_day[day]: latest[str(r["mutation_event_id"])]=r
            buckets=aggregate_latest_ledger(latest.values())
            for cc,b in sorted(buckets.items()):
                points.append({"date":day,"currency_code":cc,"ledger_updates":len(by_day[day]),
                    "historical_candidate_micros":int(b["acted_on_historical_candidate_micros"]),"projected_prevented_micros":int(b["projected_prevented_micros"]),
                    "observed_post_action_query_spend_micros":int(b["observed_post_action_query_spend_micros"]),"verified_recovery_micros":int(b["verified_recovery_micros"])})
        return {"rows":points,"note":"Timeline values are end-of-day cumulative latest snapshots per mutation event; ledger revisions are not double counted."}

    # --- Epic 8 Monitoring & Alerts ---

    _MONITOR_DEFAULTS: dict[str, dict[str, Any]] = {
        "data_freshness": {"enabled": True, "severity_override": None, "config": {"warning_hours": 36, "critical_hours": 72}},
        "measurement_integrity": {"enabled": True, "severity_override": None, "config": {}},
        "job_health": {"enabled": True, "severity_override": None, "config": {}},
        "campaign_serving": {"enabled": True, "severity_override": None, "config": {}},
        # Statistical monitors are opt-in. Their thresholds are explicit customer configuration.
        "spend_anomaly": {"enabled": False, "severity_override": None, "config": {"baseline_days": 14, "recent_days": 3, "spend_multiplier": 2.0, "min_cost_delta_micros": 10000000, "min_baseline_daily_cost_micros": 5000000}},
        "conversion_drop": {"enabled": False, "severity_override": None, "config": {"baseline_days": 14, "recent_days": 3, "conversion_ratio": 0.30, "min_baseline_daily_conversions": 1.0, "min_recent_spend_ratio": 0.50}},
        "reconciliation": {"enabled": True, "severity_override": None, "config": {}},
        # Reserved until an exact applied-query recurrence evidence path exists.
        "query_recurrence": {"enabled": False, "severity_override": None, "config": {}},
    }

    @staticmethod
    def _validate_monitor_policy(monitor_type: str, config: dict[str, Any]) -> dict[str, Any]:
        if monitor_type not in PostgresApiRepository._MONITOR_DEFAULTS:
            raise ValueError("unsupported monitor_type")
        if not isinstance(config, dict):
            raise ValueError("monitor config must be an object")
        if monitor_type == "data_freshness":
            warning=int(config.get("warning_hours",36)); critical=int(config.get("critical_hours",72))
            if warning < 1 or critical <= warning or critical > 24*30:
                raise ValueError("data_freshness requires 1 <= warning_hours < critical_hours <= 720")
            return {"warning_hours":warning,"critical_hours":critical}
        if monitor_type == "spend_anomaly":
            baseline=int(config.get("baseline_days",14)); recent=int(config.get("recent_days",3))
            multiplier=float(config.get("spend_multiplier",2.0)); delta=int(config.get("min_cost_delta_micros",10_000_000)); min_base=int(config.get("min_baseline_daily_cost_micros",5_000_000))
            if baseline < 7 or baseline > 60 or recent < 2 or recent > 14:
                raise ValueError("spend_anomaly observation windows are invalid")
            if multiplier < 1.1 or multiplier > 20 or delta < 0 or min_base < 0:
                raise ValueError("spend_anomaly thresholds are invalid")
            return {"baseline_days":baseline,"recent_days":recent,"spend_multiplier":multiplier,"min_cost_delta_micros":delta,"min_baseline_daily_cost_micros":min_base}
        if monitor_type == "conversion_drop":
            baseline=int(config.get("baseline_days",14)); recent=int(config.get("recent_days",3)); ratio=float(config.get("conversion_ratio",0.30)); min_conv=float(config.get("min_baseline_daily_conversions",1.0)); min_spend_ratio=float(config.get("min_recent_spend_ratio",0.50))
            if baseline < 7 or baseline > 60 or recent < 2 or recent > 14 or ratio <= 0 or ratio >= 1:
                raise ValueError("conversion_drop thresholds are invalid")
            if min_conv < 0 or min_spend_ratio < 0 or min_spend_ratio > 2:
                raise ValueError("conversion_drop minimum evidence gates are invalid")
            return {"baseline_days":baseline,"recent_days":recent,"conversion_ratio":ratio,"min_baseline_daily_conversions":min_conv,"min_recent_spend_ratio":min_spend_ratio}
        if monitor_type == "query_recurrence" and bool(config.get("enabled", False)):
            raise ValueError("query recurrence is reserved until exact applied-query recurrence evidence is implemented")
        return dict(config)

    def monitoring_policies(self, *, tenant_id: UUID, account_id: UUID | None) -> list[dict[str, Any]]:
        # Latest event wins. Account-specific policy overrides the organization default.
        effective={k:{"monitor_type":k,"enabled":v["enabled"],"severity_override":v["severity_override"],"config":dict(v["config"]),"scope":"built_in_default","updated_at":None} for k,v in self._MONITOR_DEFAULTS.items()}
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """SELECT DISTINCT ON (account_id,monitor_type)
                          account_id,monitor_type,enabled,severity_override,config,occurred_at,id
                   FROM recovery.monitor_policy_events
                   WHERE tenant_id=%s AND (account_id IS NULL OR account_id=%s)
                   ORDER BY account_id,monitor_type,occurred_at DESC,id DESC""",
                (tenant_id,account_id),
            )
            org={}; acct={}
            for r in cur.fetchall():
                (org if r["account_id"] is None else acct)[r["monitor_type"]]=r
        for source,scope in ((org,"organization_default"),(acct,"account_override")):
            for k,r in source.items():
                effective[k]={"monitor_type":k,"enabled":bool(r["enabled"]),"severity_override":r["severity_override"],"config":dict(r["config"] or {}),"scope":scope,"updated_at":r["occurred_at"]}
        return [effective[k] for k in sorted(effective)]

    def monitoring_policy_event(self, *, tenant_id: UUID, account_id: UUID | None, actor: str, monitor_type: str, enabled: bool, severity_override: str | None, config: dict[str, Any]) -> dict[str, Any]:
        if severity_override is not None and severity_override not in {"info","warning","critical"}:
            raise ValueError("invalid severity_override")
        clean=self._validate_monitor_policy(monitor_type,config)
        if monitor_type == "query_recurrence" and enabled:
            raise ValueError("query recurrence monitoring is not available until exact recurrence evidence is implemented")
        if account_id is not None:
            self.ensure_account(tenant_id=tenant_id,account_id=account_id)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """INSERT INTO recovery.monitor_policy_events(tenant_id,account_id,monitor_type,enabled,severity_override,config,actor)
                   VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING occurred_at""",
                (tenant_id,account_id,monitor_type,enabled,severity_override,json.dumps(clean),actor),
            )
            updated=cur.fetchone()["occurred_at"]
        return {"monitor_type":monitor_type,"enabled":enabled,"severity_override":severity_override,"config":clean,"scope":"account_override" if account_id else "organization_default","updated_at":updated}

    @staticmethod
    def _alert_projection(instance: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        state=derive_alert_state(events).value
        severity=str(instance["initial_severity"])
        latest_evidence=dict(instance.get("first_evidence") or {})
        assigned_to=None
        last_seen=instance["opened_at"]
        occurrence=1
        for e in sorted(events,key=lambda x:(x["occurred_at"],str(x["id"]))):
            if e.get("severity"):
                severity=str(e["severity"])
            payload=dict(e.get("payload") or {})
            if e["event_type"] in {"opened","reopened","observed"}:
                if isinstance(payload.get("evidence"),dict): latest_evidence=dict(payload["evidence"])
                last_seen=e["occurred_at"]
                if e["event_type"] in {"observed","reopened"}: occurrence += 1
            if e["event_type"]=="assigned": assigned_to=payload.get("assigned_to")
            elif e["event_type"]=="unassigned": assigned_to=None
        return {
            "id":instance["id"],"account_id":instance["account_id"],"monitor_type":instance["monitor_type"],"source_key":instance["source_key"],
            "alert_fingerprint":instance["alert_fingerprint"],"generation":int(instance["generation"]),"initial_severity":instance["initial_severity"],
            "title":instance["title"],"first_evidence":dict(instance.get("first_evidence") or {}),"latest_evidence":latest_evidence,"opened_at":instance["opened_at"],
            "state":state,"severity":severity,"assigned_to":assigned_to,"last_seen_at":last_seen,"occurrence_count":occurrence,
        }

    def _alert_detail_with_cursor(self, cur: Any, *, tenant_id: UUID, alert_id: UUID) -> dict[str, Any]:
        cur.execute("SELECT * FROM recovery.monitor_alert_instances WHERE tenant_id=%s AND id=%s",(tenant_id,alert_id)); instance=cur.fetchone()
        if instance is None: raise ApiNotFound("monitor alert not found")
        cur.execute("SELECT id,event_type,severity,actor,payload,occurred_at FROM recovery.monitor_alert_events WHERE tenant_id=%s AND alert_instance_id=%s ORDER BY occurred_at,id",(tenant_id,alert_id))
        events=[dict(r) for r in cur.fetchall()]
        out=self._alert_projection(dict(instance),events); out["events"]=events; return out

    def monitoring_alert_detail(self, *, tenant_id: UUID, alert_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            return self._alert_detail_with_cursor(cur,tenant_id=tenant_id,alert_id=alert_id)

    def monitoring_alerts(self, *, tenant_id: UUID, account_id: UUID | None, state: str | None, severity: str | None, monitor_type: str | None, limit: int) -> list[dict[str, Any]]:
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        if state and state not in {"open","acknowledged","resolved","dismissed"}: raise ValueError("invalid alert state")
        if severity and severity not in {"info","warning","critical"}: raise ValueError("invalid alert severity")
        clauses=["tenant_id=%s"]; params:list[Any]=[tenant_id]
        if account_id is not None: clauses.append("account_id=%s"); params.append(account_id)
        if monitor_type: clauses.append("monitor_type=%s"); params.append(monitor_type)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(f"SELECT * FROM recovery.monitor_alert_instances WHERE {' AND '.join(clauses)} ORDER BY opened_at DESC,id DESC LIMIT %s",tuple(params+[limit*4]))
            instances=[dict(r) for r in cur.fetchall()]
            out=[]
            for inst in instances:
                cur.execute("SELECT id,event_type,severity,actor,payload,occurred_at FROM recovery.monitor_alert_events WHERE tenant_id=%s AND alert_instance_id=%s ORDER BY occurred_at,id",(tenant_id,inst["id"]))
                row=self._alert_projection(inst,[dict(e) for e in cur.fetchall()])
                if state and row["state"]!=state: continue
                if severity and row["severity"]!=severity: continue
                out.append(row)
                if len(out)>=limit: break
            return out

    def monitoring_overview(self, *, tenant_id: UUID, account_id: UUID | None) -> dict[str, Any]:
        alerts=self.monitoring_alerts(tenant_id=tenant_id,account_id=account_id,state=None,severity=None,monitor_type=None,limit=500)
        active=[a for a in alerts if a["state"] in {"open","acknowledged"}]
        counts={"open":0,"acknowledged":0,"critical":0,"warning":0,"info":0}
        by:dict[str,int]={}
        for a in active:
            counts[a["state"]]=counts.get(a["state"],0)+1; counts[a["severity"]]=counts.get(a["severity"],0)+1
            by[a["monitor_type"]]=by.get(a["monitor_type"],0)+1
        recent=sorted(active,key=lambda x:(x["last_seen_at"],str(x["id"])),reverse=True)[:10]
        return {"account_id":account_id,"counts":counts,"active_by_monitor_type":[{"monitor_type":k,"count":v} for k,v in sorted(by.items(),key=lambda x:(-x[1],x[0]))],"recent_alerts":recent,"generated_at":datetime.now(timezone.utc),"note":"Monitoring alerts are diagnostic evidence and are not automatically a waste or recovery claim."}

    def monitoring_alert_event(self, *, tenant_id: UUID, alert_id: UUID, actor: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            detail=self._alert_detail_with_cursor(cur,tenant_id=tenant_id,alert_id=alert_id)
            validate_alert_transition(detail["state"],event_type)
            clean=dict(payload or {})
            if event_type=="assigned":
                raw=clean.get("assigned_to")
                try: assigned=UUID(str(raw))
                except Exception as exc: raise ValueError("assigned event requires assigned_to UUID") from exc
                cur.execute("SELECT 1 FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s AND status='active'",(tenant_id,assigned))
                if cur.fetchone() is None: raise ApiConflict("assignee is not an active tenant member")
                clean["assigned_to"]=str(assigned)
            if event_type=="commented" and not str(clean.get("comment") or "").strip():
                raise ValueError("commented event requires comment")
            cur.execute("INSERT INTO recovery.monitor_alert_events(tenant_id,alert_instance_id,event_type,severity,actor,payload) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",(tenant_id,alert_id,event_type,detail["severity"],actor,json.dumps(clean)))
            return self._alert_detail_with_cursor(cur,tenant_id=tenant_id,alert_id=alert_id)

    def _persist_monitor_signal(self, cur: Any, *, tenant_id: UUID, account_id: UUID, actor: str, signal: MonitorSignal, severity_override: str | None) -> tuple[str, UUID]:
        base_fp=payload_sha256({"account_id":str(account_id),"monitor_type":signal.monitor_type,"source_key":signal.source_key})
        cur.execute("SELECT * FROM recovery.monitor_alert_instances WHERE tenant_id=%s AND account_id=%s AND alert_fingerprint=%s ORDER BY generation DESC LIMIT 1",(tenant_id,account_id,base_fp))
        previous=cur.fetchone(); previous_state=None; generation=None; condition_cleared_after_close=True
        if previous is not None:
            cur.execute("SELECT id,event_type,severity,actor,payload,occurred_at FROM recovery.monitor_alert_events WHERE tenant_id=%s AND alert_instance_id=%s ORDER BY occurred_at,id",(tenant_id,previous["id"]))
            previous_events=[dict(r) for r in cur.fetchall()]
            previous_state=derive_alert_state(previous_events).value; generation=int(previous["generation"])
            # Manual close is not proof the provider/system condition cleared.
            # A new incident generation is permitted only after an evaluator
            # recorded an auto_resolved event at/after the latest manual close.
            last_manual_close=max((i for i,e in enumerate(previous_events) if e["event_type"] in {"resolved","dismissed"}),default=-1)
            last_auto_clear=max((i for i,e in enumerate(previous_events) if e["event_type"]=="auto_resolved"),default=-1)
            condition_cleared_after_close=last_auto_clear >= last_manual_close
        action,new_generation,event_type=incident_observation_action(
            previous_state,generation,condition_cleared_after_close=condition_cleared_after_close
        )
        severity=severity_override or signal.severity.value
        if action=="new":
            alert_id=uuid4()
            cur.execute("""INSERT INTO recovery.monitor_alert_instances(id,tenant_id,account_id,monitor_type,source_key,alert_fingerprint,generation,initial_severity,title,first_evidence)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                        (alert_id,tenant_id,account_id,signal.monitor_type,signal.source_key,base_fp,new_generation,severity,signal.title,json.dumps(dict(signal.evidence))))
        else:
            alert_id=previous["id"]
        cur.execute("INSERT INTO recovery.monitor_alert_events(tenant_id,alert_instance_id,event_type,severity,actor,payload) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                    (tenant_id,alert_id,event_type,severity,actor,json.dumps({"evidence":dict(signal.evidence)})))
        return event_type,alert_id

    def monitoring_evaluate(self, *, tenant_id: UUID, account_id: UUID, actor: str) -> dict[str, Any]:
        self.ensure_account(tenant_id=tenant_id,account_id=account_id)
        policy_rows=self.monitoring_policies(tenant_id=tenant_id,account_id=account_id)
        policies={p["monitor_type"]:p for p in policy_rows}
        measurement=self.measurement_integrity_overview(tenant_id=tenant_id,account_id=account_id)
        signals:list[MonitorSignal]=[]; evaluated:set[str]=set()
        now=datetime.now(timezone.utc)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT id,window_start,window_end,completed_at,status FROM recovery.sync_runs
                           WHERE tenant_id=%s AND account_id=%s AND status='completed'
                           ORDER BY completed_at DESC,id DESC LIMIT 1""",(tenant_id,account_id))
            latest=cur.fetchone()
            if policies["data_freshness"]["enabled"]:
                evaluated.add("data_freshness")
                cfg=policies["data_freshness"]["config"]
                if latest is None:
                    signals.append(MonitorSignal("data_freshness","account-sync",AlertSeverity.CRITICAL,"No completed Google Ads sync",{"last_completed_sync":None,"financial_claim_supported":False,"causal_claim_supported":False}))
                else:
                    age=(now-latest["completed_at"]).total_seconds()/3600
                    threshold=None; sev=None
                    if age >= int(cfg.get("critical_hours",72)): threshold=int(cfg.get("critical_hours",72)); sev=AlertSeverity.CRITICAL
                    elif age >= int(cfg.get("warning_hours",36)): threshold=int(cfg.get("warning_hours",36)); sev=AlertSeverity.WARNING
                    if sev:
                        signals.append(MonitorSignal("data_freshness","account-sync",sev,"Google Ads data is stale",{"last_completed_sync":latest["completed_at"].isoformat(),"age_hours":round(age,1),"threshold_hours":threshold,"financial_claim_supported":False,"causal_claim_supported":False}))

            if policies["campaign_serving"]["enabled"] and latest is not None:
                evaluated.add("campaign_serving")
                cur.execute("""SELECT customer_id,campaign_id,campaign_name,advertising_channel_type,status,primary_status,primary_status_reasons
                               FROM recovery.campaign_health_observations WHERE tenant_id=%s AND sync_run_id=%s ORDER BY campaign_id""",(tenant_id,latest["id"]))
                for r in cur.fetchall():
                    signal=campaign_health_signal(CampaignHealthObservation(r["customer_id"],r["campaign_id"],r["campaign_name"],r["advertising_channel_type"],r["status"],r["primary_status"],tuple(r["primary_status_reasons"] or [])))
                    if signal: signals.append(signal)

            if policies["measurement_integrity"]["enabled"]:
                evaluated.add("measurement_integrity")
                conf=str(measurement["confidence"])
                if conf in {"blocked","constrained","unknown"}:
                    sev=AlertSeverity.CRITICAL if conf=="blocked" else AlertSeverity.WARNING
                    signals.append(MonitorSignal("measurement_integrity","account-measurement",sev,f"Measurement integrity is {conf}",{"confidence":conf,"issues":measurement.get("issues",[]),"conversion_dependent_claims_allowed":bool(measurement.get("conversion_dependent_claims_allowed")),"financial_claim_supported":False,"causal_claim_supported":False}))

            if policies["job_health"]["enabled"]:
                evaluated.add("job_health")
                cur.execute("""SELECT id,job_type,status,failure_code,completed_at FROM recovery.api_jobs
                               WHERE tenant_id=%s AND (payload->>'account_id')=%s AND status='failed'
                               ORDER BY completed_at DESC NULLS LAST,id DESC LIMIT 1""",(tenant_id,str(account_id)))
                failed=cur.fetchone()
                if failed and failed["completed_at"] and (now-failed["completed_at"]) <= timedelta(hours=24):
                    signals.append(MonitorSignal("job_health",f"job:{failed['id']}",AlertSeverity.WARNING,"Recent Recovery OS job failed",{"job_id":str(failed["id"]),"job_type":failed["job_type"],"failure_code":failed["failure_code"],"financial_claim_supported":False,"causal_claim_supported":False}))

            if policies["reconciliation"]["enabled"]:
                evaluated.add("reconciliation")
                cur.execute("""SELECT id,job_type,failure_code FROM recovery.api_jobs
                               WHERE tenant_id=%s AND (payload->>'account_id')=%s AND status='needs_reconciliation'
                               ORDER BY completed_at DESC NULLS LAST,id DESC LIMIT 20""",(tenant_id,str(account_id)))
                for r in cur.fetchall():
                    signals.append(MonitorSignal("reconciliation",f"job:{r['id']}",AlertSeverity.CRITICAL,"External effect needs reconciliation",{"job_id":str(r["id"]),"job_type":r["job_type"],"failure_code":r["failure_code"],"financial_claim_supported":False,"causal_claim_supported":False}))

            # Explicit statistical policies. Conversion monitoring uses only mature provider evidence.
            if latest is not None and policies["spend_anomaly"]["enabled"]:
                evaluated.add("spend_anomaly"); cfg=policies["spend_anomaly"]["config"]
                cur.execute("""SELECT campaign_id,max(campaign_name) AS campaign_name,currency_code,observation_date,sum(cost_micros)::bigint AS cost_micros
                               FROM recovery.campaign_performance_segments WHERE tenant_id=%s AND account_id=%s AND sync_run_id=%s
                               GROUP BY campaign_id,currency_code,observation_date ORDER BY campaign_id,observation_date""",(tenant_id,account_id,latest["id"]))
                grouped:dict[tuple[str,str,str],list[dict[str,Any]]]={}
                for r in cur.fetchall(): grouped.setdefault((r["campaign_id"],r["campaign_name"],r["currency_code"]),[]).append(dict(r))
                for (cid,name,cc),rows in grouped.items():
                    b=int(cfg.get("baseline_days",14)); rr=int(cfg.get("recent_days",3)); need=b+rr
                    if len(rows)<need: continue
                    baseline=rows[-need:-rr]; recent=rows[-rr:]
                    signal=spend_anomaly_signal(campaign_id=cid,campaign_name=name,currency_code=cc,baseline_daily_cost_micros=sum(x["cost_micros"] for x in baseline)/len(baseline),recent_daily_cost_micros=sum(x["cost_micros"] for x in recent)/len(recent),baseline_days=len(baseline),recent_days=len(recent),spend_multiplier=float(cfg.get("spend_multiplier",2.0)),min_cost_delta_micros=int(cfg.get("min_cost_delta_micros",10_000_000)),min_baseline_daily_cost_micros=int(cfg.get("min_baseline_daily_cost_micros",5_000_000)))
                    if signal: signals.append(signal)

            if latest is not None and policies["conversion_drop"]["enabled"] and measurement.get("conversion_dependent_claims_allowed"):
                evaluated.add("conversion_drop"); cfg=policies["conversion_drop"]["config"]
                lag=int(measurement["configured_conversion_lag_days"] or 0)
                mature_end=latest["window_end"]-timedelta(days=lag)
                cur.execute("""SELECT campaign_id,max(campaign_name) AS campaign_name,currency_code,observation_date,
                                      sum(cost_micros)::bigint AS cost_micros,sum(conversions) AS conversions
                               FROM recovery.campaign_performance_segments WHERE tenant_id=%s AND account_id=%s AND sync_run_id=%s AND observation_date<=%s
                               GROUP BY campaign_id,currency_code,observation_date ORDER BY campaign_id,observation_date""",(tenant_id,account_id,latest["id"],mature_end))
                grouped2:dict[tuple[str,str,str],list[dict[str,Any]]]={}
                for r in cur.fetchall(): grouped2.setdefault((r["campaign_id"],r["campaign_name"],r["currency_code"]),[]).append(dict(r))
                for (cid,name,cc),rows in grouped2.items():
                    b=int(cfg.get("baseline_days",14)); rr=int(cfg.get("recent_days",3)); need=b+rr
                    if len(rows)<need: continue
                    baseline=rows[-need:-rr]; recent=rows[-rr:]
                    signal=conversion_drop_signal(campaign_id=cid,campaign_name=name,currency_code=cc,baseline_daily_cost_micros=sum(x["cost_micros"] for x in baseline)/len(baseline),recent_daily_cost_micros=sum(x["cost_micros"] for x in recent)/len(recent),baseline_daily_conversions=sum((Decimal(str(x["conversions"])) for x in baseline),Decimal(0))/Decimal(len(baseline)),recent_daily_conversions=sum((Decimal(str(x["conversions"])) for x in recent),Decimal(0))/Decimal(len(recent)),baseline_days=len(baseline),recent_days=len(recent),conversion_ratio=float(cfg.get("conversion_ratio",0.30)),maturity_lag_days=lag,min_baseline_daily_conversions=Decimal(str(cfg.get("min_baseline_daily_conversions",1.0))),min_recent_spend_ratio=float(cfg.get("min_recent_spend_ratio",0.50)))
                    if signal: signals.append(signal)
            elif policies["conversion_drop"]["enabled"]:
                evaluated.add("conversion_drop")

            if policies["query_recurrence"]["enabled"]:
                # Reserved for a later exact query/action recurrence join. It is evaluated as no-signal here
                # rather than inferred from aggregate query volume.
                evaluated.add("query_recurrence")

            present:set[tuple[str,str]] = set(); opened=0; observed=0
            for signal in signals:
                policy=policies.get(signal.monitor_type) or {}
                event_type,alert_id=self._persist_monitor_signal(cur,tenant_id=tenant_id,account_id=account_id,actor=actor,signal=signal,severity_override=policy.get("severity_override"))
                present.add((signal.monitor_type,signal.source_key))
                if event_type=="opened": opened+=1
                else: observed+=1

            # Auto-resolve only incident families evaluated from a fresh pass and absent now.
            cur.execute("SELECT * FROM recovery.monitor_alert_instances WHERE tenant_id=%s AND account_id=%s ORDER BY generation DESC,opened_at DESC",(tenant_id,account_id))
            auto=0; seen_fp=set()
            for inst in cur.fetchall():
                key=(inst["monitor_type"],inst["source_key"])
                if key in seen_fp: continue
                seen_fp.add(key)
                if inst["monitor_type"] not in evaluated or key in present: continue
                cur.execute("SELECT id,event_type,severity,actor,payload,occurred_at FROM recovery.monitor_alert_events WHERE tenant_id=%s AND alert_instance_id=%s ORDER BY occurred_at,id",(tenant_id,inst["id"]))
                events=[dict(e) for e in cur.fetchall()]
                state=derive_alert_state(events).value
                # Record a real clear observation. This is required before a
                # later return of the same fingerprint can become a new
                # incident generation. It also distinguishes manual closure
                # from evaluator-observed recovery.
                last_manual_close=max((i for i,e in enumerate(events) if e["event_type"] in {"resolved","dismissed"}),default=-1)
                last_auto_clear=max((i for i,e in enumerate(events) if e["event_type"]=="auto_resolved"),default=-1)
                needs_clear_event = state in {"open","acknowledged"} or last_auto_clear < last_manual_close
                if needs_clear_event:
                    cur.execute("INSERT INTO recovery.monitor_alert_events(tenant_id,alert_instance_id,event_type,severity,actor,payload) VALUES (%s,%s,'auto_resolved',%s,%s,%s::jsonb)",(tenant_id,inst["id"],inst["initial_severity"],actor,json.dumps({"reason":"condition_not_observed_in_latest_evaluation"})))
                    auto+=1
        return {"account_id":account_id,"evaluated_monitor_types":sorted(evaluated),"signal_count":len(signals),"opened_count":opened,"observed_count":observed,"auto_resolved_count":auto,"evaluated_at":now}


    # --- Epic 9 reporting ---

    def list_report_generations(self, *, tenant_id: UUID, report_type: str | None, scope_kind: str | None, scope_id: str | None, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        clauses=["g.tenant_id=%s"]; params:list[Any]=[tenant_id]
        if report_type:
            ReportType(report_type); clauses.append("g.report_type=%s"); params.append(report_type)
        if scope_kind:
            ReportScope(scope_kind); clauses.append("g.scope_kind=%s"); params.append(scope_kind)
        if scope_id:
            clauses.append("g.scope_id=%s"); params.append(scope_id)
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(f"""
                SELECT g.id,g.report_type,g.template_version,g.schema_version,g.scope_kind,g.scope_id,
                       g.period_start,g.period_end,g.generated_by,g.source_job_id,g.schedule_id,
                       g.snapshot_sha256,g.generated_at,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object('format',a.artifact_format,'byte_size',a.byte_size,'sha256',a.artifact_sha256) ORDER BY a.artifact_format)
                                 FROM recovery.report_artifacts a WHERE a.tenant_id=g.tenant_id AND a.generation_id=g.id),'[]'::jsonb) AS artifacts
                FROM recovery.report_generations g
                WHERE {' AND '.join(clauses)}
                ORDER BY g.generated_at DESC,g.id DESC LIMIT %s
            """,tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def report_generation(self, *, tenant_id: UUID, generation_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""
                SELECT g.*,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object('format',a.artifact_format,'content_type',a.content_type,'byte_size',a.byte_size,'sha256',a.artifact_sha256) ORDER BY a.artifact_format)
                                 FROM recovery.report_artifacts a WHERE a.tenant_id=g.tenant_id AND a.generation_id=g.id),'[]'::jsonb) AS artifacts,
                       COALESCE((SELECT jsonb_agg(jsonb_build_object('recipient',d.recipient,'event_type',d.event_type,'detail',d.detail,'occurred_at',d.occurred_at) ORDER BY d.occurred_at,d.id)
                                 FROM recovery.report_delivery_events d WHERE d.tenant_id=g.tenant_id AND d.generation_id=g.id),'[]'::jsonb) AS deliveries
                FROM recovery.report_generations g WHERE g.tenant_id=%s AND g.id=%s
            """,(tenant_id,generation_id))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("report generation not found")
            return dict(row)

    def generate_report(self, *, tenant_id: UUID, generated_by: UUID, report_type: str, scope_kind: str, scope_id: str, period_start: date | None, period_end: date | None, source_job_id: UUID | None, schedule_id: UUID | None) -> dict[str, Any]:
        request=ReportRequest(report_type=ReportType(report_type),scope_kind=ReportScope(scope_kind),scope_id=scope_id,period_start=period_start,period_end=period_end)
        if source_job_id is not None:
            with self._connect() as conn, conn.cursor() as cur:
                self._set_user(cur,generated_by); self.core._set_tenant(cur,tenant_id)
                cur.execute("SELECT id FROM recovery.report_generations WHERE tenant_id=%s AND source_job_id=%s",(tenant_id,source_job_id))
                existing=cur.fetchone()
            if existing is not None:
                return self.report_generation(tenant_id=tenant_id,generation_id=existing["id"])

        generation_id=uuid4()
        snapshot=build_report_snapshot(repo=self,tenant_id=tenant_id,generation_id=generation_id,generated_by=generated_by,request=request)
        snapshot_hash=report_snapshot_sha256(snapshot)
        pdf=render_report_pdf(snapshot); csv_bytes=render_report_csv(snapshot)
        artifacts=[("pdf","application/pdf",pdf),("csv","text/csv; charset=utf-8",csv_bytes)]
        for fmt,ctype,content in artifacts:
            if not content or len(content)>10*1024*1024:
                raise ValueError(f"generated {fmt} artifact exceeds the 10 MiB report limit")

        duplicate_id=None
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,generated_by); self.core._set_tenant(cur,tenant_id)
            if source_job_id is not None:
                self.core._advisory_xact_lock(cur,f"report-generation:{tenant_id}:{source_job_id}")
                cur.execute("SELECT id FROM recovery.report_generations WHERE tenant_id=%s AND source_job_id=%s",(tenant_id,source_job_id))
                existing=cur.fetchone()
                if existing is not None:
                    duplicate_id=existing["id"]
            if duplicate_id is None:
                cur.execute("""
                    INSERT INTO recovery.report_generations(
                        id,tenant_id,report_type,template_version,schema_version,scope_kind,scope_id,
                        period_start,period_end,generated_by,source_job_id,schedule_id,snapshot_sha256,snapshot
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,(generation_id,tenant_id,report_type,snapshot["template_version"],snapshot["schema_version"],scope_kind,scope_id,period_start,period_end,generated_by,source_job_id,schedule_id,snapshot_hash,self._json(snapshot)))
                for fmt,ctype,content in artifacts:
                    digest=hashlib.sha256(content).hexdigest()
                    cur.execute("""INSERT INTO recovery.report_artifacts(tenant_id,generation_id,artifact_format,content_type,byte_size,artifact_sha256,content)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",(tenant_id,generation_id,fmt,ctype,len(content),digest,content))
        return self.report_generation(tenant_id=tenant_id,generation_id=duplicate_id or generation_id)

    def report_artifact(self, *, tenant_id: UUID, generation_id: UUID, artifact_format: str) -> dict[str, Any]:
        if artifact_format not in {"pdf","csv"}: raise ValueError("artifact format must be pdf or csv")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT a.content,a.content_type,a.byte_size,a.artifact_sha256,g.report_type,g.generated_at
                           FROM recovery.report_artifacts a JOIN recovery.report_generations g ON g.tenant_id=a.tenant_id AND g.id=a.generation_id
                           WHERE a.tenant_id=%s AND a.generation_id=%s AND a.artifact_format=%s""",(tenant_id,generation_id,artifact_format))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("report artifact not found")
            return dict(row)

    def create_report_share(self, *, tenant_id: UUID, user_id: UUID, actor: str, generation_id: UUID, expires_days: int) -> dict[str, Any]:
        if not 1 <= expires_days <= 90: raise ValueError("expires_days must be between 1 and 90")
        token,digest=new_share_token(tenant_id); share_id=uuid4()
        expires=datetime.now(timezone.utc)+timedelta(days=expires_days)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT 1 FROM recovery.report_generations WHERE tenant_id=%s AND id=%s",(tenant_id,generation_id))
            if cur.fetchone() is None: raise ApiNotFound("report generation not found")
            cur.execute("""INSERT INTO recovery.report_share_links(id,tenant_id,generation_id,token_sha256,created_by,expires_at)
                           VALUES (%s,%s,%s,%s,%s,%s)""",(share_id,tenant_id,generation_id,digest,user_id,expires))
            cur.execute("""INSERT INTO recovery.report_share_events(tenant_id,share_link_id,event_type,actor,payload)
                           VALUES (%s,%s,'created',%s,%s)""",(tenant_id,share_id,actor,self._json({"expires_at":expires.isoformat()})))
        return {"id":share_id,"generation_id":generation_id,"token":token,"expires_at":expires,"state":"active","created_at":datetime.now(timezone.utc)}

    def revoke_report_share(self, *, tenant_id: UUID, actor: str, share_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT generation_id,expires_at,created_at FROM recovery.report_share_links WHERE tenant_id=%s AND id=%s",(tenant_id,share_id))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("report share link not found")
            cur.execute("SELECT event_type FROM recovery.report_share_events WHERE tenant_id=%s AND share_link_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,share_id))
            latest=cur.fetchone()
            if latest is None or latest["event_type"]!="revoked":
                cur.execute("""INSERT INTO recovery.report_share_events(tenant_id,share_link_id,event_type,actor,payload)
                               VALUES (%s,%s,'revoked',%s,'{}'::jsonb)""",(tenant_id,share_id,actor))
        return {"id":share_id,"generation_id":row["generation_id"],"expires_at":row["expires_at"],"state":"revoked","created_at":row["created_at"]}

    def list_report_shares(self, *, tenant_id: UUID, generation_id: UUID | None) -> list[dict[str, Any]]:
        params:list[Any]=[tenant_id]; clause=""
        if generation_id is not None: clause=" AND s.generation_id=%s"; params.append(generation_id)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(f"""
                SELECT s.id,s.generation_id,s.expires_at,s.created_at,
                       CASE WHEN s.expires_at<=now() THEN 'expired'
                            WHEN COALESCE((SELECT e.event_type FROM recovery.report_share_events e WHERE e.tenant_id=s.tenant_id AND e.share_link_id=s.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'created')='revoked' THEN 'revoked'
                            ELSE 'active' END AS state,
                       (SELECT count(*)::int FROM recovery.report_share_events e WHERE e.tenant_id=s.tenant_id AND e.share_link_id=s.id AND e.event_type='accessed') AS access_count
                FROM recovery.report_share_links s WHERE s.tenant_id=%s {clause}
                ORDER BY s.created_at DESC,s.id DESC
            """,tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def _public_share_row(self, *, token: str, record_access: bool) -> tuple[UUID, dict[str, Any]]:
        tenant_id=parse_share_tenant(token); digest=share_token_sha256(token)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""
                SELECT s.id,s.generation_id,s.expires_at,
                       COALESCE((SELECT e.event_type FROM recovery.report_share_events e WHERE e.tenant_id=s.tenant_id AND e.share_link_id=s.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'created') AS latest_event
                FROM recovery.report_share_links s WHERE s.tenant_id=%s AND s.token_sha256=%s
            """,(tenant_id,digest))
            row=cur.fetchone()
            if row is None or row["expires_at"]<=datetime.now(timezone.utc) or row["latest_event"]=='revoked':
                raise ApiNotFound("report share link is invalid, expired, or revoked")
            if record_access:
                cur.execute("""INSERT INTO recovery.report_share_events(tenant_id,share_link_id,event_type,actor,payload)
                               VALUES (%s,%s,'accessed','public','{}'::jsonb)""",(tenant_id,row["id"]))
            return tenant_id,dict(row)

    def public_report(self, *, token: str, record_access: bool = True) -> dict[str, Any]:
        tenant_id,share=self._public_share_row(token=token,record_access=record_access)
        generation=self.report_generation(tenant_id=tenant_id,generation_id=share["generation_id"])
        return {"share":{"expires_at":share["expires_at"]},"generation":{"id":generation["id"],"report_type":generation["report_type"],"snapshot_sha256":generation["snapshot_sha256"],"generated_at":generation["generated_at"],"snapshot":generation["snapshot"],"artifacts":generation["artifacts"]}}

    def public_report_artifact(self, *, token: str, artifact_format: str) -> dict[str, Any]:
        tenant_id,share=self._public_share_row(token=token,record_access=False)
        return self.report_artifact(tenant_id=tenant_id,generation_id=share["generation_id"],artifact_format=artifact_format)

    def list_report_schedules(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""
                SELECT DISTINCT ON (schedule_id)
                       id,schedule_id,report_type,scope_kind,scope_id,frequency,timezone_name,hour,minute,weekday,day_of_month,recipients,enabled,actor_user_id,occurred_at
                FROM recovery.report_schedule_events WHERE tenant_id=%s
                ORDER BY schedule_id,occurred_at DESC,id DESC
            """,(tenant_id,))
            return [dict(r) for r in cur.fetchall()]

    def record_report_schedule(self, *, tenant_id: UUID, user_id: UUID, schedule_id: UUID | None, report_type: str, scope_kind: str, scope_id: str, frequency: str, timezone_name: str, hour: int, minute: int, weekday: int | None, day_of_month: int | None, recipients: list[str], enabled: bool) -> dict[str, Any]:
        rt=ReportType(report_type); sk=ReportScope(scope_kind)
        if sk not in REPORT_SCOPE_RULES[rt]: raise ValueError("report type does not support selected scope")
        sid=schedule_id or uuid4()
        spec=ScheduleDefinition(schedule_id=sid,report_type=rt,scope_kind=sk,scope_id=scope_id,frequency=frequency,timezone_name=timezone_name,hour=hour,minute=minute,weekday=weekday,day_of_month=day_of_month,recipients=tuple(recipients),enabled=enabled)
        if sk is ReportScope.ACCOUNT: self.ensure_account(tenant_id=tenant_id,account_id=UUID(scope_id))
        elif sk is ReportScope.PORTFOLIO: self.portfolio_detail(tenant_id=tenant_id,portfolio_id=UUID(scope_id))
        elif scope_id!=str(tenant_id): raise ValueError("organization schedule scope_id must equal tenant_id")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.report_schedule_events(
                    tenant_id,schedule_id,report_type,scope_kind,scope_id,frequency,timezone_name,hour,minute,weekday,day_of_month,recipients,enabled,actor_user_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id,schedule_id,report_type,scope_kind,scope_id,frequency,timezone_name,hour,minute,weekday,day_of_month,recipients,enabled,actor_user_id,occurred_at
                """,(tenant_id,sid,rt.value,sk.value,scope_id,frequency,timezone_name,hour,minute,weekday,day_of_month,self._json(list(spec.recipients)),enabled,user_id))
            return dict(cur.fetchone())

    def report_schedule(self, *, tenant_id: UUID, schedule_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT id,schedule_id,report_type,scope_kind,scope_id,frequency,timezone_name,hour,minute,weekday,day_of_month,recipients,enabled,actor_user_id,occurred_at
                           FROM recovery.report_schedule_events WHERE tenant_id=%s AND schedule_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1""",(tenant_id,schedule_id))
            row=cur.fetchone()
            if row is None: raise ApiNotFound("report schedule not found")
            return dict(row)

    def record_report_delivery(self, *, tenant_id: UUID, generation_id: UUID, schedule_id: UUID | None, recipient: str, event_type: str, detail: str | None) -> None:
        if event_type not in {"prepared","sent","failed","ambiguous","skipped_not_configured"}: raise ValueError("invalid report delivery event")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.report_delivery_events(tenant_id,generation_id,schedule_id,recipient,event_type,detail)
                           VALUES (%s,%s,%s,%s,%s,%s)""",(tenant_id,generation_id,schedule_id,recipient,event_type,detail))

    # --- Epic 10 organization / agency operations ---
    def _record_org_activity(self, cur, *, tenant_id: UUID, actor_user_id: UUID, event_type: str, target_type: str, target_id: str, payload: dict[str, Any] | None = None) -> None:
        cur.execute(
            """INSERT INTO recovery.organization_activity_events(tenant_id,actor_user_id,event_type,target_type,target_id,payload)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (tenant_id,actor_user_id,event_type,target_type,target_id,self._json(payload or {})),
        )

    def list_organization_members(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute(
                """SELECT m.user_id,u.email,m.role,m.status,m.account_access_mode,m.client_portal,m.created_at,m.updated_at
                   FROM recovery.tenant_memberships m JOIN recovery.app_users u ON u.id=m.user_id
                   WHERE m.tenant_id=%s ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'analyst' THEN 2 ELSE 3 END,lower(COALESCE(u.email,'')),m.user_id""",
                (tenant_id,),
            )
            rows=[dict(r) for r in cur.fetchall()]
        assignments=self.account_assignments(tenant_id=tenant_id)
        by_user:dict[UUID,list[dict[str,Any]]]={}
        for a in assignments: by_user.setdefault(a["user_id"],[]).append(a)
        for row in rows:
            row["accessible_account_count"]=len(self.accessible_account_ids(tenant_id=tenant_id,user_id=row["user_id"])) if row["status"]=="active" else 0
            row["assignments"]=by_user.get(row["user_id"],[])
        return rows

    def _invite_projection(self, *, tenant_id: UUID, invite_id: UUID | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            where="AND i.id=%s" if invite_id else ""
            params=(tenant_id,invite_id) if invite_id else (tenant_id,)
            cur.execute(
                f"""SELECT i.id,i.email,i.role,i.account_access_mode,i.client_portal,i.expires_at,i.created_at,
                           e.event_type AS latest_event
                    FROM recovery.organization_invites i
                    LEFT JOIN LATERAL (
                      SELECT event_type FROM recovery.organization_invite_events e
                      WHERE e.tenant_id=i.tenant_id AND e.invite_id=i.id
                      ORDER BY occurred_at DESC,id DESC LIMIT 1
                    ) e ON true
                    WHERE i.tenant_id=%s {where}
                    ORDER BY i.created_at DESC,i.id DESC""",params)
            rows=[dict(r) for r in cur.fetchall()]
        now=datetime.now(timezone.utc)
        for r in rows:
            r["state"]=r.pop("latest_event") or ("expired" if r["expires_at"]<=now else "pending")
            r["token"]=None
        return rows

    def create_organization_invite(self, *, tenant_id: UUID, actor_user_id: UUID, actor_role: TenantRole, email: str, role: str, account_access_mode: str, client_portal: bool, expires_days: int) -> dict[str, Any]:
        email=normalize_email(email); validate_access_shape(role=role,account_access_mode=account_access_mode,client_portal=client_portal)
        if expires_days<1 or expires_days>30: raise ValueError("expires_days must be between 1 and 30")
        try: validate_owner_management(actor_role=actor_role.value,target_role=role)
        except PermissionError as exc: raise ApiConflict(str(exc)) from exc
        token=new_invite_token(str(tenant_id)); digest=invite_token_sha256(token); expires=datetime.now(timezone.utc)+timedelta(days=expires_days)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            self.core._advisory_xact_lock(cur,f"organization-invite:{tenant_id}:{email}")
            cur.execute("SELECT 1 FROM recovery.tenant_memberships m JOIN recovery.app_users u ON u.id=m.user_id WHERE m.tenant_id=%s AND lower(u.email)=%s AND m.status='active'",(tenant_id,email))
            if cur.fetchone(): raise ApiConflict("this email already has active organization access")
            cur.execute(
                """SELECT i.id FROM recovery.organization_invites i
                   WHERE i.tenant_id=%s AND i.email=%s AND i.expires_at>now()
                     AND NOT EXISTS (SELECT 1 FROM recovery.organization_invite_events e WHERE e.tenant_id=i.tenant_id AND e.invite_id=i.id AND e.event_type IN ('accepted','revoked','expired'))
                   LIMIT 1""",(tenant_id,email))
            if cur.fetchone(): raise ApiConflict("an active invitation already exists for this email")
            cur.execute(
                """INSERT INTO recovery.organization_invites(tenant_id,email,role,account_access_mode,client_portal,token_sha256,expires_at,invited_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id,email,role,account_access_mode,client_portal,expires_at,created_at""",
                (tenant_id,email,role,account_access_mode,client_portal,digest,expires,actor_user_id),
            )
            row=dict(cur.fetchone()); row["state"]="pending"; row["token"]=token
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type="member_invited",target_type="invitation",target_id=str(row["id"]),payload={"email":email,"role":role,"account_access_mode":account_access_mode,"client_portal":client_portal})
            return row

    def list_organization_invites(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        return self._invite_projection(tenant_id=tenant_id)

    def revoke_organization_invite(self, *, tenant_id: UUID, invite_id: UUID, actor_user_id: UUID, actor_role: TenantRole) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            self.core._advisory_xact_lock(cur,f"organization-invite-id:{tenant_id}:{invite_id}")
            cur.execute("SELECT role,expires_at FROM recovery.organization_invites WHERE tenant_id=%s AND id=%s FOR SHARE",(tenant_id,invite_id)); invite=cur.fetchone()
            if invite is None: raise ApiNotFound("invitation not found")
            try: validate_owner_management(actor_role=actor_role.value,target_role=invite["role"])
            except PermissionError as exc: raise ApiConflict(str(exc)) from exc
            cur.execute("SELECT event_type FROM recovery.organization_invite_events WHERE tenant_id=%s AND invite_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,invite_id)); latest=cur.fetchone()
            state=(latest["event_type"] if latest else ("expired" if invite["expires_at"]<=datetime.now(timezone.utc) else "pending"))
            if state!="pending": raise ApiConflict("only pending invitations can be revoked")
            cur.execute("INSERT INTO recovery.organization_invite_events(tenant_id,invite_id,event_type,actor_user_id) VALUES (%s,%s,'revoked',%s)",(tenant_id,invite_id,actor_user_id))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type="invitation_revoked",target_type="invitation",target_id=str(invite_id),payload={})
        return self._invite_projection(tenant_id=tenant_id,invite_id=invite_id)[0]

    def accept_organization_invite(self, *, token: str, principal_user_id: UUID, principal_email: str | None) -> dict[str, Any]:
        try: tenant_id=UUID(token.split('.',1)[0])
        except Exception as exc: raise ApiNotFound("invitation is invalid") from exc
        email=normalize_email(principal_email or "")
        digest=invite_token_sha256(token)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,principal_user_id); self.core._set_tenant(cur,tenant_id)
            self.core._advisory_xact_lock(cur,f"organization-invite-token:{tenant_id}:{digest}")
            cur.execute(
                """SELECT i.id,i.email,i.role,i.account_access_mode,i.client_portal,i.expires_at,t.display_name AS tenant_name,
                          (SELECT event_type FROM recovery.organization_invite_events e WHERE e.tenant_id=i.tenant_id AND e.invite_id=i.id ORDER BY occurred_at DESC,id DESC LIMIT 1) AS latest_event
                   FROM recovery.organization_invites i JOIN recovery.tenants t ON t.id=i.tenant_id
                   WHERE i.tenant_id=%s AND i.token_sha256=%s
                   FOR SHARE OF i""",(tenant_id,digest))
            invite=cur.fetchone()
            if invite is None or invite["expires_at"]<=datetime.now(timezone.utc) or invite["latest_event"] in {"accepted","revoked","expired"}: raise ApiNotFound("invitation is invalid, expired, or already used")
            if email != invite["email"]: raise ApiConflict("sign in with the email address that was invited")
            cur.execute("SELECT role,status FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s",(tenant_id,principal_user_id))
            existing=cur.fetchone()
            if existing is not None and existing["status"]=="active": raise ApiConflict("user already has active organization access")
            cur.execute(
                """INSERT INTO recovery.tenant_memberships(tenant_id,user_id,role,status,account_access_mode,client_portal)
                   VALUES (%s,%s,%s,'active',%s,%s)
                   ON CONFLICT (tenant_id,user_id) DO UPDATE SET role=EXCLUDED.role,status='active',account_access_mode=EXCLUDED.account_access_mode,client_portal=EXCLUDED.client_portal,updated_at=now()""",
                (tenant_id,principal_user_id,invite["role"],invite["account_access_mode"],invite["client_portal"]),
            )
            cur.execute("INSERT INTO recovery.organization_invite_events(tenant_id,invite_id,event_type,actor_user_id) VALUES (%s,%s,'accepted',%s)",(tenant_id,invite["id"],principal_user_id))
            cur.execute(
                """INSERT INTO recovery.membership_admin_events(tenant_id,user_id,actor_user_id,event_type,role,status,account_access_mode,client_portal,source_invite_id)
                   VALUES (%s,%s,%s,%s,%s,'active',%s,%s,%s)""",
                (tenant_id,principal_user_id,principal_user_id,"reactivated" if existing else "joined",invite["role"],invite["account_access_mode"],invite["client_portal"],invite["id"]),
            )
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=principal_user_id,event_type="member_joined",target_type="member",target_id=str(principal_user_id),payload={"role":invite["role"],"source_invite_id":str(invite["id"])})
            return {"tenant_id":tenant_id,"tenant_name":invite["tenant_name"],"role":invite["role"],"account_access_mode":invite["account_access_mode"],"client_portal":bool(invite["client_portal"])}

    def update_organization_member(self, *, tenant_id: UUID, actor_user_id: UUID, actor_role: TenantRole, user_id: UUID, role: str, status: str, account_access_mode: str, client_portal: bool) -> dict[str, Any]:
        validate_access_shape(role=role,account_access_mode=account_access_mode,client_portal=client_portal)
        if status not in {"active","disabled"}: raise ValueError("invalid membership status")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            # Serialize every privileged membership transition for the tenant. Without this,
            # two Owners could concurrently demote themselves after each sees the other active.
            self.core._advisory_xact_lock(cur,f"organization-membership-admin:{tenant_id}")
            cur.execute("SELECT role,status,account_access_mode,client_portal FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s FOR UPDATE",(tenant_id,user_id))
            old=cur.fetchone()
            if old is None: raise ApiNotFound("organization member not found")
            cur.execute("SELECT count(*)::int AS n FROM recovery.tenant_memberships WHERE tenant_id=%s AND role='owner' AND status='active' AND user_id<>%s",(tenant_id,user_id))
            other_owners=int(cur.fetchone()["n"])
            try:
                validate_member_transition(actor_role=actor_role.value,current_role=old["role"],current_status=old["status"],new_role=role,new_status=status,other_active_owner_count=other_owners)
            except (PermissionError,ValueError) as exc:
                raise ApiConflict(str(exc)) from exc
            cur.execute("UPDATE recovery.tenant_memberships SET role=%s,status=%s,account_access_mode=%s,client_portal=%s,updated_at=now() WHERE tenant_id=%s AND user_id=%s",(role,status,account_access_mode,client_portal,tenant_id,user_id))
            if old["role"]!=role: event="role_changed"
            elif old["status"]!=status: event="disabled" if status=="disabled" else "reactivated"
            elif old["account_access_mode"]!=account_access_mode: event="access_mode_changed"
            else: event="client_portal_changed"
            cur.execute("""INSERT INTO recovery.membership_admin_events(tenant_id,user_id,actor_user_id,event_type,role,status,account_access_mode,client_portal,payload)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(tenant_id,user_id,actor_user_id,event,role,status,account_access_mode,client_portal,self._json({"previous":{"role":old["role"],"status":old["status"],"account_access_mode":old["account_access_mode"],"client_portal":bool(old["client_portal"])}})))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"member_{event}",target_type="member",target_id=str(user_id),payload={"role":role,"status":status,"account_access_mode":account_access_mode,"client_portal":client_portal})
        return next(r for r in self.list_organization_members(tenant_id=tenant_id) if r["user_id"]==user_id)

    def member_account_access_matrix(self, *, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
        allowed=self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT account_access_mode FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s",(tenant_id,user_id)); m=cur.fetchone()
            if m is None: raise ApiNotFound("organization member not found")
            cur.execute("SELECT id,customer_id,descriptive_name FROM recovery.google_ads_accounts WHERE tenant_id=%s ORDER BY lower(descriptive_name),customer_id",(tenant_id,)); accounts=[dict(r) for r in cur.fetchall()]
            direct:set[UUID]=set()
            cur.execute("""SELECT account_id FROM (SELECT DISTINCT ON (account_id) account_id,event_type FROM recovery.member_account_access_events WHERE tenant_id=%s AND user_id=%s ORDER BY account_id,occurred_at DESC,id DESC) x WHERE event_type='grant'""",(tenant_id,user_id)); direct={r["account_id"] for r in cur.fetchall()}
            cur.execute("""WITH member_ws AS (SELECT workspace_id FROM (SELECT DISTINCT ON(workspace_id) workspace_id,event_type FROM recovery.client_workspace_member_events WHERE tenant_id=%s AND user_id=%s ORDER BY workspace_id,occurred_at DESC,id DESC) x WHERE event_type='grant'), ws_accounts AS (SELECT workspace_id,account_id FROM (SELECT DISTINCT ON(workspace_id,account_id) workspace_id,account_id,event_type FROM recovery.client_workspace_account_events WHERE tenant_id=%s ORDER BY workspace_id,account_id,occurred_at DESC,id DESC) x WHERE event_type='link'), ws_names AS (SELECT workspace_id,name FROM (SELECT DISTINCT ON(workspace_id) workspace_id,name,event_type FROM recovery.client_workspace_events WHERE tenant_id=%s ORDER BY workspace_id,occurred_at DESC,id DESC) x WHERE event_type<>'archived') SELECT wa.account_id,wn.name FROM ws_accounts wa JOIN member_ws mw USING(workspace_id) JOIN ws_names wn USING(workspace_id)""",(tenant_id,user_id,tenant_id,tenant_id))
            ws_sources:dict[UUID,list[str]]={}
            for r in cur.fetchall(): ws_sources.setdefault(r["account_id"],[]).append(f"client:{r['name']}")
        out=[]
        for a in accounts:
            sources=[]
            if m["account_access_mode"]=="all_accounts": sources.append("organization")
            if a["id"] in direct: sources.append("direct")
            sources.extend(ws_sources.get(a["id"],[]))
            out.append({**a,"accessible":a["id"] in allowed,"sources":sources})
        return out

    def record_member_account_access(self, *, tenant_id: UUID, actor_user_id: UUID, user_id: UUID, account_id: UUID, action: str, reason: str | None) -> dict[str, Any]:
        if action not in {"grant","revoke"}: raise ValueError("invalid account access action")
        self.ensure_account(tenant_id=tenant_id,account_id=account_id)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT role,status,account_access_mode FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s",(tenant_id,user_id)); m=cur.fetchone()
            if m is None or m["status"]!="active": raise ApiNotFound("active organization member not found")
            if m["account_access_mode"]!="selected_accounts": raise ApiConflict("direct grants apply only to selected_accounts memberships")
            cur.execute("INSERT INTO recovery.member_account_access_events(tenant_id,user_id,account_id,actor_user_id,event_type,reason) VALUES (%s,%s,%s,%s,%s,%s)",(tenant_id,user_id,account_id,actor_user_id,action,reason))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"account_access_{action}",target_type="member_account",target_id=f"{user_id}:{account_id}",payload={"user_id":str(user_id),"account_id":str(account_id),"reason":reason})
        return {"user_id":user_id,"account_id":account_id,"action":action,"accessible":account_id in self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id)}

    def _workspace_rows(self, *, tenant_id: UUID, workspace_id: UUID | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            extra="WHERE workspace_id=%s" if workspace_id else ""; params=(workspace_id,) if workspace_id else ()
            cur.execute(f"""SELECT DISTINCT ON (workspace_id) workspace_id,name,external_reference,notes,event_type,occurred_at
                            FROM recovery.client_workspace_events {extra}
                            ORDER BY workspace_id,occurred_at DESC,id DESC""",params)
            return [{**dict(r),"state":"archived" if r["event_type"]=="archived" else "active"} for r in cur.fetchall()]

    def list_client_workspaces(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        return [self.client_workspace_detail(tenant_id=tenant_id,workspace_id=r["workspace_id"]) for r in self._workspace_rows(tenant_id=tenant_id)]

    def client_workspace_detail(self, *, tenant_id: UUID, workspace_id: UUID) -> dict[str, Any]:
        rows=self._workspace_rows(tenant_id=tenant_id,workspace_id=workspace_id)
        if not rows: raise ApiNotFound("client workspace not found")
        out=rows[0]
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT a.id,a.customer_id,a.descriptive_name,a.currency_code FROM recovery.google_ads_accounts a JOIN (
                    SELECT DISTINCT ON (account_id) account_id,event_type FROM recovery.client_workspace_account_events WHERE tenant_id=%s AND workspace_id=%s ORDER BY account_id,occurred_at DESC,id DESC
                  ) x ON x.account_id=a.id WHERE a.tenant_id=%s AND x.event_type='link' ORDER BY lower(a.descriptive_name),a.customer_id""",(tenant_id,workspace_id,tenant_id))
            out["accounts"]=[dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT u.id AS user_id,u.email,m.role,m.client_portal FROM recovery.app_users u JOIN recovery.tenant_memberships m ON m.user_id=u.id AND m.tenant_id=%s JOIN (
                    SELECT DISTINCT ON (user_id) user_id,event_type FROM recovery.client_workspace_member_events WHERE tenant_id=%s AND workspace_id=%s ORDER BY user_id,occurred_at DESC,id DESC
                  ) x ON x.user_id=u.id WHERE x.event_type='grant' AND m.status='active' ORDER BY lower(COALESCE(u.email,'')),u.id""",(tenant_id,tenant_id,workspace_id))
            out["members"]=[dict(r) for r in cur.fetchall()]
        return out

    def record_client_workspace(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID | None, action: str, name: str, external_reference: str | None, notes: str | None) -> dict[str, Any]:
        if action not in {"created","update","archive","restore","updated","archived","restored"}: raise ValueError("invalid client workspace action")
        mapping={"update":"updated","archive":"archived","restore":"restored"}; event=mapping.get(action,action)
        wid=workspace_id or uuid4()
        if workspace_id is None and event!="created": raise ValueError("new client workspace must use created action")
        if workspace_id is not None and event=="created": raise ValueError("existing client workspace cannot be created again")
        if workspace_id is not None: self.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.client_workspace_events(tenant_id,workspace_id,actor_user_id,event_type,name,external_reference,notes)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",(tenant_id,wid,actor_user_id,event,name.strip(),external_reference,notes))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"client_workspace_{event}",target_type="client_workspace",target_id=str(wid),payload={"name":name.strip()})
        return self.client_workspace_detail(tenant_id=tenant_id,workspace_id=wid)

    def record_client_workspace_account(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID, account_id: UUID, action: str) -> dict[str, Any]:
        if action not in {"link","unlink"}: raise ValueError("invalid client workspace account action")
        self.ensure_account(tenant_id=tenant_id,account_id=account_id); ws=self.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)
        if ws["state"]!="active": raise ApiConflict("archived client workspace cannot be changed")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("INSERT INTO recovery.client_workspace_account_events(tenant_id,workspace_id,account_id,actor_user_id,event_type) VALUES (%s,%s,%s,%s,%s)",(tenant_id,workspace_id,account_id,actor_user_id,action))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"client_account_{action}",target_type="client_workspace",target_id=str(workspace_id),payload={"account_id":str(account_id)})
        return self.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)

    def record_client_workspace_member(self, *, tenant_id: UUID, actor_user_id: UUID, workspace_id: UUID, user_id: UUID, action: str) -> dict[str, Any]:
        if action not in {"grant","revoke"}: raise ValueError("invalid client workspace member action")
        ws=self.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)
        if ws["state"]!="active": raise ApiConflict("archived client workspace cannot be changed")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT status,account_access_mode FROM recovery.tenant_memberships WHERE tenant_id=%s AND user_id=%s",(tenant_id,user_id)); m=cur.fetchone()
            if m is None or m["status"]!="active": raise ApiNotFound("active organization member not found")
            if m["account_access_mode"]!="selected_accounts": raise ApiConflict("client workspace grants apply only to selected_accounts memberships")
            cur.execute("INSERT INTO recovery.client_workspace_member_events(tenant_id,workspace_id,user_id,actor_user_id,event_type) VALUES (%s,%s,%s,%s,%s)",(tenant_id,workspace_id,user_id,actor_user_id,action))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"client_member_{action}",target_type="client_workspace",target_id=str(workspace_id),payload={"user_id":str(user_id)})
        return self.client_workspace_detail(tenant_id=tenant_id,workspace_id=workspace_id)

    def account_assignments(self, *, tenant_id: UUID, account_id: UUID | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            extra="AND e.account_id=%s" if account_id else ""; params=(tenant_id,account_id) if account_id else (tenant_id,)
            cur.execute(f"""SELECT x.account_id,x.user_id,u.email,x.responsibility,x.event_type AS state,x.occurred_at FROM (
                    SELECT DISTINCT ON (account_id,user_id,responsibility) account_id,user_id,responsibility,event_type,occurred_at,id
                    FROM recovery.account_assignment_events e WHERE e.tenant_id=%s {extra}
                    ORDER BY account_id,user_id,responsibility,occurred_at DESC,id DESC
                  ) x JOIN recovery.app_users u ON u.id=x.user_id WHERE x.event_type='assign' ORDER BY x.account_id,x.responsibility,lower(COALESCE(u.email,''))""",params)
            return [{**dict(r),"state":"assigned"} for r in cur.fetchall()]

    def record_account_assignment(self, *, tenant_id: UUID, actor_user_id: UUID, account_id: UUID, user_id: UUID, responsibility: str, action: str, note: str | None) -> dict[str, Any]:
        if responsibility not in {"lead","analyst","approver","client_contact"}: raise ValueError("invalid account responsibility")
        if action not in {"assign","unassign"}: raise ValueError("invalid assignment action")
        self.ensure_account(tenant_id=tenant_id,account_id=account_id)
        if action=="assign" and account_id not in self.accessible_account_ids(tenant_id=tenant_id,user_id=user_id): raise ApiConflict("member must have account access before assignment")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,actor_user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("INSERT INTO recovery.account_assignment_events(tenant_id,account_id,user_id,actor_user_id,responsibility,event_type,note) VALUES (%s,%s,%s,%s,%s,%s,%s)",(tenant_id,account_id,user_id,actor_user_id,responsibility,action,note))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=actor_user_id,event_type=f"account_{action}ment",target_type="account_assignment",target_id=f"{account_id}:{user_id}:{responsibility}",payload={"account_id":str(account_id),"user_id":str(user_id),"responsibility":responsibility,"note":note})
        matches=[r for r in self.account_assignments(tenant_id=tenant_id,account_id=account_id) if r["user_id"]==user_id and r["responsibility"]==responsibility]
        return matches[0] if matches else {"account_id":account_id,"user_id":user_id,"email":None,"responsibility":responsibility,"state":"unassigned","occurred_at":datetime.now(timezone.utc)}

    def organization_activity(self, *, tenant_id: UUID, limit: int = 200) -> list[dict[str, Any]]:
        if limit<1 or limit>500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT e.id,e.actor_user_id,u.email AS actor_email,e.event_type,e.target_type,e.target_id,e.occurred_at,e.payload
                           FROM recovery.organization_activity_events e LEFT JOIN recovery.app_users u ON u.id=e.actor_user_id
                           WHERE e.tenant_id=%s ORDER BY e.occurred_at DESC,e.id DESC LIMIT %s""",(tenant_id,limit))
            return [dict(r) for r in cur.fetchall()]

    # --- V1 customer Security & Data / Help & Support ---

    def customer_support_cases(self, *, tenant_id: UUID, user_id: UUID, include_all: bool, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 300: raise ValueError("limit must be between 1 and 300")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            own="" if include_all else "AND c.created_by=%s"; params=(tenant_id,limit) if include_all else (tenant_id,user_id,limit)
            cur.execute(f"""SELECT c.id,c.account_id,c.created_by,u.email AS created_by_email,c.category,c.subject,c.initial_body,c.created_at,
                                   COALESCE((SELECT e.event_type FROM recovery.customer_support_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id AND e.event_type IN ('closed','reopened') ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'opened') AS state,
                                   (SELECT count(*)::int FROM recovery.customer_support_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id AND e.event_type='commented') AS comment_count,
                                   (SELECT max(e.occurred_at) FROM recovery.customer_support_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id) AS last_event_at
                            FROM recovery.customer_support_cases c LEFT JOIN recovery.app_users u ON u.id=c.created_by
                            WHERE c.tenant_id=%s {own} ORDER BY COALESCE((SELECT max(e.occurred_at) FROM recovery.customer_support_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id),c.created_at) DESC,c.id DESC LIMIT %s""",params)
            rows=[dict(r) for r in cur.fetchall()]
        for r in rows:
            r["state"]="closed" if r["state"]=="closed" else "open"
        return rows

    def customer_support_case(self, *, tenant_id: UUID, user_id: UUID, case_id: UUID, include_all: bool) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            own="" if include_all else "AND c.created_by=%s"; params=(tenant_id,case_id) if include_all else (tenant_id,case_id,user_id)
            cur.execute(f"""SELECT c.id,c.account_id,c.created_by,u.email AS created_by_email,c.category,c.subject,c.initial_body,c.created_at
                            FROM recovery.customer_support_cases c LEFT JOIN recovery.app_users u ON u.id=c.created_by
                            WHERE c.tenant_id=%s AND c.id=%s {own}""",params)
            row=cur.fetchone()
            if row is None: raise ApiNotFound("support case not found")
            cur.execute("""SELECT e.id,e.event_type,e.actor_user_id,u.email AS actor_email,e.payload,e.occurred_at
                           FROM recovery.customer_support_events e LEFT JOIN recovery.app_users u ON u.id=e.actor_user_id
                           WHERE e.tenant_id=%s AND e.case_id=%s ORDER BY e.occurred_at,e.id""",(tenant_id,case_id))
            events=[dict(r) for r in cur.fetchall()]
        state="open"
        for e in events:
            if e["event_type"]=="closed": state="closed"
            elif e["event_type"]=="reopened": state="open"
        return {**dict(row),"state":state,"events":events}

    def create_customer_support_case(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, category: str, subject: str, body: str) -> dict[str, Any]:
        if category not in {"product","data","google_ads","billing","access","security","reporting","other"}: raise ValueError("invalid support category")
        if account_id is not None: self.ensure_account(tenant_id=tenant_id,account_id=account_id,user_id=user_id)
        subject=subject.strip();body=body.strip()
        if not subject or not body: raise ValueError("support subject and body are required")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("""INSERT INTO recovery.customer_support_cases(tenant_id,account_id,created_by,category,subject,initial_body)
                           VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",(tenant_id,account_id,user_id,category,subject,body))
            cid=cur.fetchone()["id"]
            cur.execute("INSERT INTO recovery.customer_support_events(tenant_id,case_id,event_type,actor_user_id,payload) VALUES (%s,%s,'opened',%s,'{}'::jsonb)",(tenant_id,cid,user_id))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=user_id,event_type="support_case_opened",target_type="support_case",target_id=str(cid),payload={"category":category,"account_id":str(account_id) if account_id else None})
        return self.customer_support_case(tenant_id=tenant_id,user_id=user_id,case_id=cid,include_all=True)

    def customer_support_case_event(self, *, tenant_id: UUID, user_id: UUID, case_id: UUID, include_all: bool, event_type: str, comment: str | None) -> dict[str, Any]:
        if event_type not in {"commented","closed","reopened"}: raise ValueError("invalid support event")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"customer-support:{tenant_id}:{case_id}")
            own="" if include_all else "AND created_by=%s"; params=(tenant_id,case_id) if include_all else (tenant_id,case_id,user_id)
            cur.execute(f"SELECT created_by FROM recovery.customer_support_cases WHERE tenant_id=%s AND id=%s {own}",params)
            if cur.fetchone() is None: raise ApiNotFound("support case not found")
            cur.execute("SELECT event_type FROM recovery.customer_support_events WHERE tenant_id=%s AND case_id=%s AND event_type IN ('closed','reopened') ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,case_id)); latest=cur.fetchone(); state="closed" if latest and latest["event_type"]=="closed" else "open"
            if event_type=="closed" and state=="closed": raise ApiConflict("support case is already closed")
            if event_type=="reopened" and state!="closed": raise ApiConflict("support case is not closed")
            text=(comment or "").strip()
            if event_type=="commented" and not text: raise ValueError("support comment is required")
            payload={"comment":text} if text else {}
            cur.execute("INSERT INTO recovery.customer_support_events(tenant_id,case_id,event_type,actor_user_id,payload) VALUES (%s,%s,%s,%s,%s)",(tenant_id,case_id,event_type,user_id,self._json(payload)))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=user_id,event_type=f"support_case_{event_type}",target_type="support_case",target_id=str(case_id),payload={})
        return self.customer_support_case(tenant_id=tenant_id,user_id=user_id,case_id=case_id,include_all=include_all)

    def _customer_data_requests(self, *, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT r.id,r.account_id,r.created_by,u.email AS created_by_email,r.request_type,r.reason,r.created_at,
                                  COALESCE((SELECT e.event_type FROM recovery.customer_data_request_events e WHERE e.tenant_id=r.tenant_id AND e.request_id=r.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'requested') AS state,
                                  (SELECT max(e.occurred_at) FROM recovery.customer_data_request_events e WHERE e.tenant_id=r.tenant_id AND e.request_id=r.id) AS last_event_at
                           FROM recovery.customer_data_requests r LEFT JOIN recovery.app_users u ON u.id=r.created_by
                           WHERE r.tenant_id=%s ORDER BY r.created_at DESC,r.id DESC""",(tenant_id,))
            return [dict(r) for r in cur.fetchall()]

    def security_data_overview(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT m.role,m.status,m.account_access_mode,m.client_portal,m.created_at,m.updated_at,u.email,u.last_seen_at FROM recovery.tenant_memberships m JOIN recovery.app_users u ON u.id=m.user_id WHERE m.tenant_id=%s AND m.user_id=%s",(tenant_id,user_id)); membership=cur.fetchone()
            if membership is None: raise ApiNotFound("membership not found")
            cur.execute("""SELECT c.id,c.status,c.connected_by,u.email AS connected_by_email,c.granted_scopes,c.connected_at,c.last_verified_at,c.revoked_at,c.error_code
                           FROM recovery.google_oauth_connections c LEFT JOIN recovery.app_users u ON u.id=c.connected_by
                           WHERE c.tenant_id=%s ORDER BY c.connected_at DESC,c.id DESC""",(tenant_id,)); connections=[dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT id,terms_url,terms_version,privacy_url,privacy_version,source,accepted_at,occurred_at
                           FROM recovery.user_legal_acceptance_events WHERE user_id=%s AND (tenant_id=%s OR tenant_id IS NULL) ORDER BY occurred_at DESC,id DESC LIMIT 5""",(user_id,tenant_id)); legal=[dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT id,actor_user_id,event_type,target_type,target_id,occurred_at,payload FROM recovery.organization_activity_events
                           WHERE tenant_id=%s AND (event_type ILIKE '%%member%%' OR event_type ILIKE '%%access%%' OR event_type ILIKE '%%invite%%' OR event_type ILIKE '%%oauth%%' OR event_type ILIKE '%%data%%')
                           ORDER BY occurred_at DESC,id DESC LIMIT 50""",(tenant_id,)); security_events=[dict(r) for r in cur.fetchall()]
        return {"membership":dict(membership),"google_connections":connections,"legal_acceptances":legal,"security_events":security_events,"data_requests":self._customer_data_requests(tenant_id=tenant_id),"retention":{"evidence":"Immutable evidence remains until a controlled deletion workflow is completed.","credentials":"Google refresh tokens are stored in the configured secret vault; database rows contain only secret references/hashes.","share_tokens":"External report capability tokens are stored only as SHA-256 hashes.","deletion":"Organization deletion is a controlled request and is never executed directly from the browser."}}

    def create_customer_data_request(self, *, tenant_id: UUID, user_id: UUID, account_id: UUID | None, request_type: str, reason: str) -> dict[str, Any]:
        if request_type not in {"full_data_export","organization_deletion","google_ads_disconnect"}: raise ValueError("invalid data request type")
        if request_type=="google_ads_disconnect":
            if account_id is None: raise ValueError("google_ads_disconnect requires account_id")
            self.ensure_account(tenant_id=tenant_id,account_id=account_id,user_id=user_id)
        else: account_id=None
        reason=reason.strip()
        if not reason: raise ValueError("request reason is required")
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"customer-data-request:{tenant_id}:{request_type}:{account_id or 'org'}")
            cur.execute("""SELECT r.id FROM recovery.customer_data_requests r WHERE r.tenant_id=%s AND r.request_type=%s AND r.account_id IS NOT DISTINCT FROM %s
                           AND NOT EXISTS (SELECT 1 FROM recovery.customer_data_request_events e WHERE e.tenant_id=r.tenant_id AND e.request_id=r.id AND e.event_type IN ('cancelled','completed','rejected')) LIMIT 1""",(tenant_id,request_type,account_id))
            if cur.fetchone(): raise ApiConflict("an active request of this type already exists for this scope")
            cur.execute("INSERT INTO recovery.customer_data_requests(tenant_id,account_id,created_by,request_type,reason) VALUES (%s,%s,%s,%s,%s) RETURNING id,created_at",(tenant_id,account_id,user_id,request_type,reason)); row=cur.fetchone(); rid=row["id"]
            cur.execute("INSERT INTO recovery.customer_data_request_events(tenant_id,request_id,event_type,actor_user_id,actor,payload) VALUES (%s,%s,'requested',%s,%s,'{}'::jsonb)",(tenant_id,rid,user_id,f"user:{user_id}"))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=user_id,event_type="data_request_created",target_type="data_request",target_id=str(rid),payload={"request_type":request_type,"account_id":str(account_id) if account_id else None})
        return next(r for r in self._customer_data_requests(tenant_id=tenant_id) if r["id"]==rid)

    def cancel_customer_data_request(self, *, tenant_id: UUID, user_id: UUID, request_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"customer-data-request-id:{tenant_id}:{request_id}")
            cur.execute("SELECT created_by FROM recovery.customer_data_requests WHERE tenant_id=%s AND id=%s",(tenant_id,request_id)); req=cur.fetchone()
            if req is None: raise ApiNotFound("data request not found")
            cur.execute("SELECT event_type FROM recovery.customer_data_request_events WHERE tenant_id=%s AND request_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,request_id)); latest=cur.fetchone(); state=latest["event_type"] if latest else "requested"
            if state in {"cancelled","completed","rejected"}: raise ApiConflict("data request is already terminal")
            cur.execute("INSERT INTO recovery.customer_data_request_events(tenant_id,request_id,event_type,actor_user_id,actor,payload) VALUES (%s,%s,'cancelled',%s,%s,'{}'::jsonb)",(tenant_id,request_id,user_id,f"user:{user_id}"))
            self._record_org_activity(cur,tenant_id=tenant_id,actor_user_id=user_id,event_type="data_request_cancelled",target_type="data_request",target_id=str(request_id),payload={})
        return next(r for r in self._customer_data_requests(tenant_id=tenant_id) if r["id"]==request_id)

    def security_configuration_export(self, *, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
        """Bounded customer-controlled configuration/audit export; never exports credentials/secrets."""
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT id,slug,display_name,created_at FROM recovery.tenants WHERE id=%s",(tenant_id,)); tenant=cur.fetchone()
            if tenant is None: raise ApiNotFound("tenant not found")
            cur.execute("SELECT id,customer_id,descriptive_name,currency_code,time_zone,account_status,test_account,created_at,updated_at FROM recovery.google_ads_accounts WHERE tenant_id=%s ORDER BY customer_id",(tenant_id,)); accounts=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT id,account_id,truth_fingerprint,schema_version,business_version,payload,created_by,created_at FROM recovery.business_truth_snapshots WHERE tenant_id=%s ORDER BY account_id,business_version",(tenant_id,)); truths=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT id,actor_user_id,event_type,target_type,target_id,occurred_at,payload FROM recovery.organization_activity_events WHERE tenant_id=%s ORDER BY occurred_at,id LIMIT 5000",(tenant_id,)); activity=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT id,status,connected_by,granted_scopes,connected_at,last_verified_at,revoked_at,error_code FROM recovery.google_oauth_connections WHERE tenant_id=%s ORDER BY connected_at",(tenant_id,)); connections=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT id,name,description,created_at,updated_at FROM recovery.portfolios WHERE tenant_id=%s ORDER BY created_at",(tenant_id,)); portfolios=[dict(r) for r in cur.fetchall()]
        return {"schema_version":"recovery-configuration-export.v1","generated_at":datetime.now(timezone.utc),"generated_by":user_id,"tenant":dict(tenant),"accounts":accounts,"business_truth_versions":truths,"portfolios":portfolios,"google_connection_metadata":connections,"organization_activity":activity,"support_cases":self.customer_support_cases(tenant_id=tenant_id,user_id=user_id,include_all=True,limit=300),"data_requests":self._customer_data_requests(tenant_id=tenant_id),"exclusions":["OAuth refresh tokens/secret references","report share raw tokens","billing provider secrets","raw provider credentials"]}

    # --- Epic 12 internal admin/support ---

    def platform_operator_role(self, *, user_id: UUID) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            self._set_user(cur,user_id)
            cur.execute("SELECT recovery_private.current_platform_operator_role() AS role")
            row=cur.fetchone(); return str(row["role"]) if row and row["role"] else None

    def _require_platform_operator(self, cur: Any, user_id: UUID) -> str:
        self._set_user(cur,user_id)
        cur.execute("SELECT recovery_private.current_platform_operator_role() AS role")
        row=cur.fetchone(); role=str(row["role"]) if row and row["role"] else None
        if role is None: raise PlatformAuthorizationError("platform operator access required")
        return role

    def list_internal_tenants(self, *, user_id: UUID, query: str | None, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id)
            if query:
                q=f"%{query.strip()}%"
                cur.execute("SELECT tenant_id,slug,display_name,first_seen_at FROM recovery.platform_tenant_directory WHERE slug ILIKE %s OR display_name ILIKE %s ORDER BY display_name LIMIT %s",(q,q,limit))
            else:
                cur.execute("SELECT tenant_id,slug,display_name,first_seen_at FROM recovery.platform_tenant_directory ORDER BY display_name LIMIT %s",(limit,))
            rows=[dict(r) for r in cur.fetchall()]
        # Deliberately collect tenant-local counts only after selecting each tenant context.
        out=[]
        for row in rows:
            tid=row["tenant_id"]
            with self._connect() as conn, conn.cursor() as cur:
                self._set_user(cur,user_id); self.core._set_tenant(cur,tid)
                cur.execute("SELECT count(*)::int AS n FROM recovery.google_ads_accounts WHERE tenant_id=%s",(tid,)); accounts=int(cur.fetchone()["n"])
                cur.execute("SELECT count(*)::int AS n FROM recovery.tenant_memberships WHERE tenant_id=%s AND status='active'",(tid,)); members=int(cur.fetchone()["n"])
                cur.execute("SELECT count(*)::int AS n FROM recovery.api_jobs WHERE tenant_id=%s AND status IN ('queued','running','needs_reconciliation')",(tid,)); active_jobs=int(cur.fetchone()["n"])
            out.append({**row,"account_count":accounts,"active_member_count":members,"active_job_count":active_jobs})
        return out

    def internal_tenant_diagnostics(self, *, user_id: UUID, tenant_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT id,slug,display_name,created_at FROM recovery.tenants WHERE id=%s",(tenant_id,)); tenant=cur.fetchone()
            if tenant is None: raise ApiNotFound("tenant not found")
            cur.execute("SELECT id,customer_id,descriptive_name,currency_code,time_zone,account_status,test_account,(credential_ref IS NOT NULL) AS google_connection_present,updated_at FROM recovery.google_ads_accounts WHERE tenant_id=%s ORDER BY descriptive_name,customer_id",(tenant_id,)); accounts=[dict(r) for r in cur.fetchall()]
            cur.execute("""SELECT m.user_id,m.role,m.status,m.account_access_mode,m.client_portal,u.email,u.last_seen_at
                           FROM recovery.tenant_memberships m LEFT JOIN recovery.app_users u ON u.id=m.user_id
                           WHERE m.tenant_id=%s ORDER BY m.role,u.email NULLS LAST""",(tenant_id,)); members=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT status,count(*)::int AS n FROM recovery.api_jobs WHERE tenant_id=%s GROUP BY status",(tenant_id,)); job_counts={r["status"]:int(r["n"]) for r in cur.fetchall()}
            cur.execute("SELECT id,job_type,status,failure_code,created_at,completed_at FROM recovery.api_jobs WHERE tenant_id=%s AND status='needs_reconciliation' ORDER BY created_at DESC LIMIT 20",(tenant_id,)); reconciliation=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT provider_status,entitlement_state,plan_key,current_end,updated_at FROM recovery.billing_tenant_current WHERE tenant_id=%s",(tenant_id,)); billing=cur.fetchone()
            cur.execute("SELECT id,status,completed_at,failure_code,account_id FROM recovery.sync_runs WHERE tenant_id=%s ORDER BY started_at DESC,id DESC LIMIT 1",(tenant_id,)); sync=cur.fetchone()
            cur.execute("SELECT id,status,completed_at,failure_code,account_id FROM recovery.analysis_runs WHERE tenant_id=%s ORDER BY started_at DESC,id DESC LIMIT 1",(tenant_id,)); analysis=cur.fetchone()
            cur.execute("""SELECT d.id,d.scope_kind,d.account_id,d.release_fingerprint,e.event_type,e.occurred_at
                           FROM recovery.semantic_release_definitions d LEFT JOIN LATERAL (
                             SELECT event_type,occurred_at FROM recovery.semantic_release_events e
                             WHERE e.tenant_id=d.tenant_id AND e.release_definition_id=d.id ORDER BY occurred_at DESC,id DESC LIMIT 1
                           ) e ON true WHERE d.tenant_id=%s ORDER BY d.created_at DESC LIMIT 20""",(tenant_id,)); releases=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT feature_key,enabled,reason,occurred_at FROM recovery.internal_feature_control_events WHERE tenant_id=%s ORDER BY occurred_at DESC,id DESC",(tenant_id,)); features=[dict(r) for r in cur.fetchall()]
            return {"tenant":dict(tenant),"accounts":accounts,"members":members,"job_counts":job_counts,"reconciliation":reconciliation,"billing":dict(billing) if billing else None,"latest_sync":dict(sync) if sync else None,"latest_analysis":dict(analysis) if analysis else None,"semantic_releases":releases,"feature_controls":features}

    def internal_jobs(self, *, user_id: UUID, tenant_id: UUID, status: str | None, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("limit must be between 1 and 500")
        allowed={"queued","running","succeeded","failed","cancelled","needs_reconciliation"}
        if status and status not in allowed: raise ValueError("invalid job status")
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id); self.core._set_tenant(cur,tenant_id)
            if status:
                cur.execute("SELECT id,job_type,status,attempts,max_attempts,requested_by,endpoint,operation_key,failure_code,created_at,started_at,completed_at FROM recovery.api_jobs WHERE tenant_id=%s AND status=%s ORDER BY created_at DESC LIMIT %s",(tenant_id,status,limit))
            else:
                cur.execute("SELECT id,job_type,status,attempts,max_attempts,requested_by,endpoint,operation_key,failure_code,created_at,started_at,completed_at FROM recovery.api_jobs WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s",(tenant_id,limit))
            return [dict(r) for r in cur.fetchall()]

    def internal_retry_job(self, *, user_id: UUID, tenant_id: UUID, job_id: UUID, reason: str) -> dict[str, Any]:
        if not reason.strip(): raise ValueError("remediation reason is required")
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role not in {"support_engineer","platform_admin"}: raise ApiConflict("operator role cannot perform remediation")
            self.core._set_tenant(cur,tenant_id); self.core._advisory_xact_lock(cur,f"internal-retry:{tenant_id}:{job_id}")
            cur.execute("SELECT id,job_type,status,payload,max_attempts FROM recovery.api_jobs WHERE tenant_id=%s AND id=%s FOR UPDATE",(tenant_id,job_id)); old=cur.fetchone()
            if old is None: raise ApiNotFound("job not found")
            if old["status"]!="failed": raise ApiConflict("only terminal failed jobs can be safely retried")
            if old["job_type"] not in SAFE_INTERNAL_RETRY_JOB_TYPES: raise ApiConflict("job type is not in the internal safe-retry allowlist")
            new_id=uuid4(); endpoint=f"internal:retry:{job_id}"
            cur.execute("""INSERT INTO recovery.api_jobs(id,tenant_id,job_type,status,payload,requested_by,endpoint,operation_key,idempotency_key,request_sha256,available_at,max_attempts)
                           VALUES (%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,now(),%s)""",
                        (new_id,tenant_id,old["job_type"],self._json(dict(old["payload"])),user_id,endpoint,f"internal-retry:{job_id}:{new_id}",str(new_id),payload_sha256({"source_job_id":str(job_id),"payload":dict(old["payload"])}),old["max_attempts"]))
            cur.execute("""INSERT INTO recovery.internal_remediation_events(tenant_id,target_type,target_id,action,actor_user_id,reason,payload)
                           VALUES (%s,'job',%s,'safe_retry',%s,%s,%s)""",(tenant_id,str(job_id),user_id,reason.strip(),self._json({"new_job_id":str(new_id),"job_type":old["job_type"]})))
            return {"source_job_id":job_id,"new_job_id":new_id,"job_type":old["job_type"],"status":"queued"}

    def internal_support_cases(self, *, user_id: UUID, tenant_id: UUID, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id); self.core._set_tenant(cur,tenant_id)
            cur.execute("""SELECT c.id,c.title,c.category,c.severity,c.opened_by,c.created_at,
                     COALESCE((SELECT e.event_type FROM recovery.internal_support_case_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'opened') AS latest_event,
                     (SELECT e.occurred_at FROM recovery.internal_support_case_events e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1) AS updated_at
                     FROM recovery.internal_support_cases c WHERE c.tenant_id=%s ORDER BY c.created_at DESC LIMIT %s""",(tenant_id,limit))
            return [dict(r) for r in cur.fetchall()]

    def create_internal_support_case(self, *, user_id: UUID, tenant_id: UUID, title: str, category: str, severity: str, note: str | None) -> dict[str, Any]:
        if category not in {"product","data","google_ads","billing","integration","security","access","other"}: raise ValueError("invalid support category")
        if severity not in {"low","medium","high","critical"}: raise ValueError("invalid support severity")
        if not title.strip(): raise ValueError("title is required")
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role not in {"support_engineer","platform_admin"}: raise ApiConflict("operator role cannot create support cases")
            self.core._set_tenant(cur,tenant_id); case_id=uuid4()
            cur.execute("INSERT INTO recovery.internal_support_cases(id,tenant_id,title,category,severity,opened_by) VALUES (%s,%s,%s,%s,%s,%s)",(case_id,tenant_id,title.strip(),category,severity,user_id))
            cur.execute("INSERT INTO recovery.internal_support_case_events(tenant_id,case_id,event_type,actor_user_id,payload) VALUES (%s,%s,'opened',%s,%s)",(tenant_id,case_id,user_id,self._json({"note":note.strip() if note else None})))
            return {"id":case_id,"title":title.strip(),"category":category,"severity":severity,"latest_event":"opened"}

    def internal_support_case_event(self, *, user_id: UUID, tenant_id: UUID, case_id: UUID, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        allowed={"note","assigned","unassigned","status_changed","closed","reopened"}
        if event_type not in allowed: raise ValueError("invalid support case event")
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role not in {"support_engineer","platform_admin"}: raise ApiConflict("operator role cannot modify support cases")
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT 1 FROM recovery.internal_support_cases WHERE tenant_id=%s AND id=%s",(tenant_id,case_id))
            if cur.fetchone() is None: raise ApiNotFound("support case not found")
            cur.execute("INSERT INTO recovery.internal_support_case_events(tenant_id,case_id,event_type,actor_user_id,payload) VALUES (%s,%s,%s,%s,%s) RETURNING id,occurred_at",(tenant_id,case_id,event_type,user_id,self._json(payload or {}))); r=cur.fetchone()
            return {"id":r["id"],"case_id":case_id,"event_type":event_type,"payload":payload or {},"occurred_at":r["occurred_at"]}

    def internal_feature_controls(self, *, user_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id); self.core._set_tenant(cur,tenant_id)
            out=[]
            for key in sorted(FEATURE_KEYS):
                cur.execute("SELECT enabled,reason,occurred_at,actor_user_id FROM recovery.internal_feature_control_events WHERE tenant_id=%s AND feature_key=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,key)); row=cur.fetchone()
                out.append({"feature_key":key,"enabled":bool(row["enabled"]) if row else True,"reason":row["reason"] if row else "default enabled","occurred_at":row["occurred_at"] if row else None,"actor_user_id":row["actor_user_id"] if row else None})
            return out

    def set_internal_feature_control(self, *, user_id: UUID, tenant_id: UUID, feature_key: str, enabled: bool, reason: str) -> dict[str, Any]:
        if feature_key not in FEATURE_KEYS: raise ValueError("unsupported internal feature key")
        if not reason.strip(): raise ValueError("feature control reason is required")
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role!="platform_admin": raise ApiConflict("only platform_admin can change operational controls")
            self.core._set_tenant(cur,tenant_id)
            cur.execute("INSERT INTO recovery.internal_feature_control_events(tenant_id,feature_key,enabled,actor_user_id,reason) VALUES (%s,%s,%s,%s,%s) RETURNING occurred_at",(tenant_id,feature_key,enabled,user_id,reason.strip())); row=cur.fetchone()
            return {"feature_key":feature_key,"enabled":enabled,"reason":reason.strip(),"occurred_at":row["occurred_at"],"actor_user_id":user_id}

    def internal_feature_enabled(self, *, tenant_id: UUID, feature_key: str) -> bool:
        if feature_key not in FEATURE_KEYS: raise ValueError("unsupported internal feature key")
        with self._connect() as conn, conn.cursor() as cur:
            self.core._set_tenant(cur,tenant_id)
            cur.execute("SELECT enabled FROM recovery.internal_feature_control_events WHERE tenant_id=%s AND feature_key=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(tenant_id,feature_key)); row=cur.fetchone()
            return bool(row["enabled"]) if row else True

    def internal_platform_incidents(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=500: raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id)
            cur.execute("""SELECT DISTINCT ON (incident_id) incident_id,event_type,severity,title,payload,occurred_at,actor_user_id
                           FROM recovery.platform_incident_events ORDER BY incident_id,occurred_at DESC,id DESC""")
            rows=[dict(r) for r in cur.fetchall()]
            rows.sort(key=lambda r:r["occurred_at"],reverse=True)
            return rows[:limit]

    def internal_release_history(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=200: raise ValueError("limit must be between 1 and 200")
        tenants=self.list_internal_tenants(user_id=user_id,query=None,limit=500)
        rows=[]
        for t in tenants:
            tid=t["tenant_id"]
            with self._connect() as conn, conn.cursor() as cur:
                self._set_user(cur,user_id); self.core._set_tenant(cur,tid)
                cur.execute("""SELECT id,status,result,completed_at FROM recovery.api_jobs
                               WHERE tenant_id=%s AND job_type='deployment_probe' AND status='succeeded' AND result IS NOT NULL
                               ORDER BY completed_at DESC,id DESC LIMIT 20""",(tid,))
                for r in cur.fetchall():
                    result=dict(r["result"] or {})
                    if result.get("probe")!="ok": continue
                    rows.append({"tenant_id":tid,"tenant_name":t["display_name"],"job_id":r["id"],"release_id":str(result.get("release_id") or "unversioned"),"worker_version":str(result.get("worker_version") or "unknown"),"completed_at":r["completed_at"]})
        rows.sort(key=lambda x:x["completed_at"],reverse=True)
        return rows[:limit]

    def create_internal_platform_incident_event(self, *, user_id: UUID, incident_id: UUID | None, event_type: str, severity: str, title: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type not in {"opened","update","mitigated","resolved","reopened"}: raise ValueError("invalid incident event")
        if severity not in {"low","medium","high","critical"}: raise ValueError("invalid incident severity")
        if not title.strip(): raise ValueError("incident title required")
        iid=incident_id or uuid4()
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role not in {"support_engineer","platform_admin"}: raise ApiConflict("operator role cannot modify platform incidents")
            cur.execute("INSERT INTO recovery.platform_incident_events(incident_id,event_type,severity,title,actor_user_id,payload) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,occurred_at",(iid,event_type,severity,title.strip(),user_id,self._json(payload or {}))); row=cur.fetchone()
            return {"id":row["id"],"incident_id":iid,"event_type":event_type,"severity":severity,"title":title.strip(),"payload":payload or {},"occurred_at":row["occurred_at"],"actor_user_id":user_id}
    # --- Epic 14 launch control ---

    def _launch_state_with_cursor(self, cur: Any) -> dict[str, Any]:
        cur.execute("SELECT id,launch_mode,release_id,qualification_id,reason,occurred_at,actor_user_id FROM recovery.platform_launch_events ORDER BY occurred_at DESC,id DESC LIMIT 1")
        row=cur.fetchone()
        if row is None:
            return {"launch_mode":"closed","release_id":None,"qualification_id":None,"reason":"default closed","occurred_at":None,"actor_user_id":None}
        return dict(row)

    def public_launch_status(self, *, user_id: UUID | None = None, email: str | None = None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            if user_id is not None:self._set_user(cur,user_id)
            state=self._launch_state_with_cursor(cur)
            access=False;hint=None;expires=None
            if user_id is not None and email:
                digest=launch_email_sha256(email)
                cur.execute("SELECT id,event_type,expires_at,subject_hint,occurred_at FROM recovery.platform_launch_access_events WHERE subject_email_sha256=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",(digest,))
                r=cur.fetchone()
                if r:
                    x=derive_launch_access([dict(r)]);access=x.allowed;hint=x.subject_hint;expires=x.expires_at
            mode=LaunchMode(state["launch_mode"])
            return {"launch_mode":mode.value,"workspace_creation_open":mode is LaunchMode.PUBLIC or (mode in {LaunchMode.PILOT_ONLY,LaunchMode.INVITE_ONLY} and access),"access_granted":access,"access_hint":hint,"access_expires_at":expires,"release_id":state["release_id"] if mode is LaunchMode.PUBLIC else None}

    def launch_workspace_creation_allowed(self, *, user_id: UUID, email: str | None) -> bool:
        status=self.public_launch_status(user_id=user_id,email=email)
        return bool(status["workspace_creation_open"])

    def internal_launch_status(self, *, user_id: UUID) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id)
            state=self._launch_state_with_cursor(cur)
            cur.execute("SELECT id,release_id,report_sha256,report_generated_at,occurred_at,imported_by FROM recovery.platform_launch_qualifications ORDER BY occurred_at DESC,id DESC LIMIT 10")
            qualifications=[dict(r) for r in cur.fetchall()]
            cur.execute("SELECT count(*)::int AS n FROM (SELECT DISTINCT ON (subject_email_sha256) subject_email_sha256,event_type,expires_at FROM recovery.platform_launch_access_events ORDER BY subject_email_sha256,occurred_at DESC,id DESC) x WHERE event_type='granted' AND (expires_at IS NULL OR expires_at>now())")
            active=int(cur.fetchone()["n"])
            return {**state,"active_access_grants":active,"qualifications":qualifications}

    def import_launch_qualification(self, *, user_id: UUID, report: dict[str, Any]) -> dict[str, Any]:
        role=self.platform_operator_role(user_id=user_id)
        if role!="platform_admin":raise ApiConflict("only platform_admin can import launch qualification")
        validate_launch_gate_report(report)
        release_id=str(report["expected_release_id"]); generated=datetime.fromisoformat(str(report["generated_at"]).replace("Z","+00:00")).astimezone(timezone.utc)
        digest=payload_sha256(report)
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id)
            cur.execute("SELECT id,release_id,report_sha256,report_generated_at,occurred_at,imported_by FROM recovery.platform_launch_qualifications WHERE report_sha256=%s",(digest,)); prior=cur.fetchone()
            if prior:return dict(prior)
            cur.execute("INSERT INTO recovery.platform_launch_qualifications(release_id,report_sha256,report,report_generated_at,imported_by) VALUES (%s,%s,%s,%s,%s) RETURNING id,release_id,report_sha256,report_generated_at,occurred_at,imported_by",(release_id,digest,self._json(report),generated,user_id));return dict(cur.fetchone())

    def set_internal_launch_mode(self, *, user_id: UUID, launch_mode: str, release_id: str | None, reason: str) -> dict[str, Any]:
        try:mode=LaunchMode(launch_mode)
        except Exception as exc:raise ValueError("invalid launch mode") from exc
        if not reason.strip():raise ValueError("launch mode reason is required")
        release=(release_id or "").strip() or None
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role!="platform_admin":raise ApiConflict("only platform_admin can change launch mode")
            self.core._advisory_xact_lock(cur,"platform-launch-mode")
            qualification_id=None
            if mode is LaunchMode.PUBLIC:
                if not release:raise ValueError("public launch requires release_id")
                cur.execute("SELECT id FROM recovery.platform_launch_qualifications WHERE release_id=%s AND report_generated_at>=now()-interval '24 hours' ORDER BY report_generated_at DESC,id DESC LIMIT 1",(release,))
                q=cur.fetchone()
                if q is None:raise ApiConflict("public launch requires a fresh imported qualified launch-gate report for this release")
                qualification_id=q["id"]
            cur.execute("INSERT INTO recovery.platform_launch_events(launch_mode,release_id,qualification_id,actor_user_id,reason) VALUES (%s,%s,%s,%s,%s) RETURNING id,launch_mode,release_id,qualification_id,reason,occurred_at,actor_user_id",(mode.value,release,qualification_id,user_id,reason.strip()));return dict(cur.fetchone())

    def list_internal_launch_access(self, *, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        if not 1<=limit<=500:raise ValueError("limit must be between 1 and 500")
        with self._connect() as conn, conn.cursor() as cur:
            self._require_platform_operator(cur,user_id)
            cur.execute("SELECT DISTINCT ON (subject_email_sha256) id,subject_email_sha256,subject_hint,event_type,expires_at,reason,actor_user_id,occurred_at FROM recovery.platform_launch_access_events ORDER BY subject_email_sha256,occurred_at DESC,id DESC")
            rows=[dict(r) for r in cur.fetchall()]
            rows.sort(key=lambda r:r["occurred_at"],reverse=True)
            return rows[:limit]

    def record_internal_launch_access(self, *, user_id: UUID, email: str, event_type: str, expires_at: datetime | None, reason: str) -> dict[str, Any]:
        if event_type not in {"granted","revoked"}:raise ValueError("launch access event_type must be granted or revoked")
        if not reason.strip():raise ValueError("launch access reason is required")
        normalized=normalize_launch_email(email);digest=launch_email_sha256(normalized);hint=launch_email_hint(normalized)
        if expires_at is not None:
            if expires_at.tzinfo is None or expires_at.utcoffset() is None:raise ValueError("expires_at must be timezone-aware")
            expires_at=expires_at.astimezone(timezone.utc)
            if expires_at<=datetime.now(timezone.utc):raise ValueError("launch access expiry must be in the future")
        with self._connect() as conn, conn.cursor() as cur:
            role=self._require_platform_operator(cur,user_id)
            if role!="platform_admin":raise ApiConflict("only platform_admin can change launch access")
            self.core._advisory_xact_lock(cur,f"launch-access:{digest}")
            cur.execute("INSERT INTO recovery.platform_launch_access_events(subject_email_sha256,subject_hint,event_type,expires_at,actor_user_id,reason) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,subject_email_sha256,subject_hint,event_type,expires_at,reason,actor_user_id,occurred_at",(digest,hint,event_type,expires_at if event_type=="granted" else None,user_id,reason.strip()));return dict(cur.fetchone())

