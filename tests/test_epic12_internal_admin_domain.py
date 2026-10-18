from datetime import datetime,timezone
from uuid import uuid4
import pytest
from recovery.internal_admin import (
    FEATURE_KEYS,SAFE_INTERNAL_RETRY_JOB_TYPES,PLATFORM_ROLE_PERMISSIONS,PlatformAccess,
    PlatformAuthorizationError,PlatformOperatorRole,PlatformPermission,feature_state,
)


def test_platform_roles_are_separate_and_least_privilege():
    assert PlatformPermission.FEATURE_CONTROL not in PLATFORM_ROLE_PERMISSIONS[PlatformOperatorRole.SUPPORT_ENGINEER]
    assert PlatformPermission.SAFE_REMEDIATION in PLATFORM_ROLE_PERMISSIONS[PlatformOperatorRole.SUPPORT_ENGINEER]
    assert PlatformPermission.SUPPORT_CASE_WRITE not in PLATFORM_ROLE_PERMISSIONS[PlatformOperatorRole.SECURITY_AUDITOR]
    assert PlatformPermission.FEATURE_CONTROL in PLATFORM_ROLE_PERMISSIONS[PlatformOperatorRole.PLATFORM_ADMIN]


def test_platform_access_rejects_missing_permission():
    a=PlatformAccess(uuid4(),PlatformOperatorRole.SUPPORT_VIEWER)
    with pytest.raises(PlatformAuthorizationError): a.require(PlatformPermission.SAFE_REMEDIATION)


def test_safe_retry_allowlist_excludes_consequential_side_effect_jobs():
    assert 'apply_negative' not in SAFE_INTERNAL_RETRY_JOB_TYPES
    assert 'rollback_negative' not in SAFE_INTERNAL_RETRY_JOB_TYPES
    assert 'report_generation' not in SAFE_INTERNAL_RETRY_JOB_TYPES
    assert 'google_ads_sync' in SAFE_INTERNAL_RETRY_JOB_TYPES


def test_feature_controls_are_real_operational_keys_and_latest_event_wins():
    assert FEATURE_KEYS==frozenset({'google_ads_mutations','billing_mutations','scheduled_report_email'})
    now=datetime.now(timezone.utc)
    rows=[{'id':'a','feature_key':'google_ads_mutations','enabled':False,'occurred_at':now},{'id':'b','feature_key':'google_ads_mutations','enabled':True,'occurred_at':now}]
    assert feature_state(rows,'google_ads_mutations') is True
    assert feature_state([],'billing_mutations') is True
