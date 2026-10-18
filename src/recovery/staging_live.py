from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from recovery.staging_preflight import (
    Phase15Preflight,
    PreflightConfig,
    READ_ONLY_ACK_VALUE,
)
from recovery.staging_validation import Phase15StagingValidator, StagingConfig


@dataclass(frozen=True, slots=True)
class LiveBootstrapResult:
    preflight_failed: bool
    staging_failed: bool | None
    preflight_report: Path
    staging_report: Path | None

    @property
    def exit_code(self) -> int:
        if self.preflight_failed:
            return 2
        if self.staging_failed:
            return 3
        return 0


def _interactive_available() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def _secret_prompt(prompt: str) -> str:
    return getpass.getpass(prompt).strip()


def _plain_prompt(prompt: str) -> str:
    return input(prompt).strip()


def _ensure_env(
    name: str,
    *,
    prompt: str,
    secret: bool = False,
    required: bool = True,
    default: str | None = None,
    non_interactive: bool = False,
    prompt_fn: Callable[[str], str] | None = None,
) -> str | None:
    existing = os.getenv(name, "").strip()
    if existing:
        return existing
    if non_interactive or not _interactive_available():
        if default is not None:
            os.environ[name] = default
            return default
        if required:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return None
    ask = prompt_fn or (_secret_prompt if secret else _plain_prompt)
    suffix = f" [{default}]" if default is not None else ""
    value = ask(f"{prompt}{suffix}: ").strip()
    if not value and default is not None:
        value = default
    if not value:
        if required:
            raise RuntimeError(f"A value is required for {name}")
        return None
    os.environ[name] = value
    return value


def _ensure_uuid_env(name: str, *, non_interactive: bool) -> str:
    existing = os.getenv(name, "").strip()
    if existing:
        UUID(existing)
        return existing
    # A staging tenant UUID is not a secret and can be generated deterministically for this run.
    generated = str(uuid4())
    os.environ[name] = generated
    if not non_interactive:
        print(f"Generated {name}={generated}")
    return generated


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _collect_environment(args: argparse.Namespace) -> Path | None:
    _ensure_env(
        "RECOVERY_STAGING_DATABASE_URL",
        prompt="PostgreSQL/Supabase ADMIN or migration connection URL",
        secret=True,
        non_interactive=args.non_interactive,
    )
    _ensure_env(
        "RECOVERY_STAGING_APP_DATABASE_URL",
        prompt="Optional non-BYPASSRLS application-role DB URL (press Enter to skip)",
        secret=True,
        required=False,
        non_interactive=args.non_interactive,
    )
    _ensure_uuid_env("RECOVERY_STAGING_TENANT_ID", non_interactive=args.non_interactive)
    _ensure_env(
        "RECOVERY_STAGING_TENANT_SLUG",
        prompt="Staging tenant slug",
        default="phase15-staging",
        non_interactive=args.non_interactive,
    )
    _ensure_env(
        "RECOVERY_STAGING_TENANT_NAME",
        prompt="Staging tenant name",
        default="Phase 15 Staging",
        non_interactive=args.non_interactive,
    )
    _ensure_env(
        "RECOVERY_STAGING_CUSTOMER_ID",
        prompt="Google Ads advertiser customer ID (10 digits, not manager ID)",
        non_interactive=args.non_interactive,
    )
    _ensure_env(
        "GOOGLE_ADS_JSON_KEY_FILE_PATH",
        prompt="Path to Google service-account JSON file",
        non_interactive=args.non_interactive,
    )
    _ensure_env(
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        prompt="Optional Google Ads manager customer ID (press Enter if direct advertiser access)",
        required=False,
        non_interactive=args.non_interactive,
    )

    os.environ["RECOVERY_PHASE15_READ_ONLY_ACK"] = READ_ONLY_ACK_VALUE

    if not args.skip_gemini:
        if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("GOOGLE_API_KEY", "").strip():
            _ensure_env(
                "GEMINI_API_KEY",
                prompt="Gemini API key (kept only in this process environment)",
                secret=True,
                non_interactive=args.non_interactive,
            )

    truth_path: Path | None = Path(args.business_truth).expanduser().resolve() if args.business_truth else None
    if not args.skip_analysis or not args.skip_gemini:
        if truth_path is None:
            value = _ensure_env(
                "RECOVERY_STAGING_BUSINESS_TRUTH_PATH",
                prompt="Path to user-confirmed Business Truth JSON",
                non_interactive=args.non_interactive,
            )
            truth_path = Path(value or "").expanduser().resolve()
        if not truth_path.is_file():
            raise RuntimeError(f"Business Truth file does not exist: {truth_path}")
    return truth_path


def run_live_bootstrap(args: argparse.Namespace) -> LiveBootstrapResult:
    truth_path = _collect_environment(args)
    report_dir = Path(args.report_dir).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = report_dir / "phase15-preflight-report.json"
    staging_path = report_dir / "phase15-staging-report.json"

    preflight = Phase15Preflight(
        PreflightConfig(
            database_url=os.getenv("RECOVERY_STAGING_DATABASE_URL") or None,
            app_database_url=os.getenv("RECOVERY_STAGING_APP_DATABASE_URL") or None,
            tenant_id=os.getenv("RECOVERY_STAGING_TENANT_ID") or None,
            tenant_slug=os.getenv("RECOVERY_STAGING_TENANT_SLUG") or None,
            tenant_name=os.getenv("RECOVERY_STAGING_TENANT_NAME") or None,
            customer_id=os.getenv("RECOVERY_STAGING_CUSTOMER_ID") or None,
            business_truth_path=truth_path,
            conversion_lag_days=args.conversion_lag_days,
            run_analysis=not args.skip_analysis,
            run_gemini=not args.skip_gemini,
            probe_database=True,
            probe_google=True,
            probe_gemini=not args.skip_gemini,
            report_path=preflight_path,
        )
    ).run()

    for check in preflight.checks:
        print(f"[{check.status.value.upper():4}] {check.name}: {check.detail}")
    print(f"Preflight report: {preflight_path}")
    print(f"Preflight fingerprint: {preflight.fingerprint_sha256}")

    if preflight.failed:
        print("Live staging was NOT started because preflight failed.")
        return LiveBootstrapResult(True, None, preflight_path, None)

    staging = Phase15StagingValidator(
        StagingConfig(
            database_url=os.environ["RECOVERY_STAGING_DATABASE_URL"],
            app_database_url=os.getenv("RECOVERY_STAGING_APP_DATABASE_URL") or None,
            tenant_id=UUID(os.environ["RECOVERY_STAGING_TENANT_ID"]),
            tenant_slug=os.environ["RECOVERY_STAGING_TENANT_SLUG"],
            tenant_name=os.environ["RECOVERY_STAGING_TENANT_NAME"],
            customer_id=os.environ["RECOVERY_STAGING_CUSTOMER_ID"],
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            conversion_lag_days=args.conversion_lag_days,
            business_truth_path=truth_path,
            apply_migrations=not args.no_apply_migrations,
            repeat_sync_probe=not args.no_replay_probe,
            run_analysis=not args.skip_analysis,
            run_gemini=not args.skip_gemini,
            gemini_sample_size=args.gemini_sample_size,
            report_path=staging_path,
        )
    ).run()

    _write_json(staging_path, staging.to_dict())
    for check in staging.checks:
        print(f"[{check.status.value.upper():4}] {check.name}: {check.detail}")
    print(f"Staging report: {staging_path}")
    print(f"Staging fingerprint: {staging.fingerprint_sha256}")
    print("FINAL RESULT: PASS" if not staging.failed else "FINAL RESULT: FAIL")

    return LiveBootstrapResult(False, staging.failed, preflight_path, staging_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Interactive Phase-15 live bootstrap. Secrets are held only in the process environment; "
            "the command first runs live preflight and proceeds to the read-only Google Ads staging "
            "validator only when every preflight FAIL is cleared."
        )
    )
    parser.add_argument("--start", required=True, help="Google Ads reporting start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Google Ads reporting end date YYYY-MM-DD")
    parser.add_argument("--business-truth", help="Path to user-confirmed Business Truth JSON")
    parser.add_argument("--conversion-lag-days", type=int)
    parser.add_argument("--gemini-sample-size", type=int, default=5)
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--no-replay-probe", action="store_true")
    parser.add_argument("--no-apply-migrations", action="store_true")
    parser.add_argument("--non-interactive", action="store_true", help="Never prompt; require all values in environment/arguments")
    parser.add_argument("--report-dir", default="phase15-live-reports")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.skip_analysis and args.conversion_lag_days is None:
        raise SystemExit("--conversion-lag-days is required unless --skip-analysis is used")
    try:
        result = run_live_bootstrap(args)
    except KeyboardInterrupt:
        print("Cancelled. No Google Ads mutation path exists in Phase 15.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Live bootstrap failed before completion: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
