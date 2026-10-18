from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from recovery.api.auth import AuthenticationError, Principal, StaticTokenVerifier, SupabaseJWTVerifier


def p(expired=False):
    return Principal(
        user_id=uuid4(), subject=str(uuid4()), email=None,
        issuer="https://p.supabase.co/auth/v1", audience="authenticated",
        role_claim="authenticated", issued_at=None,
        expires_at=datetime.now(timezone.utc) + (timedelta(seconds=-1) if expired else timedelta(hours=1)),
    )


def test_supabase_verifier_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        SupabaseJWTVerifier(project_url="http://project.supabase.co")


def test_static_verifier_rejects_unknown_and_expired_tokens():
    good = p()
    verifier = StaticTokenVerifier({"good": good, "old": p(expired=True)})
    assert verifier.verify("good") == good
    with pytest.raises(AuthenticationError):
        verifier.verify("missing")
    with pytest.raises(AuthenticationError):
        verifier.verify("old")
