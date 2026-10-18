from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database_url: str
    supabase_url: str
    allowed_origins: tuple[str, ...] = ()
    billing_enabled: bool = False
    razorpay_webhook_secret: str = ""
    billing_grace_hours: int = 0
    google_ads_oauth_client_id: str = ""
    google_ads_oauth_client_secret: str = ""
    google_ads_oauth_redirect_uri: str = ""
    google_oauth_secret_manager_project: str = ""
    terms_url: str = ""
    terms_version: str = ""
    privacy_url: str = ""
    privacy_version: str = ""
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    turnstile_hostnames: tuple[str, ...] = ()
    public_workspace_max_per_user_24h: int = 1

    @classmethod
    def from_env(cls) -> "ApiSettings":
        db = os.environ.get("DATABASE_URL", "").strip()
        supabase = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        if not db:
            raise RuntimeError("DATABASE_URL is required")
        if not supabase:
            raise RuntimeError("SUPABASE_URL is required")
        origins_raw = os.environ.get("API_ALLOWED_ORIGINS", "")
        origins = tuple(x.strip() for x in origins_raw.split(",") if x.strip())
        if "*" in origins:
            raise RuntimeError("wildcard CORS origin is forbidden for production API")
        billing_enabled = os.environ.get("BILLING_ENABLED", "").strip().lower() in {"1","true","yes","on"}
        webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
        if billing_enabled and not webhook_secret:
            raise RuntimeError("RAZORPAY_WEBHOOK_SECRET is required when BILLING_ENABLED=true")
        try:
            grace_hours=int(os.environ.get("BILLING_GRACE_HOURS","0") or 0)
        except ValueError as exc:
            raise RuntimeError("BILLING_GRACE_HOURS must be an integer") from exc
        if grace_hours<0 or grace_hours>720:
            raise RuntimeError("BILLING_GRACE_HOURS must be between 0 and 720")
        turnstile_site=os.environ.get("RECOVERY_TURNSTILE_SITE_KEY","").strip()
        turnstile_secret=os.environ.get("RECOVERY_TURNSTILE_SECRET","").strip()
        turnstile_hosts=tuple(sorted({x.strip().lower().rstrip('.') for x in os.environ.get("RECOVERY_TURNSTILE_HOSTNAMES","").split(",") if x.strip()}))
        if any((turnstile_site,turnstile_secret,turnstile_hosts)) and not all((turnstile_site,turnstile_secret,turnstile_hosts)):
            raise RuntimeError("RECOVERY_TURNSTILE_SITE_KEY, RECOVERY_TURNSTILE_SECRET and RECOVERY_TURNSTILE_HOSTNAMES must be configured together")
        try:workspace_limit=int(os.environ.get("RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H","1") or 1)
        except ValueError as exc:raise RuntimeError("RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H must be an integer") from exc
        if workspace_limit<1 or workspace_limit>20:
            raise RuntimeError("RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H must be between 1 and 20")
        return cls(
            database_url=db, supabase_url=supabase, allowed_origins=origins,
            billing_enabled=billing_enabled, razorpay_webhook_secret=webhook_secret, billing_grace_hours=grace_hours,
            google_ads_oauth_client_id=os.environ.get("GOOGLE_ADS_OAUTH_CLIENT_ID", "").strip(),
            google_ads_oauth_client_secret=os.environ.get("GOOGLE_ADS_OAUTH_CLIENT_SECRET", "").strip(),
            google_ads_oauth_redirect_uri=os.environ.get("GOOGLE_ADS_OAUTH_REDIRECT_URI", "").strip(),
            google_oauth_secret_manager_project=os.environ.get("GOOGLE_OAUTH_SECRET_MANAGER_PROJECT", "").strip(),
            terms_url=os.environ.get("RECOVERY_TERMS_URL", "").strip(),
            terms_version=os.environ.get("RECOVERY_TERMS_VERSION", "").strip(),
            privacy_url=os.environ.get("RECOVERY_PRIVACY_URL", "").strip(),
            privacy_version=os.environ.get("RECOVERY_PRIVACY_VERSION", "").strip(),
            turnstile_site_key=turnstile_site,turnstile_secret_key=turnstile_secret,turnstile_hostnames=turnstile_hosts,
            public_workspace_max_per_user_24h=workspace_limit,
        )
