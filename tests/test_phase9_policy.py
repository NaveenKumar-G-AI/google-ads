from datetime import datetime, timezone
from uuid import uuid4

import pytest

from recovery.api.auth import Principal
from recovery.api.policy import AuthorizationError, Permission, TenantAccess, TenantRole


def principal():
    return Principal(
        user_id=uuid4(), subject=str(uuid4()), email="a@example.test",
        issuer="https://x.supabase.co/auth/v1", audience="authenticated",
        role_claim="authenticated", issued_at=None,
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def test_viewer_is_read_only():
    access = TenantAccess(uuid4(), principal(), TenantRole.VIEWER)
    access.require(Permission.FINDINGS_READ)
    with pytest.raises(AuthorizationError):
        access.require(Permission.SYNC_START)


def test_analyst_can_sync_and_analyze_but_not_approve():
    access = TenantAccess(uuid4(), principal(), TenantRole.ANALYST)
    access.require(Permission.SYNC_START)
    access.require(Permission.ANALYSIS_START)
    with pytest.raises(AuthorizationError):
        access.require(Permission.PROPOSAL_DECIDE)


def test_admin_and_owner_can_approve_and_mutate():
    for role in (TenantRole.ADMIN, TenantRole.OWNER):
        access = TenantAccess(uuid4(), principal(), role)
        access.require(Permission.PROPOSAL_DECIDE)
        access.require(Permission.MUTATION_EXECUTE)
        access.require(Permission.MUTATION_ROLLBACK)
