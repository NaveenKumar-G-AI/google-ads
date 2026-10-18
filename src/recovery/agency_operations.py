from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import secrets
from typing import Iterable

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> str:
    email=value.strip().lower()
    if len(email)>320 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("valid email address required")
    return email


def new_invite_token(tenant_id: str) -> str:
    return f"{tenant_id}.{secrets.token_urlsafe(32)}"


def invite_token_sha256(token: str) -> str:
    raw=token.strip()
    if len(raw)<32:
        raise ValueError("invalid invitation token")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_access_shape(*, role: str, account_access_mode: str, client_portal: bool) -> None:
    if role not in {"owner","admin","analyst","viewer"}:
        raise ValueError("invalid role")
    if account_access_mode not in {"all_accounts","selected_accounts"}:
        raise ValueError("invalid account access mode")
    if role in {"owner","admin"} and account_access_mode != "all_accounts":
        raise ValueError("owner/admin require all_accounts access")
    if client_portal and not (role=="viewer" and account_access_mode=="selected_accounts"):
        raise ValueError("client portal requires viewer + selected_accounts")


def latest_event_state(events: Iterable[dict], *, event_key: str="event_type") -> str | None:
    ordered=sorted(events,key=lambda e:(str(e.get("occurred_at") or ""),str(e.get("id") or "")))
    return str(ordered[-1][event_key]) if ordered else None


def invitation_state(invite: dict, events: Iterable[dict], *, now: datetime | None=None) -> str:
    state=latest_event_state(events)
    if state in {"accepted","revoked","expired"}: return state
    now=now or datetime.now(timezone.utc)
    expires=invite["expires_at"]
    if expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
    return "expired" if expires<=now else "pending"


@dataclass(frozen=True, slots=True)
class AccountAccess:
    mode: str
    account_ids: frozenset[str]

    def allows(self, account_id: str) -> bool:
        return self.mode=="all_accounts" or account_id in self.account_ids

def validate_owner_management(*, actor_role: str, target_role: str) -> None:
    """Only an Owner may create/revoke/manage Owner-level access."""
    if target_role == "owner" and actor_role != "owner":
        raise PermissionError("only an owner can manage owner access")


def validate_member_transition(*, actor_role: str, current_role: str, current_status: str, new_role: str, new_status: str, other_active_owner_count: int) -> None:
    """Validate privileged membership transitions after the tenant admin lock is held."""
    if actor_role != "owner" and (current_role == "owner" or new_role == "owner"):
        raise PermissionError("only an owner can manage owner access")
    removes_active_owner = current_role == "owner" and current_status == "active" and (new_role != "owner" or new_status != "active")
    if removes_active_owner and other_active_owner_count < 1:
        raise ValueError("organization must retain at least one active owner")

