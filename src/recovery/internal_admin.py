from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID


class PlatformOperatorRole(str, Enum):
    SUPPORT_VIEWER = "support_viewer"
    SUPPORT_ENGINEER = "support_engineer"
    PLATFORM_ADMIN = "platform_admin"
    SECURITY_AUDITOR = "security_auditor"


class PlatformPermission(str, Enum):
    PLATFORM_READ = "platform_read"
    TENANT_DIAGNOSTICS = "tenant_diagnostics"
    SUPPORT_CASE_READ = "support_case_read"
    SUPPORT_CASE_WRITE = "support_case_write"
    SAFE_REMEDIATION = "safe_remediation"
    FEATURE_CONTROL = "feature_control"
    INCIDENT_READ = "incident_read"
    INCIDENT_WRITE = "incident_write"
    SECURITY_AUDIT_READ = "security_audit_read"
    LAUNCH_CONTROL = "launch_control"


PLATFORM_ROLE_PERMISSIONS: dict[PlatformOperatorRole, frozenset[PlatformPermission]] = {
    PlatformOperatorRole.SUPPORT_VIEWER: frozenset({
        PlatformPermission.PLATFORM_READ, PlatformPermission.TENANT_DIAGNOSTICS,
        PlatformPermission.SUPPORT_CASE_READ, PlatformPermission.INCIDENT_READ,
    }),
    PlatformOperatorRole.SUPPORT_ENGINEER: frozenset({
        PlatformPermission.PLATFORM_READ, PlatformPermission.TENANT_DIAGNOSTICS,
        PlatformPermission.SUPPORT_CASE_READ, PlatformPermission.SUPPORT_CASE_WRITE,
        PlatformPermission.SAFE_REMEDIATION, PlatformPermission.INCIDENT_READ,
        PlatformPermission.INCIDENT_WRITE,
    }),
    PlatformOperatorRole.PLATFORM_ADMIN: frozenset(PlatformPermission),
    PlatformOperatorRole.SECURITY_AUDITOR: frozenset({
        PlatformPermission.PLATFORM_READ, PlatformPermission.TENANT_DIAGNOSTICS,
        PlatformPermission.SUPPORT_CASE_READ, PlatformPermission.INCIDENT_READ,
        PlatformPermission.SECURITY_AUDIT_READ,
    }),
}


class PlatformAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformAccess:
    user_id: UUID
    role: PlatformOperatorRole

    def require(self, permission: PlatformPermission) -> None:
        if permission not in PLATFORM_ROLE_PERMISSIONS[self.role]:
            raise PlatformAuthorizationError(f"operator role {self.role.value} lacks permission {permission.value}")


SAFE_INTERNAL_RETRY_JOB_TYPES=frozenset({
    "google_ads_sync","analysis_run","semantic_shadow","monitoring_evaluation","google_ads_account_discovery","deployment_probe",
})

FEATURE_KEYS=frozenset({"google_ads_mutations","billing_mutations","scheduled_report_email"})


def feature_state(events: list[dict[str, Any]], feature_key: str) -> bool:
    """Default operational state is enabled; latest exact-key event wins."""
    if feature_key not in FEATURE_KEYS:
        raise ValueError("unsupported internal feature key")
    matching=[e for e in events if str(e.get("feature_key"))==feature_key]
    if not matching:
        return True
    latest=max(matching,key=lambda e:(e.get("occurred_at"),str(e.get("id",""))))
    return bool(latest.get("enabled"))
