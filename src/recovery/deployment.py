from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from recovery.db.canonical import payload_sha256
from recovery.db.postgres import PostgresRecoveryRepository


@dataclass(frozen=True, slots=True)
class DeploymentCheck:
    name: str
    status: str  # pass | warn | fail | skip
    detail: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeploymentReport:
    environment: str
    generated_at: str
    ready: bool
    checks: tuple[DeploymentCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "generated_at": self.generated_at,
            "ready": self.ready,
            "checks": [asdict(c) for c in self.checks],
        }


_SECRET_NAMES = {
    "DATABASE_URL", "RECOVERY_WORKER_DATABASE_URL", "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    "GOOGLE_ADS_SERVICE_ACCOUNT_JSON", "GOOGLE_ADS_JSON_KEY_FILE_PATH",
}


def _present(value: str | None) -> bool:
    return bool((value or "").strip())


def _https_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def _bundled_migrations() -> dict[str, str]:
    root = resources.files("recovery.db.migrations")
    output: dict[str, str] = {}
    for item in sorted((p for p in root.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name):
        sql_text = item.read_text(encoding="utf-8")
        output[item.name] = payload_sha256({"filename": item.name, "sql": sql_text})
    return output


def _safe_service_account_metadata(path_value: str | None) -> dict[str, Any]:
    path = Path((path_value or "").strip())
    if not str(path):
        return {"configured": False}
    if not path.is_file():
        return {"configured": True, "exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"configured": True, "exists": True, "valid_json": False}
    # Never return private_key/private_key_id or raw credential bytes.
    return {
        "configured": True,
        "exists": True,
        "valid_json": True,
        "type": payload.get("type"),
        "project_id": payload.get("project_id"),
        "client_email_present": bool(payload.get("client_email")),
        "private_key_present": bool(payload.get("private_key")),
    }


class ProductionReadiness:
    """Fail-closed production/staging deployment checks.

    This checker intentionally validates configuration and durable infrastructure only.
    It never mutates Google Ads and never includes secret values in its report.
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = dict(os.environ if env is None else env)
        self.checks: list[DeploymentCheck] = []

    def _add(self, name: str, status: str, detail: str, **metadata: Any) -> None:
        self.checks.append(DeploymentCheck(name, status, detail, metadata))

    def _environment(self) -> str:
        value = self.env.get("RECOVERY_ENVIRONMENT", "").strip().lower()
        if value not in {"staging", "production"}:
            self._add("environment", "fail", "RECOVERY_ENVIRONMENT must be staging or production")
            return value or "unknown"
        self._add("environment", "pass", f"deployment environment is {value}")
        return value

    def _static_config(self, environment: str) -> None:
        db = self.env.get("DATABASE_URL", "")
        worker_db = self.env.get("RECOVERY_WORKER_DATABASE_URL", "")
        supabase = self.env.get("SUPABASE_URL", "")
        origins = [x.strip() for x in self.env.get("API_ALLOWED_ORIGINS", "").split(",") if x.strip()]

        self._add("api_database", "pass" if _present(db) else "fail",
                  "API database DSN configured" if _present(db) else "DATABASE_URL is required")
        self._add("worker_database", "pass" if _present(worker_db) else "fail",
                  "worker database DSN configured" if _present(worker_db) else "RECOVERY_WORKER_DATABASE_URL is required")
        self._add("supabase_url", "pass" if _https_url(supabase) else "fail",
                  "Supabase project URL is HTTPS" if _https_url(supabase) else "SUPABASE_URL must be a valid HTTPS URL")

        if not origins:
            self._add("cors_origins", "fail", "API_ALLOWED_ORIGINS must contain the deployed dashboard origin")
        elif "*" in origins:
            self._add("cors_origins", "fail", "wildcard CORS origin is forbidden")
        elif environment == "production" and any(not _https_url(x) for x in origins):
            self._add("cors_origins", "fail", "production CORS origins must use HTTPS", count=len(origins))
        else:
            self._add("cors_origins", "pass", "CORS origins are explicit", count=len(origins))

        if environment == "production":
            ack = self.env.get("RECOVERY_BACKUP_POLICY_ACK", "").strip()
            if ack != "PITR_OR_DAILY_BACKUP_VERIFIED":
                self._add("backup_policy", "fail",
                          "production requires explicit backup/PITR verification acknowledgement")
            else:
                self._add("backup_policy", "pass", "backup/PITR verification acknowledged")
        else:
            self._add("backup_policy", "skip", "backup acknowledgement is mandatory only for production")

        # V1 public-launch surface. Syntax checks are deployment checks only; the launch
        # gate separately requires external evidence that these pages/processes were reviewed.
        terms=self.env.get("RECOVERY_TERMS_URL","").strip(); privacy=self.env.get("RECOVERY_PRIVACY_URL","").strip(); deletion=self.env.get("RECOVERY_DATA_DELETION_URL","").strip(); status_url=self.env.get("RECOVERY_STATUS_URL","").strip(); support=self.env.get("RECOVERY_SUPPORT_EMAIL","").strip()
        terms_version=self.env.get("RECOVERY_TERMS_VERSION","").strip(); privacy_version=self.env.get("RECOVERY_PRIVACY_VERSION","").strip()
        if environment=="production":
            if not (_https_url(terms) and _https_url(privacy) and _https_url(deletion)):
                self._add("public_legal_urls","fail","production requires HTTPS Terms, Privacy, and Data Deletion URLs")
            else:self._add("public_legal_urls","pass","public legal/privacy/deletion URLs are HTTPS")
            if not terms_version or not privacy_version or len(terms_version)>120 or len(privacy_version)>120:
                self._add("public_legal_versions","fail","production requires non-empty Terms and Privacy version identifiers of at most 120 characters")
            else:self._add("public_legal_versions","pass","Terms and Privacy version identifiers are configured",terms_version=terms_version,privacy_version=privacy_version)
            if "@" not in support or any(ch.isspace() for ch in support) or len(support)>320:
                self._add("public_support_contact","fail","RECOVERY_SUPPORT_EMAIL must be a valid public support address")
            else:self._add("public_support_contact","pass","public support contact is configured")
            if status_url and not _https_url(status_url):self._add("public_status_url","fail","RECOVERY_STATUS_URL must use HTTPS when configured")
            else:self._add("public_status_url","pass" if status_url else "warn","public status URL configured" if status_url else "public status URL is not configured")
        else:
            self._add("public_legal_urls","skip","public legal URLs are enforced for production launch")
            self._add("public_legal_versions","skip","public legal policy versions are enforced for production launch")
            self._add("public_support_contact","skip","public support contact is enforced for production launch")

        turnstile_site=self.env.get("RECOVERY_TURNSTILE_SITE_KEY","").strip(); turnstile_secret=self.env.get("RECOVERY_TURNSTILE_SECRET","").strip(); turnstile_hosts=[x.strip().lower().rstrip('.') for x in self.env.get("RECOVERY_TURNSTILE_HOSTNAMES","").split(",") if x.strip()]
        try:workspace_limit=int(self.env.get("RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H","1") or 1)
        except ValueError:workspace_limit=-1
        abuse_complete=bool(turnstile_site and turnstile_secret and turnstile_hosts and 1<=workspace_limit<=20)
        bad_hosts=any(h in {"localhost","127.0.0.1","::1"} or "/" in h or ":" in h for h in turnstile_hosts)
        if environment=="production":
            if not abuse_complete or bad_hosts:
                self._add("public_signup_abuse","fail","production requires Turnstile site/secret keys, explicit production hostnames, and a 1-20 per-user 24h workspace limit")
            else:self._add("public_signup_abuse","pass","server-side public signup abuse controls are configured",hostnames=turnstile_hosts,max_workspaces_per_user_24h=workspace_limit)
        elif any((turnstile_site,turnstile_secret,turnstile_hosts)):
            self._add("public_signup_abuse","pass" if abuse_complete and not bad_hosts else "fail","staging public-signup abuse configuration is complete" if abuse_complete and not bad_hosts else "staging Turnstile configuration is partial or invalid",hostnames=turnstile_hosts,max_workspaces_per_user_24h=workspace_limit)
        else:self._add("public_signup_abuse","skip","Turnstile is not configured in this non-production environment")

        # Google Ads production auth. Self-serve SaaS uses multi-user OAuth; a
        # service account is only an optional internal/staging fallback. Developer
        # tokens are intentionally not required in 2026.
        oauth_client_id = self.env.get("GOOGLE_ADS_OAUTH_CLIENT_ID", "").strip()
        oauth_client_secret = self.env.get("GOOGLE_ADS_OAUTH_CLIENT_SECRET", "").strip()
        oauth_redirect = self.env.get("GOOGLE_ADS_OAUTH_REDIRECT_URI", "").strip()
        oauth_secret_project = self.env.get("GOOGLE_OAUTH_SECRET_MANAGER_PROJECT", "").strip()
        oauth_values = (oauth_client_id, oauth_client_secret, oauth_redirect, oauth_secret_project)
        oauth_any = any(_present(v) for v in oauth_values)
        oauth_all = all(_present(v) for v in oauth_values)
        if oauth_any and not oauth_all:
            self._add("google_ads_oauth", "fail", "Google Ads OAuth configuration is partial; client ID, client secret, HTTPS redirect URI and Secret Manager project must be configured together")
        elif oauth_all:
            redirect_ok = _https_url(oauth_redirect)
            origin_match = any(oauth_redirect.startswith(x.rstrip("/") + "/") for x in origins) if origins else False
            if not redirect_ok:
                self._add("google_ads_oauth", "fail", "Google Ads OAuth redirect URI must use HTTPS")
            elif not origin_match:
                self._add("google_ads_oauth", "fail", "Google Ads OAuth redirect URI must belong to an allowed deployed dashboard origin")
            elif environment == "production" and self.env.get("GOOGLE_ADS_OAUTH_VERIFICATION_ACK", "").strip() != "RESTRICTED_SCOPE_VERIFIED":
                self._add("google_ads_oauth", "fail", "production self-serve Google Ads OAuth requires explicit restricted-scope verification acknowledgement")
            else:
                self._add("google_ads_oauth", "pass", "self-serve Google Ads multi-user OAuth is configured", secret_manager_project=oauth_secret_project, redirect_uri=oauth_redirect)
        else:
            self._add("google_ads_oauth", "skip" if environment == "staging" else "fail", "self-serve Google Ads OAuth is not configured")

        if environment=="production":
            access_ack=self.env.get("GOOGLE_ADS_PRODUCTION_ACCESS_ACK","").strip()
            if access_ack!="EXPLORER_OR_HIGHER":
                self._add("google_ads_production_access","fail","production requires explicit Google Ads API Explorer-or-higher access acknowledgement")
            else:self._add("google_ads_production_access","pass","Google Ads API production access level acknowledged")
        else:self._add("google_ads_production_access","skip","production Google Ads access acknowledgement is required only for production")

        service_path = self.env.get("GOOGLE_ADS_SERVICE_ACCOUNT_JSON", "").strip() or self.env.get("GOOGLE_ADS_JSON_KEY_FILE_PATH", "")
        if _present(service_path):
            meta = _safe_service_account_metadata(service_path)
            ok = bool(meta.get("exists") and meta.get("valid_json") and meta.get("client_email_present") and meta.get("private_key_present"))
            self._add("google_ads_credentials", "pass" if ok else "fail",
                      "optional internal service-account fallback is structurally valid" if ok else "configured service-account fallback is structurally invalid",
                      **meta)
        else:
            self._add("google_ads_credentials", "skip", "no legacy/internal service-account fallback configured")

        if not (_present(self.env.get("GEMINI_API_KEY")) or _present(self.env.get("GOOGLE_API_KEY"))):
            self._add("gemini_credentials", "fail", "GEMINI_API_KEY or GOOGLE_API_KEY is required for semantic AI")
        else:
            both = _present(self.env.get("GEMINI_API_KEY")) and _present(self.env.get("GOOGLE_API_KEY"))
            self._add("gemini_credentials", "warn" if both else "pass",
                      "both Gemini key variables are set; provider precedence must be intentional" if both else "Gemini credential configured")

        billing_enabled = self.env.get("BILLING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        grace_raw = self.env.get("BILLING_GRACE_HOURS", "0").strip() or "0"
        try:
            grace_hours = int(grace_raw)
        except ValueError:
            grace_hours = -1
        if not 0 <= grace_hours <= 720:
            self._add("billing_grace_policy", "fail", "BILLING_GRACE_HOURS must be an integer between 0 and 720")
        elif grace_hours == 0:
            self._add("billing_grace_policy", "pass", "billing grace is disabled; provider entitlement state applies immediately", grace_hours=0)
        else:
            self._add("billing_grace_policy", "pass", "bounded Recovery OS billing grace policy is configured", grace_hours=grace_hours)

        if not billing_enabled:
            self._add("billing_mode", "warn" if environment == "production" else "pass", "billing is disabled")
        else:
            key_id = self.env.get("RAZORPAY_KEY_ID", "").strip()
            required = all(_present(self.env.get(k)) for k in ("RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "BILLING_PLANS_JSON"))
            if not key_id or not required:
                self._add("billing_mode", "fail", "billing is enabled but Razorpay/webhook/plan configuration is incomplete")
            elif environment == "production" and not key_id.startswith("rzp_live_"):
                self._add("billing_mode", "fail", "production billing must use a Razorpay live key ID")
            elif environment == "staging" and not key_id.startswith("rzp_test_"):
                self._add("billing_mode", "fail", "staging billing must use a Razorpay test key ID")
            else:
                self._add("billing_mode", "pass", f"Razorpay key mode matches {environment}")
            if environment=="production":
                activation=self.env.get("RAZORPAY_LIVE_ACTIVATION_ACK","").strip(); webhook=self.env.get("RAZORPAY_LIVE_WEBHOOK_ACK","").strip()
                self._add("razorpay_live_activation","pass" if activation=="LIVE_ACCOUNT_ACTIVATED" else "fail","Razorpay live merchant activation acknowledged" if activation=="LIVE_ACCOUNT_ACTIVATED" else "production billing requires live merchant activation acknowledgement")
                self._add("razorpay_live_webhook","pass" if webhook=="LIVE_WEBHOOK_VERIFIED" else "fail","Razorpay live webhook path acknowledged" if webhook=="LIVE_WEBHOOK_VERIFIED" else "production billing requires live webhook verification acknowledgement")

    def _database(self) -> None:
        dsn = self.env.get("DATABASE_URL", "").strip()
        if not dsn:
            self._add("database_connectivity", "skip", "DATABASE_URL is not configured")
            return
        try:
            repo = PostgresRecoveryRepository(dsn)
            expected = _bundled_migrations()
            with repo._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_database() AS db, current_user AS usr, current_setting('server_version') AS version")
                row = cur.fetchone()
                cur.execute("SELECT to_regclass('recovery.schema_migrations') AS relation")
                relation = cur.fetchone()["relation"]
                if relation is None:
                    raise RuntimeError("recovery.schema_migrations is missing")
                cur.execute("SELECT version, sha256 FROM recovery.schema_migrations ORDER BY version")
                applied = {r["version"]: r["sha256"] for r in cur.fetchall()}
                drift = [name for name, digest in expected.items() if applied.get(name) != digest]
                unexpected = sorted(set(applied) - set(expected))
                if drift or unexpected:
                    self._add("migration_integrity", "fail", "live migration registry differs from packaged migrations",
                              missing_or_changed=drift, unexpected=unexpected)
                else:
                    self._add("migration_integrity", "pass", "all packaged migration bytes match live registry",
                              count=len(expected))

                self._add("database_connectivity", "pass", "database connection and recovery schema are readable",
                          database=row["db"], user=row["usr"], server_version=row["version"])

            worker_dsn = self.env.get("RECOVERY_WORKER_DATABASE_URL", "").strip()
            if worker_dsn:
                worker_repo = PostgresRecoveryRepository(worker_dsn)
                with worker_repo._connect() as wconn, wconn.cursor() as cur:
                    cur.execute("""
                        SELECT status, count(*)::int AS n
                        FROM recovery.api_jobs
                        GROUP BY status
                        ORDER BY status
                    """)
                    counts = {r["status"]: int(r["n"]) for r in cur.fetchall()}
                    cur.execute("""
                        SELECT count(*)::int AS n
                        FROM recovery.api_jobs
                        WHERE status='running' AND lease_expires_at < now()
                    """)
                    expired = int(cur.fetchone()["n"])
                    cur.execute("SELECT count(*)::int AS n FROM recovery.api_jobs WHERE status='needs_reconciliation'")
                    reconciliation = int(cur.fetchone()["n"])
                    queue_status = "warn" if expired or reconciliation else "pass"
                    self._add("worker_queue", queue_status,
                              "worker queue has items requiring operator attention" if queue_status == "warn" else "worker queue has no expired leases/reconciliation backlog",
                              counts=counts, expired_running=expired, needs_reconciliation=reconciliation)
            else:
                self._add("worker_queue", "skip", "worker DSN not configured; queue health was not probed")
        except Exception as exc:
            self._add("database_connectivity", "fail", f"database readiness probe failed: {type(exc).__name__}")

    def run(self, *, probe_database: bool = True) -> DeploymentReport:
        environment = self._environment()
        self._static_config(environment)
        if probe_database:
            self._database()
        else:
            self._add("database_connectivity", "skip", "database probe disabled")
        ready = not any(c.status == "fail" for c in self.checks)
        return DeploymentReport(
            environment=environment,
            generated_at=datetime.now(timezone.utc).isoformat(),
            ready=ready,
            checks=tuple(self.checks),
        )


def database_ready(dsn: str) -> dict[str, Any]:
    """Small readiness probe used by the API /readyz endpoint.

    It validates connectivity and exact migration bytes, but never leaks the DSN or SQL errors.
    """
    expected = _bundled_migrations()
    repo = PostgresRecoveryRepository(dsn)
    with repo._connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        if cur.fetchone()["ok"] != 1:
            raise RuntimeError("database SELECT 1 failed")
        cur.execute("SELECT to_regclass('recovery.schema_migrations') AS relation")
        if cur.fetchone()["relation"] is None:
            raise RuntimeError("migration registry missing")
        cur.execute("SELECT version, sha256 FROM recovery.schema_migrations")
        applied = {r["version"]: r["sha256"] for r in cur.fetchall()}
        if set(applied) != set(expected):
            raise RuntimeError("migration set mismatch")
        if any(applied[name] != digest for name, digest in expected.items()):
            raise RuntimeError("migration hash mismatch")
    return {"database": "ready", "migrations": len(expected)}


def migration_main() -> None:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    applied = PostgresRecoveryRepository(dsn).apply_migrations()
    print(json.dumps({"status": "ok", "applied": list(applied)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Ads Recovery deployment readiness check")
    parser.add_argument("--no-database", action="store_true", help="skip live database probe")
    parser.add_argument("--report", help="write JSON report to this path")
    args = parser.parse_args()
    report = ProductionReadiness().run(probe_database=not args.no_database)
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report.ready else 2)


if __name__ == "__main__":
    main()
