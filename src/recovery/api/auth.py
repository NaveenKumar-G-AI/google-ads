from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import UUID


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    """Verified application identity.

    Tenant authorization is intentionally *not* embedded here. A valid Supabase JWT
    proves who the user is; tenant membership is resolved from our own database.
    """

    user_id: UUID
    subject: str
    email: str | None
    issuer: str
    audience: str
    role_claim: str
    issued_at: datetime | None
    expires_at: datetime

    @property
    def actor_id(self) -> str:
        return f"user:{self.user_id}"


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Principal: ...


class SupabaseJWTVerifier:
    """Verify Supabase Auth access tokens against asymmetric JWKS keys.

    Production intentionally supports only RS256/ES256 signing keys. Supabase marks
    HS256 shared-secret signing as not recommended for production; keeping the secret
    out of the API process also reduces blast radius.
    """

    ALLOWED_ALGORITHMS = ("ES256", "RS256")

    def __init__(self, *, project_url: str, audience: str = "authenticated") -> None:
        base = project_url.strip().rstrip("/")
        if not base.startswith("https://"):
            raise ValueError("Supabase project_url must be HTTPS")
        if not audience.strip():
            raise ValueError("JWT audience is required")
        self.project_url = base
        self.issuer = f"{base}/auth/v1"
        self.audience = audience.strip()
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - dependency error in production only
            raise RuntimeError("PyJWT[crypto] is required for JWT verification") from exc
        self._jwt = jwt
        self._jwks_client = jwt.PyJWKClient(self.jwks_url, cache_keys=True)

    @staticmethod
    def _uuid_subject(value: Any) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise AuthenticationError("JWT subject is not a valid user UUID") from exc

    def verify(self, token: str) -> Principal:
        raw = token.strip()
        if not raw:
            raise AuthenticationError("missing bearer token")
        try:
            header = self._jwt.get_unverified_header(raw)
            algorithm = header.get("alg")
            if algorithm not in self.ALLOWED_ALGORITHMS:
                raise AuthenticationError("unsupported JWT signing algorithm")
            signing_key = self._jwks_client.get_signing_key_from_jwt(raw)
            claims: Mapping[str, Any] = self._jwt.decode(
                raw,
                signing_key.key,
                algorithms=list(self.ALLOWED_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "require": ["exp", "sub", "iss", "aud", "role"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("invalid or expired access token") from exc

        role = str(claims.get("role", ""))
        if role != "authenticated":
            # Never accept service-role/anon tokens as end-user identities.
            raise AuthenticationError("JWT role is not an authenticated user")
        user_id = self._uuid_subject(claims.get("sub"))
        exp = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        iat_raw = claims.get("iat")
        iat = (
            datetime.fromtimestamp(int(iat_raw), tz=timezone.utc)
            if iat_raw is not None
            else None
        )
        aud_claim = claims.get("aud")
        if isinstance(aud_claim, list):
            aud = self.audience if self.audience in aud_claim else str(aud_claim[0])
        else:
            aud = str(aud_claim)
        email = claims.get("email")
        return Principal(
            user_id=user_id,
            subject=str(claims["sub"]),
            email=str(email) if email is not None else None,
            issuer=str(claims["iss"]),
            audience=aud,
            role_claim=role,
            issued_at=iat,
            expires_at=exp,
        )


class StaticTokenVerifier:
    """Test/dev verifier. Never constructed by create_app_from_env()."""

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        self._tokens = dict(tokens)

    def verify(self, token: str) -> Principal:
        try:
            principal = self._tokens[token]
        except KeyError as exc:
            raise AuthenticationError("invalid access token") from exc
        if principal.expires_at <= datetime.now(timezone.utc):
            raise AuthenticationError("expired access token")
        return principal
