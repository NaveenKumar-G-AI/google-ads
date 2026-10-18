from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from .auth import Principal


class AuthorizationError(RuntimeError):
    pass


class TenantRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(str, Enum):
    TENANT_READ = "tenant_read"
    ACCOUNT_READ = "account_read"
    FINDINGS_READ = "findings_read"
    LEDGER_READ = "ledger_read"
    SYNC_START = "sync_start"
    ANALYSIS_START = "analysis_start"
    SEMANTIC_SHADOW_START = "semantic_shadow_start"
    BUSINESS_TRUTH_READ = "business_truth_read"
    BUSINESS_TRUTH_WRITE = "business_truth_write"
    PROPOSAL_DECIDE = "proposal_decide"
    MUTATION_EXECUTE = "mutation_execute"
    MUTATION_ROLLBACK = "mutation_rollback"
    BILLING_READ = "billing_read"
    BILLING_MANAGE = "billing_manage"
    DEPLOYMENT_PROBE = "deployment_probe"
    PILOT_PROBE = "pilot_probe"
    PORTFOLIO_READ = "portfolio_read"
    PORTFOLIO_MANAGE = "portfolio_manage"
    TASK_READ = "task_read"
    TASK_MANAGE = "task_manage"
    NOTIFICATION_READ = "notification_read"
    GLOBAL_SEARCH = "global_search"
    ONBOARDING_MANAGE = "onboarding_manage"
    SEARCH_INTELLIGENCE_READ = "search_intelligence_read"
    WASTE_INTELLIGENCE_READ = "waste_intelligence_read"
    MEASUREMENT_INTEGRITY_READ = "measurement_integrity_read"
    MEASUREMENT_MAPPING_MANAGE = "measurement_mapping_manage"
    SEARCH_SAVED_VIEW_MANAGE = "search_saved_view_manage"
    RECOVERY_CASE_READ = "recovery_case_read"
    RECOVERY_CASE_MANAGE = "recovery_case_manage"
    RECOVERY_CENTER_READ = "recovery_center_read"
    MONITORING_READ = "monitoring_read"
    ALERT_MANAGE = "alert_manage"
    MONITOR_POLICY_MANAGE = "monitor_policy_manage"
    MONITORING_EVALUATE = "monitoring_evaluate"
    REPORTING_READ = "reporting_read"
    REPORT_GENERATE = "report_generate"
    REPORT_SHARE_MANAGE = "report_share_manage"
    REPORT_SCHEDULE_MANAGE = "report_schedule_manage"
    ORGANIZATION_TEAM_READ = "organization_team_read"
    ORGANIZATION_TEAM_MANAGE = "organization_team_manage"
    ACCOUNT_ACCESS_MANAGE = "account_access_manage"
    CLIENT_WORKSPACE_MANAGE = "client_workspace_manage"
    ORGANIZATION_ACTIVITY_READ = "organization_activity_read"
    SECURITY_DATA_READ = "security_data_read"
    DATA_REQUEST_MANAGE = "data_request_manage"
    SUPPORT_READ = "support_read"
    SUPPORT_CREATE = "support_create"
    SUPPORT_MANAGE = "support_manage"


ROLE_PERMISSIONS: dict[TenantRole, frozenset[Permission]] = {
    TenantRole.VIEWER: frozenset({
        Permission.TENANT_READ,
        Permission.ACCOUNT_READ,
        Permission.BUSINESS_TRUTH_READ,
        Permission.FINDINGS_READ,
        Permission.LEDGER_READ,
        Permission.PORTFOLIO_READ,
        Permission.TASK_READ,
        Permission.NOTIFICATION_READ,
        Permission.GLOBAL_SEARCH,
        Permission.SEARCH_INTELLIGENCE_READ,
        Permission.WASTE_INTELLIGENCE_READ,
        Permission.MEASUREMENT_INTEGRITY_READ,
        Permission.RECOVERY_CASE_READ,
        Permission.RECOVERY_CENTER_READ,
        Permission.MONITORING_READ,
        Permission.REPORTING_READ,
        Permission.SECURITY_DATA_READ,
        Permission.SUPPORT_READ,
        Permission.SUPPORT_CREATE,
    }),
    TenantRole.ANALYST: frozenset({
        Permission.TENANT_READ,
        Permission.ACCOUNT_READ,
        Permission.BUSINESS_TRUTH_READ,
        Permission.FINDINGS_READ,
        Permission.LEDGER_READ,
        Permission.SYNC_START,
        Permission.ANALYSIS_START,
        Permission.SEMANTIC_SHADOW_START,
        Permission.PORTFOLIO_READ,
        Permission.TASK_READ,
        Permission.TASK_MANAGE,
        Permission.NOTIFICATION_READ,
        Permission.GLOBAL_SEARCH,
        Permission.SEARCH_INTELLIGENCE_READ,
        Permission.SEARCH_SAVED_VIEW_MANAGE,
        Permission.WASTE_INTELLIGENCE_READ,
        Permission.MEASUREMENT_INTEGRITY_READ,
        Permission.RECOVERY_CASE_READ,
        Permission.RECOVERY_CASE_MANAGE,
        Permission.RECOVERY_CENTER_READ,
        Permission.MONITORING_READ,
        Permission.ALERT_MANAGE,
        Permission.MONITORING_EVALUATE,
        Permission.REPORTING_READ,
        Permission.REPORT_GENERATE,
        Permission.REPORT_SHARE_MANAGE,
        Permission.REPORT_SCHEDULE_MANAGE,
        Permission.SECURITY_DATA_READ,
        Permission.SUPPORT_READ,
        Permission.SUPPORT_CREATE,
        Permission.SUPPORT_MANAGE,
    }),
    TenantRole.ADMIN: frozenset(Permission),
    TenantRole.OWNER: frozenset(Permission),
}


@dataclass(frozen=True, slots=True)
class TenantAccess:
    tenant_id: UUID
    principal: Principal
    role: TenantRole
    account_access_mode: str = "all_accounts"
    client_portal: bool = False
    allowed_account_ids: frozenset[UUID] = frozenset()

    @property
    def actor_id(self) -> str:
        return self.principal.actor_id

    def require(self, permission: Permission) -> None:
        if permission not in ROLE_PERMISSIONS[self.role]:
            raise AuthorizationError(
                f"role {self.role.value} lacks permission {permission.value}"
            )

    def require_account(self, account_id: UUID) -> None:
        if self.account_access_mode == "all_accounts":
            return
        if account_id not in self.allowed_account_ids:
            raise AuthorizationError("account access denied")

    def require_unrestricted_scope(self) -> None:
        if self.account_access_mode != "all_accounts":
            raise AuthorizationError("organization/portfolio scope is unavailable for restricted memberships")
