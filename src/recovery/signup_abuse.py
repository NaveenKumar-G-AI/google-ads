from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from urllib import request as urlrequest
from urllib.error import URLError
from uuid import UUID

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN_LENGTH = 2048


class SignupAbuseVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TurnstileVerification:
    hostname: str
    action: str
    challenge_ts: datetime | None


@dataclass(frozen=True, slots=True)
class TurnstileConfig:
    site_key: str
    secret_key: str
    expected_hostnames: frozenset[str]
    action: str = "workspace-create"
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        if not self.site_key.strip():
            raise ValueError("Turnstile site key is required")
        if not self.secret_key.strip():
            raise ValueError("Turnstile secret key is required")
        if not self.expected_hostnames:
            raise ValueError("at least one Turnstile hostname is required")
        normalized={h.strip().lower().rstrip('.') for h in self.expected_hostnames if h.strip()}
        if not normalized or any('/' in h or ':' in h for h in normalized):
            raise ValueError("Turnstile hostnames must be bare DNS hostnames")
        if len(self.action)>32 or not self.action:
            raise ValueError("Turnstile action must be 1-32 characters")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 20:
            raise ValueError("Turnstile timeout must be between 0 and 20 seconds")
        object.__setattr__(self,"expected_hostnames",frozenset(normalized))


class TurnstileVerifier:
    def __init__(self, config: TurnstileConfig) -> None:
        self.config=config

    def verify(self, *, token: str, idempotency_key: UUID) -> TurnstileVerification:
        raw=token.strip()
        if not raw or len(raw)>MAX_TOKEN_LENGTH:
            raise SignupAbuseVerificationError("workspace security challenge is missing or invalid")
        body=json.dumps({
            "secret":self.config.secret_key,
            "response":raw,
            "idempotency_key":str(idempotency_key),
        },separators=(",",":"),ensure_ascii=False).encode("utf-8")
        req=urlrequest.Request(
            SITEVERIFY_URL,data=body,method="POST",
            headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"RecoveryOS/1"},
        )
        try:
            with urlrequest.urlopen(req,timeout=self.config.timeout_seconds) as response:
                if response.status != 200:
                    raise SignupAbuseVerificationError("workspace security challenge could not be verified")
                payload=json.loads(response.read(64_000).decode("utf-8"))
        except SignupAbuseVerificationError:
            raise
        except (URLError,TimeoutError,OSError,ValueError,json.JSONDecodeError) as exc:
            raise SignupAbuseVerificationError("workspace security challenge could not be verified") from exc
        if not isinstance(payload,dict) or payload.get("success") is not True:
            raise SignupAbuseVerificationError("workspace security challenge was rejected")
        hostname=str(payload.get("hostname") or "").strip().lower().rstrip('.')
        action=str(payload.get("action") or "").strip()
        if hostname not in self.config.expected_hostnames:
            raise SignupAbuseVerificationError("workspace security challenge hostname mismatch")
        if action != self.config.action:
            raise SignupAbuseVerificationError("workspace security challenge action mismatch")
        challenge_ts=None
        raw_ts=payload.get("challenge_ts")
        if raw_ts:
            try:
                challenge_ts=datetime.fromisoformat(str(raw_ts).replace("Z","+00:00"))
                if challenge_ts.tzinfo is None or challenge_ts.utcoffset() is None:
                    raise ValueError("naive timestamp")
                challenge_ts=challenge_ts.astimezone(timezone.utc)
            except Exception as exc:
                raise SignupAbuseVerificationError("workspace security challenge timestamp is invalid") from exc
            now=datetime.now(timezone.utc)
            if challenge_ts>now+timedelta(minutes=1) or now-challenge_ts>timedelta(minutes=6):
                raise SignupAbuseVerificationError("workspace security challenge is expired or future-dated")
        return TurnstileVerification(hostname=hostname,action=action,challenge_ts=challenge_ts)
