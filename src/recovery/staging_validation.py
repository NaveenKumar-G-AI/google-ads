from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.db.canonical import canonical_payload, payload_sha256
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.db.sync_store import PostgresSyncStoreFactory
from recovery.google_ads import (
    GoogleAdsSyncEngine,
    GoogleAdsV26Adapter,
    ServiceAccountConfig,
    build_service_account_client,
)
from recovery.semantic_ai import CandidateSemanticAI, GeminiInteractionsTransport
from recovery.worker.analysis_job import ConservativeAnalysisJobRunner


PHASE15_SCHEMA_VERSION = 1
EXPECTED_MIGRATIONS = (
    "0001_phase8_core.sql",
    "0002_phase9_api_boundary.sql",
    "0003_phase10_worker_runtime.sql",
    "0004_phase13_shadow_release.sql",
    "0005_phase14_production_semantic_router.sql",
    "0006_phase16_dashboard_summary.sql",
)
PINNED_RUNTIME_PACKAGES = {
    "google-ads": "34.0.0",
    "psycopg": "3.3.6",
    "fastapi": "0.143.1",
    "uvicorn": "0.54.0",
    "PyJWT": "2.15.1",
    "google-genai": "2.31.0",
}


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    status: CheckStatus
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.detail.strip():
            raise ValueError("validation check name/detail are required")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    run_id: str
    started_at: datetime
    finished_at: datetime
    checks: tuple[ValidationCheck, ...]
    schema_version: int = PHASE15_SCHEMA_VERSION

    @property
    def failed(self) -> bool:
        return any(c.status is CheckStatus.FAIL for c in self.checks)

    @property
    def fingerprint_sha256(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "checks": [asdict(c) for c in self.checks],
        }
        return payload_sha256(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
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
class StagingConfig:
    database_url: str
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    customer_id: str
    start: date
    end: date
    conversion_lag_days: int | None = None
    business_truth_path: Path | None = None
    app_database_url: str | None = None
    apply_migrations: bool = False
    repeat_sync_probe: bool = True
    run_analysis: bool = True
    run_gemini: bool = True
    gemini_sample_size: int = 5
    report_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url is required")
        if not self.tenant_slug.strip() or not self.tenant_name.strip():
            raise ValueError("tenant slug/name are required")
        if self.start > self.end:
            raise ValueError("start must be <= end")
        if self.conversion_lag_days is not None and not (0 <= self.conversion_lag_days <= 365):
            raise ValueError("conversion_lag_days must be between 0 and 365")
        if self.gemini_sample_size < 1 or self.gemini_sample_size > 50:
            raise ValueError("gemini_sample_size must be between 1 and 50")
        if self.run_analysis and self.business_truth_path is None:
            raise ValueError("business_truth_path is required when run_analysis=True")
        if self.run_analysis and self.conversion_lag_days is None:
            raise ValueError("conversion_lag_days is required when run_analysis=True")
        if self.run_gemini and self.business_truth_path is None:
            raise ValueError("business_truth_path is required when run_gemini=True")


def redact_dsn(dsn: str) -> str:
    """Return a diagnostic DSN without password/query secrets."""
    try:
        parts = urlsplit(dsn)
        if parts.scheme not in {"postgresql", "postgres"}:
            return "<redacted-dsn>"
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        user = parts.username or ""
        auth = f"{user}:***@" if user else ""
        return urlunsplit((parts.scheme, f"{auth}{host}{port}", parts.path, "", ""))
    except Exception:
        return "<redacted-dsn>"


def _bundled_migration_hashes() -> dict[str, str]:
    root = resources.files("recovery.db.migrations")
    result: dict[str, str] = {}
    for name in EXPECTED_MIGRATIONS:
        p = root.joinpath(name)
        sql_text = p.read_text(encoding="utf-8")
        result[name] = payload_sha256({"filename": name, "sql": sql_text})
    return result


def _runtime_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for package in PINNED_RUNTIME_PACKAGES:
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = None
    return result


def verify_audit_chain_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[bool, str | None]:
    """Verify one aggregate's audit hash chain from database rows in chronological order."""
    previous: str | None = None
    for i, row in enumerate(rows):
        if row.get("previous_event_hash") != previous:
            return False, f"row {i} previous_event_hash mismatch"
        event_body = {
            "tenant_id": row["tenant_id"],
            "aggregate_type": row["aggregate_type"],
            "aggregate_id": row["aggregate_id"],
            "event_type": row["event_type"],
            "actor": row["actor"],
            "occurred_at": row["occurred_at"],
            "previous_event_hash": row.get("previous_event_hash"),
            "payload": canonical_payload(row["payload"]),
        }
        expected = payload_sha256(event_body)
        if row.get("event_hash") != expected:
            return False, f"row {i} event_hash mismatch"
        previous = expected
    return True, None


class Phase15StagingValidator:
    """Live staging validator. It intentionally contains no Google Ads mutate calls."""

    def __init__(self, config: StagingConfig) -> None:
        self.config = config
        self.repo = PostgresRecoveryRepository(config.database_url)
        self.run_id = f"phase15-{uuid4()}"
        self.checks: list[ValidationCheck] = []
        self.account_id: UUID | None = None
        self.sync_run_id: UUID | None = None
        self.truth_snapshot_id: UUID | None = None
        self.analysis_result: dict[str, Any] | None = None
        self.truth_snapshot: Any | None = None
        self.mutation_count_before: int | None = None

    def _check(self, name: str, status: CheckStatus, detail: str, **evidence: Any) -> None:
        self.checks.append(ValidationCheck(name, status, detail, evidence))

    def _safe(self, name: str, fn) -> Any | None:
        try:
            return fn()
        except Exception as exc:
            self._check(name, CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
            return None

    def run(self) -> ValidationReport:
        started = datetime.now(timezone.utc)
        self._runtime_probe()
        if self._database_probe():
            self._rls_probe()
            self._google_readonly_probe()
            if self.sync_run_id is not None:
                self._business_truth_and_analysis_probe()
                self._gemini_probe()
            self._audit_chain_probe()
            self._mutation_guard_probe()
        finished = datetime.now(timezone.utc)
        report = ValidationReport(self.run_id, started, finished, tuple(self.checks))
        if self.config.report_path is not None:
            self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.report_path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return report

    def _runtime_probe(self) -> None:
        versions = _runtime_versions()
        mismatches = {
            pkg: {"expected": expected, "actual": versions[pkg]}
            for pkg, expected in PINNED_RUNTIME_PACKAGES.items()
            if versions[pkg] != expected
        }
        if mismatches:
            self._check(
                "runtime_versions", CheckStatus.FAIL,
                "Staging must use the exact pinned runtime before external results are trusted.",
                mismatches=mismatches,
            )
        else:
            self._check("runtime_versions", CheckStatus.PASS, "All pinned runtime packages match.", versions=versions)

    def _database_probe(self) -> bool:
        try:
            with self.repo._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT current_database() AS database_name, current_user AS db_user,
                           current_setting('server_version') AS server_version,
                           EXISTS (SELECT 1 FROM pg_stat_ssl WHERE pid=pg_backend_pid() AND ssl) AS ssl_active
                    """
                )
                meta = dict(cur.fetchone())
            self._check(
                "postgres_connectivity", CheckStatus.PASS, "Connected to staging PostgreSQL.",
                dsn=redact_dsn(self.config.database_url), **meta,
            )
        except Exception as exc:
            self._check("postgres_connectivity", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
            return False

        if self.config.apply_migrations:
            try:
                applied = self.repo.apply_migrations()
                self._check(
                    "database_migrations_apply", CheckStatus.PASS,
                    "Bundled migrations applied or already present.", applied_now=list(applied),
                )
            except Exception as exc:
                self._check("database_migrations_apply", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
                return False
        else:
            self._check(
                "database_migrations_apply", CheckStatus.SKIP,
                "Migration application disabled; integrity is still checked read-only.",
            )

        expected = _bundled_migration_hashes()
        try:
            with self.repo._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT to_regclass('recovery.schema_migrations') AS relation")
                relation = cur.fetchone()["relation"]
                if relation is None:
                    raise RuntimeError("recovery.schema_migrations does not exist")
                cur.execute("SELECT version, sha256 FROM recovery.schema_migrations ORDER BY version")
                live = {str(r["version"]): str(r["sha256"]) for r in cur.fetchall()}
            missing = [x for x in EXPECTED_MIGRATIONS if x not in live]
            drift = [x for x in EXPECTED_MIGRATIONS if live.get(x) not in {None, expected[x]}]
            if missing or drift:
                self._check(
                    "migration_integrity", CheckStatus.FAIL,
                    "Staging migration history is incomplete or differs from bundled bytes.",
                    missing=missing, drift=drift,
                )
                return False
            self._check(
                "migration_integrity", CheckStatus.PASS,
                "All Phase 8–14 migration bytes match the live migration registry.",
                migrations=list(EXPECTED_MIGRATIONS),
            )
        except Exception as exc:
            self._check("migration_integrity", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
            return False

        try:
            with self.repo._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='recovery' AND c.relkind='r' AND c.relname <> 'schema_migrations'
                    ORDER BY c.relname
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
                missing_rls = [r["relname"] for r in rows if not (r["relrowsecurity"] and r["relforcerowsecurity"])]
                cur.execute(
                    """
                    SELECT tablename, policyname FROM pg_policies
                    WHERE schemaname='recovery' ORDER BY tablename, policyname
                    """
                )
                policies = [dict(r) for r in cur.fetchall()]
            if missing_rls:
                self._check(
                    "database_rls_catalog", CheckStatus.FAIL,
                    "One or more recovery tables are not FORCE RLS protected.", tables=missing_rls,
                )
            else:
                self._check(
                    "database_rls_catalog", CheckStatus.PASS,
                    "All recovery application tables have RLS enabled and forced.",
                    table_count=len(rows), policy_count=len(policies),
                )
        except Exception as exc:
            self._check("database_rls_catalog", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
            return False

        try:
            self.repo.ensure_tenant(
                tenant_id=self.config.tenant_id,
                slug=self.config.tenant_slug,
                display_name=self.config.tenant_name,
            )
            self._check(
                "staging_tenant", CheckStatus.PASS,
                "Staging tenant exists with the requested immutable identity.",
                tenant_id=str(self.config.tenant_id), slug=self.config.tenant_slug,
            )
            with self.repo._connect() as conn, conn.cursor() as cur:
                self.repo._set_tenant(cur, self.config.tenant_id)
                cur.execute("SELECT count(*) AS n FROM recovery.mutation_events WHERE tenant_id=%s", (self.config.tenant_id,))
                self.mutation_count_before = int(cur.fetchone()["n"])
        except Exception as exc:
            self._check("staging_tenant", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")
            return False
        return True

    def _rls_probe(self) -> None:
        if not self.config.app_database_url:
            self._check(
                "rls_behavior", CheckStatus.SKIP,
                "RECOVERY_STAGING_APP_DATABASE_URL not supplied; catalog RLS passed but behavioral app-role isolation was not executed.",
            )
            return
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.config.app_database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user"""
                )
                bypass = bool(cur.fetchone()["rolbypassrls"])
                if bypass:
                    raise RuntimeError("app validation role has BYPASSRLS; behavioral RLS test would be meaningless")
                cur.execute("SELECT set_config('recovery.tenant_id', %s, false)", (str(self.config.tenant_id),))
                cur.execute("SELECT count(*) AS n FROM recovery.tenants WHERE id=%s", (self.config.tenant_id,))
                visible = int(cur.fetchone()["n"])
                other = uuid4()
                cur.execute("SELECT set_config('recovery.tenant_id', %s, false)", (str(other),))
                cur.execute("SELECT count(*) AS n FROM recovery.tenants WHERE id=%s", (self.config.tenant_id,))
                hidden = int(cur.fetchone()["n"])
            if visible == 1 and hidden == 0:
                self._check(
                    "rls_behavior", CheckStatus.PASS,
                    "Non-BYPASSRLS app role sees the staging tenant only under matching tenant context.",
                )
            else:
                self._check(
                    "rls_behavior", CheckStatus.FAIL,
                    "Behavioral RLS isolation did not match expectations.", visible_under_match=visible,
                    visible_under_other_tenant=hidden,
                )
        except Exception as exc:
            self._check("rls_behavior", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _google_readonly_probe(self) -> None:
        required = ("GOOGLE_ADS_JSON_KEY_FILE_PATH",)
        missing = [x for x in required if not os.getenv(x, "").strip()]
        if missing:
            self._check(
                "google_ads_readonly_sync", CheckStatus.SKIP,
                "Google Ads credentials missing; live read-only account validation was not executed.", missing_env=missing,
            )
            return
        try:
            cfg = ServiceAccountConfig(
                json_key_file_path=os.environ["GOOGLE_ADS_JSON_KEY_FILE_PATH"],
                developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None,
                login_customer_id=os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None,
            )
            client = build_service_account_client(cfg)
            adapter = GoogleAdsV26Adapter(client)
            profile = adapter.get_customer_profile(self.config.customer_id)
            if profile.manager:
                raise RuntimeError("target customer is a manager account, not an advertiser")
            if profile.status.upper() != "ENABLED":
                raise RuntimeError(f"target customer status is {profile.status}, expected ENABLED")
            if self.config.end > profile.local_today():
                raise RuntimeError("requested sync end is in the advertiser account's future")
            request_id = f"{self.run_id}:sync"
            store_factory = PostgresSyncStoreFactory(
                repository=self.repo, tenant_id=self.config.tenant_id, request_id=request_id,
                credential_ref="phase15-staging-service-account",
            )
            engine = GoogleAdsSyncEngine(adapter, chunk_days=7)
            first = engine.sync(
                customer_id=self.config.customer_id, start=self.config.start, end=self.config.end,
                store_factory=store_factory,
            )
            with self.repo._connect() as conn, conn.cursor() as cur:
                self.repo._set_tenant(cur, self.config.tenant_id)
                cur.execute(
                    """
                    SELECT s.id AS sync_run_id, s.account_id,
                           (SELECT count(*) FROM recovery.search_term_version_occurrences o
                            JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                            WHERE o.tenant_id=s.tenant_id AND c.sync_run_id=s.id) AS term_occurrences,
                           (SELECT count(*) FROM recovery.campaign_spend_version_occurrences o
                            JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                            WHERE o.tenant_id=s.tenant_id AND c.sync_run_id=s.id) AS spend_occurrences
                    FROM recovery.sync_runs s WHERE s.tenant_id=%s AND s.request_id=%s
                    """,
                    (self.config.tenant_id, request_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("sync completed but sync_run was not persisted")
                self.sync_run_id = row["sync_run_id"]
                self.account_id = row["account_id"]
                before_counts = (int(row["term_occurrences"]), int(row["spend_occurrences"]))

            replay = None
            after_counts = before_counts
            if self.config.repeat_sync_probe:
                replay = engine.sync(
                    customer_id=self.config.customer_id, start=self.config.start, end=self.config.end,
                    store_factory=store_factory,
                )
                with self.repo._connect() as conn, conn.cursor() as cur:
                    self.repo._set_tenant(cur, self.config.tenant_id)
                    cur.execute(
                        """
                        SELECT
                          (SELECT count(*) FROM recovery.search_term_version_occurrences o
                           JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                           WHERE o.tenant_id=%s AND c.sync_run_id=%s) AS term_occurrences,
                          (SELECT count(*) FROM recovery.campaign_spend_version_occurrences o
                           JOIN recovery.sync_chunks c ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                           WHERE o.tenant_id=%s AND c.sync_run_id=%s) AS spend_occurrences
                        """,
                        (self.config.tenant_id, self.sync_run_id, self.config.tenant_id, self.sync_run_id),
                    )
                    rr = cur.fetchone()
                    after_counts = (int(rr["term_occurrences"]), int(rr["spend_occurrences"]))
                if replay.downloaded_chunks != 0 or replay.skipped_completed_chunks != replay.requested_chunks:
                    raise RuntimeError("same-request sync replay downloaded a supposedly completed chunk")
                if after_counts != before_counts:
                    raise RuntimeError("same-request sync replay duplicated persisted observations")

            self._check(
                "google_ads_readonly_sync", CheckStatus.PASS,
                "Real advertiser data synced read-only; replay of the same request was idempotent.",
                customer_id=profile.customer_id,
                descriptive_name=profile.descriptive_name,
                currency_code=profile.currency_code,
                time_zone=profile.time_zone,
                test_account=profile.test_account,
                requested_chunks=first.requested_chunks,
                downloaded_chunks=first.downloaded_chunks,
                term_occurrences=before_counts[0],
                campaign_spend_occurrences=before_counts[1],
                replay_verified=bool(replay is not None),
            )
        except Exception as exc:
            self._check("google_ads_readonly_sync", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _load_truth(self):
        assert self.config.business_truth_path is not None
        payload = json.loads(self.config.business_truth_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Business Truth JSON root must be an object")
        snapshot = parse_business_truth_payload(
            payload, submitted_by="phase15-staging-validator", submitted_at=datetime.now(timezone.utc)
        )
        return snapshot

    def _business_truth_and_analysis_probe(self) -> None:
        if not self.config.run_analysis:
            self._check("business_truth_analysis", CheckStatus.SKIP, "Analysis probe disabled.")
            return
        if self.account_id is None or self.sync_run_id is None:
            self._check("business_truth_analysis", CheckStatus.SKIP, "No completed live sync is available.")
            return
        try:
            truth = self._load_truth()
            self.truth_snapshot = truth
            truth_id = self.repo.save_business_truth_snapshot(
                tenant_id=self.config.tenant_id, account_id=self.account_id,
                snapshot=truth, created_by="phase15-staging-validator",
            )
            self.truth_snapshot_id = truth_id
            runner = ConservativeAnalysisJobRunner(self.repo)
            job_id = uuid4()
            result = runner(
                tenant_id=self.config.tenant_id,
                job_id=job_id,
                payload={
                    "account_id": str(self.account_id),
                    "sync_run_id": str(self.sync_run_id),
                    "truth_snapshot_id": str(truth_id),
                    "as_of": self.config.end.isoformat(),
                    "conversion_lag_days": int(self.config.conversion_lag_days),
                },
            )
            self.analysis_result = result
            self._check(
                "business_truth_analysis", CheckStatus.PASS,
                "User-supplied Business Truth replayed and deterministic analysis completed against the real sync.",
                truth_fingerprint=truth.fingerprint_sha256,
                truth_snapshot_id=str(truth_id),
                analysis_run_id=result["analysis_run_id"],
                queries=result["queries"],
                potential_candidates=result["potentially_avoidable"],
                review_required=result["review_required"],
                proposals=result["proposals"],
                coverage_band=result["coverage_band"],
            )
        except Exception as exc:
            self._check("business_truth_analysis", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _gemini_probe(self) -> None:
        if not self.config.run_gemini:
            self._check("gemini_shadow_sample", CheckStatus.SKIP, "Gemini staging probe disabled.")
            return
        if not os.getenv("GEMINI_API_KEY", "").strip():
            self._check(
                "gemini_shadow_sample", CheckStatus.SKIP,
                "GEMINI_API_KEY missing; live semantic provider validation was not executed.",
            )
            return
        if self.sync_run_id is None:
            self._check("gemini_shadow_sample", CheckStatus.SKIP, "No live sync exists for semantic sampling.")
            return
        try:
            truth = self.truth_snapshot or self._load_truth()
            self.truth_snapshot = truth
            with self.repo._connect() as conn, conn.cursor() as cur:
                self.repo._set_tenant(cur, self.config.tenant_id)
                cur.execute(
                    """
                    SELECT DISTINCT ON (v.raw_search_term) v.raw_search_term
                    FROM recovery.search_term_version_occurrences o
                    JOIN recovery.search_term_observation_versions v
                      ON v.tenant_id=o.tenant_id AND v.id=o.version_id
                    JOIN recovery.sync_chunks c
                      ON c.tenant_id=o.tenant_id AND c.id=o.sync_chunk_id
                    WHERE o.tenant_id=%s AND c.sync_run_id=%s
                    ORDER BY v.raw_search_term, v.id
                    LIMIT %s
                    """,
                    (self.config.tenant_id, self.sync_run_id, self.config.gemini_sample_size),
                )
                queries = tuple(str(r["raw_search_term"]) for r in cur.fetchall())
            if not queries:
                self._check(
                    "gemini_shadow_sample", CheckStatus.SKIP,
                    "Real sync contains no visible search terms; test accounts commonly have no serving data.",
                )
                return
            candidate = CandidateSemanticAI(transport=GeminiInteractionsTransport())
            result = candidate.interpret_many(queries, truth)
            if result.truth_fingerprint != truth.fingerprint_sha256:
                raise RuntimeError("Gemini semantic result truth fingerprint mismatch")
            if len(result.assessments) != len(queries):
                raise RuntimeError("Gemini semantic result count differs from sampled query count")
            self._check(
                "gemini_shadow_sample", CheckStatus.PASS,
                "Real Gemini structured semantic call succeeded on real search terms with the Phase-12 financial-input boundary.",
                sample_size=len(queries),
                provider=result.provider,
                model=result.model,
                provider_model_version=result.provider_model_version,
                request_id=result.request_id,
                candidate_contract_fingerprint=result.candidate_contract_fingerprint,
                total_tokens=result.usage.total_tokens,
                production_effect_allowed=False,
            )
        except Exception as exc:
            self._check("gemini_shadow_sample", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _audit_chain_probe(self) -> None:
        try:
            aggregate_id = self.run_id
            first = self.repo.append_audit_event(
                tenant_id=self.config.tenant_id, aggregate_type="phase15_staging_validation",
                aggregate_id=aggregate_id, event_type="validation_probe_started",
                actor="phase15-staging-validator", payload={"schema_version": PHASE15_SCHEMA_VERSION},
            )
            second = self.repo.append_audit_event(
                tenant_id=self.config.tenant_id, aggregate_type="phase15_staging_validation",
                aggregate_id=aggregate_id, event_type="validation_probe_finished",
                actor="phase15-staging-validator", payload={"previous_probe_hash": first},
            )
            with self.repo._connect() as conn, conn.cursor() as cur:
                self.repo._set_tenant(cur, self.config.tenant_id)
                cur.execute(
                    """
                    SELECT tenant_id, aggregate_type, aggregate_id, event_type, actor,
                           occurred_at, previous_event_hash, event_hash, payload
                    FROM recovery.audit_events
                    WHERE tenant_id=%s AND aggregate_type='phase15_staging_validation' AND aggregate_id=%s
                    ORDER BY occurred_at, id
                    """,
                    (self.config.tenant_id, aggregate_id),
                )
                rows = tuple(dict(r) for r in cur.fetchall())
            okay, reason = verify_audit_chain_rows(rows)
            if not okay or len(rows) != 2 or rows[-1]["event_hash"] != second:
                raise RuntimeError(reason or "unexpected staging audit-chain shape")
            self._check(
                "audit_chain", CheckStatus.PASS,
                "Live PostgreSQL audit hash chain verified from stored rows.",
                event_count=len(rows), final_event_hash=second,
            )
        except Exception as exc:
            self._check("audit_chain", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")

    def _mutation_guard_probe(self) -> None:
        try:
            with self.repo._connect() as conn, conn.cursor() as cur:
                self.repo._set_tenant(cur, self.config.tenant_id)
                cur.execute(
                    "SELECT count(*) AS n FROM recovery.mutation_events WHERE tenant_id=%s",
                    (self.config.tenant_id,),
                )
                mutation_count = int(cur.fetchone()["n"])
                if self.mutation_count_before is None:
                    raise RuntimeError("mutation baseline was not captured")
                if mutation_count != self.mutation_count_before:
                    raise RuntimeError(
                        f"mutation_events changed during Phase 15: before={self.mutation_count_before}, after={mutation_count}"
                    )
                # Prove one representative evidence table is append-only using a no-op UPDATE.
                cur.execute(
                    "SELECT id FROM recovery.audit_events WHERE tenant_id=%s ORDER BY occurred_at DESC LIMIT 1",
                    (self.config.tenant_id,),
                )
                target = cur.fetchone()
            append_only_verified = False
            if target is not None:
                try:
                    with self.repo._connect() as conn, conn.cursor() as cur:
                        self.repo._set_tenant(cur, self.config.tenant_id)
                        cur.execute(
                            "UPDATE recovery.audit_events SET event_type=event_type WHERE tenant_id=%s AND id=%s",
                            (self.config.tenant_id, target["id"]),
                        )
                except Exception as exc:
                    text = str(exc).casefold()
                    append_only_verified = "append-only" in text or "not permitted" in text
            if not append_only_verified:
                raise RuntimeError("append-only evidence trigger did not reject a no-op UPDATE")
            self._check(
                "mutation_guard", CheckStatus.PASS,
                "Staging harness contains no Google mutate path; immutable evidence trigger rejected UPDATE.",
                mutation_event_count_before=self.mutation_count_before,
                mutation_event_count_after=mutation_count,
                google_mutations_performed_by_phase15=0,
            )
        except Exception as exc:
            self._check("mutation_guard", CheckStatus.FAIL, f"{type(exc).__name__}: {exc}")


def _env(name: str, *, required: bool = True) -> str | None:
    value = os.getenv(name, "").strip()
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value or None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def build_config_from_args(args: argparse.Namespace) -> StagingConfig:
    truth_path = Path(args.business_truth).resolve() if args.business_truth else None
    report = Path(args.report).resolve() if args.report else None
    return StagingConfig(
        database_url=_env("RECOVERY_STAGING_DATABASE_URL") or "",
        app_database_url=_env("RECOVERY_STAGING_APP_DATABASE_URL", required=False),
        tenant_id=UUID(args.tenant_id or (_env("RECOVERY_STAGING_TENANT_ID") or "")),
        tenant_slug=args.tenant_slug or (_env("RECOVERY_STAGING_TENANT_SLUG") or ""),
        tenant_name=args.tenant_name or (_env("RECOVERY_STAGING_TENANT_NAME") or ""),
        customer_id=args.customer_id or (_env("RECOVERY_STAGING_CUSTOMER_ID") or ""),
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        conversion_lag_days=args.conversion_lag_days,
        business_truth_path=truth_path,
        apply_migrations=args.apply_migrations,
        repeat_sync_probe=not args.no_replay_probe,
        run_analysis=not args.skip_analysis,
        run_gemini=not args.skip_gemini,
        gemini_sample_size=args.gemini_sample_size,
        report_path=report,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase-15 read-only staging integration validator (never mutates Google Ads)"
    )
    parser.add_argument("--tenant-id")
    parser.add_argument("--tenant-slug")
    parser.add_argument("--tenant-name")
    parser.add_argument("--customer-id")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--business-truth", help="Path to user-confirmed Business Truth JSON")
    parser.add_argument("--conversion-lag-days", type=int)
    parser.add_argument("--apply-migrations", action="store_true")
    parser.add_argument("--skip-analysis", action="store_true")
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--no-replay-probe", action="store_true")
    parser.add_argument("--gemini-sample-size", type=int, default=5)
    parser.add_argument("--report", default="phase15-staging-report.json")
    args = parser.parse_args()

    if os.getenv("RECOVERY_PHASE15_READ_ONLY_ACK", "") != "READ_ONLY_ONLY":
        raise SystemExit(
            "Set RECOVERY_PHASE15_READ_ONLY_ACK=READ_ONLY_ONLY. Phase 15 intentionally has no Google Ads mutation path."
        )
    try:
        config = build_config_from_args(args)
        report = Phase15StagingValidator(config).run()
    except Exception as exc:
        raise SystemExit(f"Phase-15 configuration/startup failed: {type(exc).__name__}: {exc}") from exc

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    raise SystemExit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
