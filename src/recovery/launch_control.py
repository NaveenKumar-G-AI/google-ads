from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Iterable


class LaunchMode(str, Enum):
    CLOSED = "closed"
    PILOT_ONLY = "pilot_only"
    INVITE_ONLY = "invite_only"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class LaunchState:
    mode: LaunchMode
    release_id: str | None
    qualification_id: str | None
    reason: str
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class LaunchAccessState:
    allowed: bool
    expires_at: datetime | None
    subject_hint: str | None


def normalize_launch_email(value: str) -> str:
    email=value.strip().lower()
    if not email or "@" not in email or any(ch.isspace() for ch in email) or len(email)>320:
        raise ValueError("valid email is required")
    return email


def launch_email_sha256(value: str) -> str:
    return hashlib.sha256(normalize_launch_email(value).encode("utf-8")).hexdigest()


def launch_email_hint(value: str) -> str:
    email=normalize_launch_email(value); local,domain=email.split("@",1)
    if len(local)<=2: masked=local[0]+"*"*(len(local)-1)
    else: masked=local[0]+"*"*(len(local)-2)+local[-1]
    return f"{masked}@{domain}"


def derive_launch_state(events: Iterable[dict[str, Any]]) -> LaunchState:
    rows=list(events)
    if not rows:
        return LaunchState(LaunchMode.CLOSED,None,None,"default closed",None)
    latest=max(rows,key=lambda x:(x.get("occurred_at") or datetime.min.replace(tzinfo=timezone.utc),str(x.get("id") or "")))
    return LaunchState(
        LaunchMode(str(latest["launch_mode"])),
        str(latest.get("release_id") or "").strip() or None,
        str(latest.get("qualification_id") or "").strip() or None,
        str(latest.get("reason") or ""),latest.get("occurred_at"),
    )


def derive_launch_access(events: Iterable[dict[str, Any]], *, now: datetime | None=None) -> LaunchAccessState:
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); rows=list(events)
    if not rows:return LaunchAccessState(False,None,None)
    latest=max(rows,key=lambda x:(x.get("occurred_at") or datetime.min.replace(tzinfo=timezone.utc),str(x.get("id") or "")))
    expires=latest.get("expires_at")
    if expires is not None and expires.tzinfo is None: raise ValueError("launch access expires_at must be timezone-aware")
    active=str(latest.get("event_type"))=="granted" and (expires is None or expires>now)
    return LaunchAccessState(active,expires,latest.get("subject_hint"))


def workspace_creation_allowed(mode: LaunchMode, access: LaunchAccessState) -> bool:
    if mode is LaunchMode.PUBLIC:return True
    if mode in {LaunchMode.PILOT_ONLY,LaunchMode.INVITE_ONLY}:return access.allowed
    return False
