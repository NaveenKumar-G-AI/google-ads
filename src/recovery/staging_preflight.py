from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import stat
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import UUID

from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.db.canonical import canonical_payload, payload_sha256
from recovery.google_ads.auth import (
    ServiceAccountConfig,
    build_service_account_client,
    normalize_customer_id,
)
from recovery.google_ads.adapter import GoogleAdsV26Adapter
from recovery.staging_validation import PINNED_RUNTIME_PACKAGES, redact_dsn


PHASE15_PREFLIGHT_SCHEMA_VERSION = 1
READ_ONLY_ACK_VALUE = "READ_ONLY_ONLY"


class PreflightStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    status: PreflightStatus
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreflightReport:
    started_at: datetime
    finished_at: datetime
    checks: tuple[PreflightCheck, ...]
    schema_version: int = PHASE15_PREFLIGHT_SCHEMA_VERSION

    @property
    def failed(self) -> bool:
        return any(c.status is PreflightStatus.FAIL for c in self.checks)

    @property
    def fingerprint_sha256(self) -> str:
        return payload_sha256({
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "checks": [asdict(c) for c in self.checks],
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "failed": self.failed,
            "fingerprint_sha256": self.fingerprint_sha256,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "detail": c.detail,
                    "evidence": canonical_payload(dict(c.evidence)),
                }
                for c in self.checks
            ],
        }


@dataclass(frozen=True, slots=True)
class PreflightConfig:
    database_url: str | None
    app_database_url: str | None
    tenant_id: str | None
    tenant_slug: str | None
    tenant_name: str | None
    customer_id: str | None
    business_truth_path: Path | None
    conversion_lag_days: int | None
    run_analysis: bool = True
    run_gemini: bool = True
    probe_database: bool = False
    probe_google: bool = False
    probe_gemini: bool = False
    report_path: Path | None = None


@dataclass(frozen=True, slots=True)
class ConnectionClassification:
    kind: str
    host: str | None
    port: int | None
    supabase: bool


def classify_postgres_connection(dsn: str) -> ConnectionClassification:
    parts = urlsplit(dsn)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("database URL must use postgres:// or postgresql://")
    host = (parts.hostname or "").lower()
    port = parts.port or 5432
    supabase = host.endswith("supabase.co") or ".supabase.com" in host
    if supabase and host.startswith("db.") and port == 5432:
        kind = "supabase_direct"
    elif supabase and "pooler.supabase.com" in host and port == 5432:
        kind = "supabase_session_pooler"
    elif supabase and "pooler.supabase.com" in host and port == 6543:
        kind = "supabase_transaction_pooler"
    elif port == 6543:
        kind = "transaction_pooler_or_custom"
    else:
        kind = "postgres_other"
    return ConnectionClassification(kind, parts.hostname, port, supabase)


def _package_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for pkg in PINNED_RUNTIME_PACKAGES:
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def _safe_json_load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("JSON file exceeds 5 MiB staging limit")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


class Phase15Preflight:
    """Fail-fast staging setup verifier. It never mutates Google Ads."""

    def __init__(self, config: PreflightConfig) -> None:
        self.config = config
        self.checks: list[PreflightCheck] = []
        self.truth: Any | None = None
        self.normalized_customer_id: str | None = None

    def _add(self, name: str, status: PreflightStatus, detail: str, **evidence: Any) -> None:
        self.checks.append(PreflightCheck(name, status, detail, evidence))

    def run(self) -> PreflightReport:
        started = datetime.now(timezone.utc)
        self._python_runtime()
        self._package_runtime()
        self._read_only_ack()
        self._tenant_inputs()
        self._database_urls()
        self._google_credentials()
        self._business_truth()
        self._gemini_credentials()
        if self.config.probe_database:
            self._database_live_probe()
        if self.config.probe_google:
            self._google_live_probe()
        if self.config.probe_gemini:
            self._gemini_live_probe()
        finished = datetime.now(timezone.utc)
        report = PreflightReport(started, finished, tuple(self.checks))
        if self.config.report_path:
            self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.report_path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return report

    def _python_runtime(self) -> None:
        version = sys.version_info
        ok = (3, 11) <= (version.major, version.minor) < (3, 15)
        self._add(
            "python_runtime",
            PreflightStatus.PASS if ok else PreflightStatus.FAIL,
            "Python version is within the supported 3.11–3.14 range." if ok else "Python 3.11–3.14 is required.",
            python=platform.python_version(),
        )

    def _package_runtime(self) -> None:
        actual = _package_versions()
        mismatch = {
            pkg: {"expected": expected, "actual": actual[pkg]}
            for pkg, expected in PINNED_RUNTIME_PACKAGES.items()
            if actual[pkg] != expected
        }
        self._add(
            "pinned_packages",
            PreflightStatus.FAIL if mismatch else PreflightStatus.PASS,
            "Exact Phase-15 package pins are installed." if not mismatch else "Install the exact pinned packages before trusting staging results.",
            mismatches=mismatch,
        )

    def _read_only_ack(self) -> None:
        value = os.getenv("RECOVERY_PHASE15_READ_ONLY_ACK", "")
        self._add(
            "read_only_ack",
            PreflightStatus.PASS if value == READ_ONLY_ACK_VALUE else PreflightStatus.FAIL,
            "Read-only staging acknowledgement is present." if value == READ_ONLY_ACK_VALUE else f"Set RECOVERY_PHASE15_READ_ONLY_ACK={READ_ONLY_ACK_VALUE}.",
        )

    def _tenant_inputs(self) -> None:
        errors: list[str] = []
        try:
            if not self.config.tenant_id:
                raise ValueError("tenant ID missing")
            UUID(self.config.tenant_id)
        except Exception:
            errors.append("RECOVERY_STAGING_TENANT_ID must be a UUID")
        if not (self.config.tenant_slug or "").strip():
            errors.append("RECOVERY_STAGING_TENANT_SLUG is required")
        if not (self.config.tenant_name or "").strip():
            errors.append("RECOVERY_STAGING_TENANT_NAME is required")
        try:
            if not self.config.customer_id:
                raise ValueError("missing")
            self.normalized_customer_id = normalize_customer_id(self.config.customer_id)
        except Exception as exc:
            errors.append(f"RECOVERY_STAGING_CUSTOMER_ID invalid: {exc}")
        if self.config.run_analysis and self.config.conversion_lag_days is None:
            errors.append("conversion_lag_days is required when analysis is enabled")
        if self.config.conversion_lag_days is not None and not (0 <= self.config.conversion_lag_days <= 365):
            errors.append("conversion_lag_days must be between 0 and 365")
        self._add(
            "staging_identity",
            PreflightStatus.FAIL if errors else PreflightStatus.PASS,
            "; ".join(errors) if errors else "Tenant/customer identifiers and analysis window settings are structurally valid.",
            customer_id=self.normalized_customer_id,
        )

    def _database_urls(self) -> None:
        if not self.config.database_url:
            self._add("database_admin_url", PreflightStatus.FAIL, "RECOVERY_STAGING_DATABASE_URL is required.")
        else:
            try:
                info = classify_postgres_connection(self.config.database_url)
                if info.kind in {"supabase_transaction_pooler", "transaction_pooler_or_custom"}:
                    status = PreflightStatus.FAIL
                    detail = "Do not use a transaction-pooler URL for Phase-15 migrations/admin validation; use direct PostgreSQL or a session connection."
                elif info.kind == "supabase_session_pooler":
                    status = PreflightStatus.WARN
                    detail = "Supabase session pooler is usable for persistent sessions, but Supabase recommends the direct connection for migrations when reachable."
                else:
                    status = PreflightStatus.PASS
                    detail = "Administrative PostgreSQL URL is structurally suitable for Phase-15 staging."
                self._add(
                    "database_admin_url", status, detail,
                    connection_kind=info.kind, dsn=redact_dsn(self.config.database_url),
                )
            except Exception as exc:
                self._add("database_admin_url", PreflightStatus.FAIL, str(exc))

        if not self.config.app_database_url:
            self._add(
                "database_app_url", PreflightStatus.WARN,
                "RECOVERY_STAGING_APP_DATABASE_URL is missing; behavioral RLS isolation cannot be proven.",
            )
        else:
            try:
                info = classify_postgres_connection(self.config.app_database_url)
                if info.kind in {"supabase_transaction_pooler", "transaction_pooler_or_custom"}:
                    status = PreflightStatus.FAIL
                    detail = "Phase-15 behavioral RLS uses session state; do not use transaction-pooler mode for RECOVERY_STAGING_APP_DATABASE_URL."
                else:
                    status = PreflightStatus.PASS
                    detail = "Application-role PostgreSQL URL is structurally compatible with the behavioral RLS probe."
                self._add(
                    "database_app_url", status, detail,
                    connection_kind=info.kind, dsn=redact_dsn(self.config.app_database_url),
                )
            except Exception as exc:
                self._add("database_app_url", PreflightStatus.FAIL, str(exc))

    def _google_credentials(self) -> None:
        key_env = "GOOGLE_ADS_JSON_KEY_FILE_PATH"
        key_value = os.getenv(key_env, "").strip()
        if not key_value:
            legacy_path = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_JSON", "").strip()
            detail = "Google Ads service-account key path is missing."
            if legacy_path:
                detail += " GOOGLE_ADS_SERVICE_ACCOUNT_JSON is set, but Phase 15 intentionally expects GOOGLE_ADS_JSON_KEY_FILE_PATH; set the explicit staging key-path variable too."
            self._add(
                "google_ads_credentials", PreflightStatus.FAIL,
                detail, missing_env=[key_env],
            )
            return
        key_path = Path(key_value).expanduser()
        try:
            key = _safe_json_load(key_path)
            required = ("type", "project_id", "private_key_id", "private_key", "client_email")
            absent = [x for x in required if not key.get(x)]
            if absent:
                raise ValueError(f"service-account JSON missing fields: {absent}")
            if key.get("type") != "service_account":
                raise ValueError("Google key JSON type must be service_account")
            if not str(key.get("private_key", "")).startswith("-----BEGIN PRIVATE KEY-----"):
                raise ValueError("service-account private_key is malformed")
            login_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip() or None
            normalized_login = normalize_customer_id(login_id) if login_id else None
            legacy_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip() or None
            # Exercise the same domain config validation without exposing secrets.
            ServiceAccountConfig(
                json_key_file_path=str(key_path),
                developer_token=legacy_token,
                login_customer_id=normalized_login,
            )
            evidence: dict[str, Any] = {
                "service_account_email": key.get("client_email"),
                "project_id": key.get("project_id"),
                "key_file": key_path.name,
                "login_customer_id": normalized_login,
                "developer_token_present_legacy": bool(legacy_token),
            }
            if os.name != "nt":
                mode = stat.S_IMODE(key_path.stat().st_mode)
                evidence["key_file_mode_octal"] = oct(mode)
                if mode & 0o077:
                    self._add(
                        "google_key_file_permissions", PreflightStatus.WARN,
                        "Service-account key file is readable by group/other users; restrict filesystem permissions.",
                        key_file=key_path.name, mode=oct(mode),
                    )
            self._add(
                "google_ads_credentials", PreflightStatus.PASS,
                "Google Ads service-account file is structurally valid. API access is controlled by the owning Google Cloud project's Google Ads API access level; the legacy developer token is optional and ignored by current Google Ads API servers.",
                **evidence,
            )
            if legacy_token:
                self._add(
                    "google_ads_developer_token_legacy", PreflightStatus.WARN,
                    "GOOGLE_ADS_DEVELOPER_TOKEN is set but Google sunset developer tokens on 2026-09-09. Keep it only for backwards compatibility; project-level API access is authoritative.",
                )
        except Exception as exc:
            self._add("google_ads_credentials", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _business_truth(self) -> None:
        if not self.config.run_analysis and not self.config.run_gemini:
            self._add("business_truth", PreflightStatus.SKIP, "Analysis/Gemini checks are disabled.")
            return
        path = self.config.business_truth_path
        if path is None:
            self._add("business_truth", PreflightStatus.FAIL, "--business-truth is required for analysis or Gemini validation.")
            return
        try:
            payload = _safe_json_load(path)
            fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
            truth = parse_business_truth_payload(payload, submitted_by="phase15-preflight", submitted_at=fixed_time)
            self.truth = truth
            self._add(
                "business_truth", PreflightStatus.PASS,
                "Business Truth JSON passes the Phase-2 domain validators.",
                file=path.name,
                file_sha256=payload_sha256(payload),
                business_id=truth.business_id,
                business_name=truth.business_name,
                version=truth.version,
                offers=len(truth.offers),
                explicit_non_offers=len(truth.explicit_non_offers),
                outcomes=len(truth.outcomes),
            )
        except Exception as exc:
            self._add("business_truth", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _gemini_credentials(self) -> None:
        if not self.config.run_gemini:
            self._add("gemini_credentials", PreflightStatus.SKIP, "Gemini staging check is disabled.")
            return
        gemini = os.getenv("GEMINI_API_KEY", "").strip()
        google = os.getenv("GOOGLE_API_KEY", "").strip()
        if not gemini and not google:
            self._add("gemini_credentials", PreflightStatus.FAIL, "Set GEMINI_API_KEY or GOOGLE_API_KEY for the real shadow semantic probe.")
            return
        if google and gemini:
            self._add(
                "gemini_credentials", PreflightStatus.WARN,
                "Both GOOGLE_API_KEY and GEMINI_API_KEY are set; the Google GenAI SDK gives GOOGLE_API_KEY precedence. Keep only the intended credential to avoid testing the wrong project.",
                selected_env="GOOGLE_API_KEY",
            )
        else:
            self._add(
                "gemini_credentials", PreflightStatus.PASS,
                "A Gemini API credential environment variable is present; its value is not recorded.",
                selected_env="GOOGLE_API_KEY" if google else "GEMINI_API_KEY",
            )

    def _database_live_probe(self) -> None:
        if not self.config.database_url:
            self._add("database_live", PreflightStatus.SKIP, "No admin database URL available.")
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.config.database_url, row_factory=dict_row, connect_timeout=10) as conn, conn.cursor() as cur:
                cur.execute("SELECT current_database() AS db, current_user AS usr, current_setting('server_version') AS ver")
                row = cur.fetchone()
                cur.execute("SELECT to_regclass('recovery.schema_migrations') AS migrations")
                mig = cur.fetchone()["migrations"]
            self._add(
                "database_live", PreflightStatus.PASS,
                "Administrative PostgreSQL connection succeeded.",
                database=row["db"], user=row["usr"], server_version=row["ver"], migrations_table_present=bool(mig),
            )
        except Exception as exc:
            self._add("database_live", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")

        if self.config.app_database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
                with psycopg.connect(self.config.app_database_url, row_factory=dict_row, connect_timeout=10) as conn, conn.cursor() as cur:
                    cur.execute("SELECT current_user AS usr, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
                    r = cur.fetchone()
                if r["rolsuper"] or r["rolbypassrls"]:
                    self._add(
                        "database_app_role_live", PreflightStatus.FAIL,
                        "Application-role connection is privileged and cannot prove RLS isolation.",
                        user=r["usr"], rolsuper=bool(r["rolsuper"]), rolbypassrls=bool(r["rolbypassrls"]),
                    )
                else:
                    self._add(
                        "database_app_role_live", PreflightStatus.PASS,
                        "Application-role connection is non-superuser and does not bypass RLS.",
                        user=r["usr"],
                    )
            except Exception as exc:
                self._add("database_app_role_live", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _google_live_probe(self) -> None:
        if not self.normalized_customer_id:
            self._add("google_ads_live", PreflightStatus.SKIP, "Customer ID is not valid.")
            return
        try:
            cfg = ServiceAccountConfig(
                json_key_file_path=os.environ["GOOGLE_ADS_JSON_KEY_FILE_PATH"],
                developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None,
                login_customer_id=os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None,
            )
            client = build_service_account_client(cfg)
            profile = GoogleAdsV26Adapter(client).get_customer_profile(self.normalized_customer_id)
            if profile.manager:
                raise RuntimeError("target customer is a manager account; Phase 15 requires an advertiser account")
            if str(profile.status).upper() != "ENABLED":
                raise RuntimeError(f"target advertiser status is {profile.status}, expected ENABLED")
            self._add(
                "google_ads_live", PreflightStatus.PASS,
                "Read-only Google Ads profile call succeeded.",
                customer_id=profile.customer_id,
                descriptive_name=profile.descriptive_name,
                status=profile.status,
                currency_code=profile.currency_code,
                time_zone=profile.time_zone,
                test_account=profile.test_account,
            )
        except Exception as exc:
            self._add("google_ads_live", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _gemini_live_probe(self) -> None:
        try:
            from google import genai
            client = genai.Client()
            interaction = client.interactions.create(
                model="gemini-3.8-flash",
                input="Return exactly the word READY.",
                store=False,
            )
            text = str(getattr(interaction, "output_text", "")).strip()
            if not text:
                raise RuntimeError("Gemini call returned no output text")
            self._add(
                "gemini_live", PreflightStatus.PASS,
                "Gemini authentication/connectivity probe succeeded.",
                model="gemini-3.8-flash",
                provider_model_version=(str(getattr(interaction, "model_version")) if getattr(interaction, "model_version", None) else None),
                request_id=(str(getattr(interaction, "id")) if getattr(interaction, "id", None) else None),
            )
        except Exception as exc:
            self._add("gemini_live", PreflightStatus.FAIL, f"{type(exc).__name__}: {exc}")


def build_config_from_env(args: argparse.Namespace) -> PreflightConfig:
    return PreflightConfig(
        database_url=os.getenv("RECOVERY_STAGING_DATABASE_URL") or None,
        app_database_url=os.getenv("RECOVERY_STAGING_APP_DATABASE_URL") or None,
        tenant_id=os.getenv("RECOVERY_STAGING_TENANT_ID") or None,
        tenant_slug=os.getenv("RECOVERY_STAGING_TENANT_SLUG") or None,
        tenant_name=os.getenv("RECOVERY_STAGING_TENANT_NAME") or None,
        customer_id=os.getenv("RECOVERY_STAGING_CUSTOMER_ID") or None,
        business_truth_path=Path(args.business_truth).expanduser() if args.business_truth else None,
        conversion_lag_days=args.conversion_lag_days,
        run_analysis=not args.skip_analysis,
        run_gemini=not args.skip_gemini,
        probe_database=args.probe_services,
        probe_google=args.probe_services,
        probe_gemini=args.probe_services and not args.skip_gemini,
        report_path=Path(args.report).expanduser() if args.report else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 15 staging credential/setup preflight")
    parser.add_argument("--business-truth")
    parser.add_argument("--conversion-lag-days", type=int)
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--probe-services", action="store_true", help="Perform live read-only DB/Google/Gemini connectivity calls")
    parser.add_argument("--report", default="phase15-preflight-report.json")
    args = parser.parse_args(argv)
    report = Phase15Preflight(build_config_from_env(args)).run()
    for check in report.checks:
        print(f"[{check.status.value.upper():4}] {check.name}: {check.detail}")
    print(f"Preflight fingerprint: {report.fingerprint_sha256}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
