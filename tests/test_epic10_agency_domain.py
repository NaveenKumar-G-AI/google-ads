from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest

from recovery.agency_operations import normalize_email,new_invite_token,invite_token_sha256,validate_access_shape,invitation_state
from recovery.api.auth import Principal
from recovery.api.policy import TenantAccess,TenantRole,AuthorizationError


def test_email_normalization_and_invite_token_are_capability_safe():
    tenant=uuid4(); token=new_invite_token(str(tenant))
    assert token.startswith(f"{tenant}.")
    assert len(invite_token_sha256(token))==64
    assert normalize_email("  Person@Example.COM ")=="person@example.com"
    with pytest.raises(ValueError): normalize_email("not-an-email")


def test_client_portal_is_only_selected_account_viewer():
    validate_access_shape(role="viewer",account_access_mode="selected_accounts",client_portal=True)
    for role,mode in [("analyst","selected_accounts"),("viewer","all_accounts"),("admin","all_accounts")]:
        with pytest.raises(ValueError): validate_access_shape(role=role,account_access_mode=mode,client_portal=True)
    with pytest.raises(ValueError): validate_access_shape(role="admin",account_access_mode="selected_accounts",client_portal=False)


def test_invitation_state_never_reopens_after_terminal_event():
    now=datetime.now(timezone.utc); invite={"expires_at":now+timedelta(days=1)}
    assert invitation_state(invite,[],now=now)=="pending"
    assert invitation_state({"expires_at":now-timedelta(seconds=1)},[],now=now)=="expired"
    assert invitation_state(invite,[{"event_type":"revoked","occurred_at":now,"id":"1"}],now=now)=="revoked"


def test_tenant_access_enforces_selected_account_scope():
    p=Principal(user_id=uuid4(),subject="u",email="u@example.com",issuer="i",audience="a",role_claim=None,issued_at=None,expires_at=None)
    allowed=uuid4(); denied=uuid4()
    a=TenantAccess(tenant_id=uuid4(),principal=p,role=TenantRole.VIEWER,account_access_mode="selected_accounts",client_portal=True,allowed_account_ids=frozenset({allowed}))
    a.require_account(allowed)
    with pytest.raises(AuthorizationError): a.require_account(denied)
    with pytest.raises(AuthorizationError): a.require_unrestricted_scope()

from recovery.agency_operations import validate_owner_management,validate_member_transition


def test_admin_cannot_manage_owner_level_access():
    with pytest.raises(PermissionError,match="only an owner"):
        validate_owner_management(actor_role="admin",target_role="owner")
    validate_owner_management(actor_role="owner",target_role="owner")
    validate_owner_management(actor_role="admin",target_role="viewer")


def test_last_active_owner_transition_is_rejected_but_handover_is_allowed():
    with pytest.raises(ValueError,match="at least one active owner"):
        validate_member_transition(actor_role="owner",current_role="owner",current_status="active",new_role="admin",new_status="active",other_active_owner_count=0)
    validate_member_transition(actor_role="owner",current_role="owner",current_status="active",new_role="admin",new_status="active",other_active_owner_count=1)
    with pytest.raises(PermissionError,match="only an owner"):
        validate_member_transition(actor_role="admin",current_role="owner",current_status="active",new_role="owner",new_status="active",other_active_owner_count=1)
