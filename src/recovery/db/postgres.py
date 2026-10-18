from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from uuid import UUID, uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # allows offline core tests; DB operations still fail explicitly
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

    class Jsonb:  # minimal placeholder used only when no DB call is made
        def __init__(self, value: Any) -> None:
            self.obj = value

from recovery.business_truth import BusinessTruthSnapshot
from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.evidence import observation_identity_sha256
from recovery.google_ads.adapter import GOOGLE_ADS_API_VERSION
from recovery.google_ads.sync import CustomerProfile, SYNC_SCHEMA_VERSION, SyncChunk
from recovery.negative_keywords import ApprovalRecord
from recovery.recovery_ledger import RecoveryLedgerSummary
from recovery.search_intent import normalize_query
from recovery.waste_intelligence import CampaignPerformanceSegmentObservation, UserLocationObservation
from recovery.monitoring import CampaignHealthObservation
from recovery.measurement_integrity import (
    ConversionActionObservation,CustomerConversionGoalObservation,CampaignConversionGoalObservation,
    CampaignGoalConfigObservation,ConversionLagObservation,
)

from .canonical import canonical_payload, payload_sha256
from .identity import (
    campaign_spend_identity_sha256,
    stable_chunk_payload,
    stable_inventory_payload,
)


class MigrationDriftError(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SyncRunHandle:
    sync_run_id: UUID
    account_id: UUID
    tenant_id: UUID
    request_id: str


@dataclass(frozen=True, slots=True)
class ChunkCommitResult:
    sync_chunk_id: UUID
    payload_sha256: str
    inserted_search_term_versions: int
    inserted_campaign_spend_versions: int
    already_committed: bool


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: UUID
    fingerprint: str
    already_present: bool


class PostgresRecoveryRepository:
    """Accuracy-first PostgreSQL repository.

    The repository deliberately uses explicit transactions and tenant context on every
    operation. Evidence/version tables are append-only in PostgreSQL itself; application
    code cannot silently update the facts behind an older financial claim.
    """

    def __init__(self, dsn: str, *, connect: Callable[..., Any] | None = None) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        if connect is None:
            if psycopg is None:
                raise RuntimeError(
                    'psycopg is not installed; install the project dependencies before using PostgreSQL'
                )
            connect = psycopg.connect
        self.dsn = dsn
        self._connect_fn = connect

    def _connect(self):
        return self._connect_fn(self.dsn, row_factory=dict_row)

    @staticmethod
    def _set_tenant(cur: Any, tenant_id: UUID) -> None:
        cur.execute("SELECT set_config('recovery.tenant_id', %s, true)", (str(tenant_id),))

    @staticmethod
    def _advisory_xact_lock(cur: Any, lock_key: str) -> None:
        # Transaction-scoped advisory locks disappear on commit/rollback and avoid
        # duplicate writers racing on the same logical operation.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))

    def apply_migrations(self) -> tuple[str, ...]:
        applied: list[str] = []
        migration_root = resources.files("recovery.db.migrations")
        files = sorted(
            (p for p in migration_root.iterdir() if p.name.endswith(".sql")),
            key=lambda p: p.name,
        )
        with self._connect() as conn:
            for migration in files:
                sql_text = migration.read_text(encoding="utf-8")
                digest = payload_sha256({"filename": migration.name, "sql": sql_text})
                with conn.transaction():
                    with conn.cursor() as cur:
                        # schema_migrations may not exist before the first migration.
                        cur.execute(
                            "SELECT to_regclass('recovery.schema_migrations') AS relation"
                        )
                        relation = cur.fetchone()["relation"]
                        existing = None
                        if relation is not None:
                            cur.execute(
                                "SELECT sha256 FROM recovery.schema_migrations WHERE version = %s",
                                (migration.name,),
                            )
                            existing = cur.fetchone()
                        if existing is not None:
                            if existing["sha256"] != digest:
                                raise MigrationDriftError(
                                    f"applied migration {migration.name} differs from bundled bytes"
                                )
                            continue
                        # Migrations are trusted package resources, not user input.
                        cur.execute(sql_text, prepare=False)
                        cur.execute(
                            "INSERT INTO recovery.schema_migrations(version, sha256) VALUES (%s, %s)",
                            (migration.name, digest),
                        )
                        applied.append(migration.name)
        return tuple(applied)

    def ensure_tenant(self, *, tenant_id: UUID, slug: str, display_name: str) -> None:
        if not slug.strip() or not display_name.strip():
            raise ValueError("tenant slug/display_name are required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.tenants(id, slug, display_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (tenant_id, slug.strip(), display_name.strip()),
                )
                cur.execute(
                    "SELECT slug, display_name FROM recovery.tenants WHERE id = %s",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("tenant insert/read failed under RLS")
                if row["slug"] != slug.strip() or row["display_name"] != display_name.strip():
                    raise IdempotencyConflict("tenant ID already exists with different identity")

    def upsert_google_ads_account(
        self,
        *,
        tenant_id: UUID,
        profile: CustomerProfile,
        credential_ref: str | None = None,
        credential_fingerprint: str | None = None,
    ) -> UUID:
        if credential_ref is not None and not credential_ref.strip():
            raise ValueError("credential_ref cannot be blank")
        if credential_fingerprint is not None:
            fp = credential_fingerprint.strip().lower()
            if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
                raise ValueError("credential_fingerprint must be SHA-256 hex")
            credential_fingerprint = fp
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.google_ads_accounts(
                        tenant_id, customer_id, descriptive_name, currency_code, time_zone,
                        manager, account_status, test_account, credential_ref, credential_fingerprint
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, customer_id) DO UPDATE SET
                        descriptive_name = EXCLUDED.descriptive_name,
                        manager = EXCLUDED.manager,
                        account_status = EXCLUDED.account_status,
                        test_account = EXCLUDED.test_account,
                        credential_ref = COALESCE(EXCLUDED.credential_ref, recovery.google_ads_accounts.credential_ref),
                        credential_fingerprint = COALESCE(EXCLUDED.credential_fingerprint, recovery.google_ads_accounts.credential_fingerprint),
                        updated_at = now()
                    RETURNING id, currency_code, time_zone
                    """,
                    (
                        tenant_id,
                        profile.customer_id,
                        profile.descriptive_name,
                        profile.currency_code,
                        profile.time_zone,
                        profile.manager,
                        profile.status,
                        profile.test_account,
                        credential_ref.strip() if credential_ref else None,
                        credential_fingerprint,
                    ),
                )
                row = cur.fetchone()
                if row["currency_code"] != profile.currency_code or row["time_zone"] != profile.time_zone:
                    raise IdempotencyConflict(
                        "stored immutable account currency/timezone differs from Google profile"
                    )
                return row["id"]

    def begin_sync_run(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        request_id: str,
        profile: CustomerProfile,
        start: date,
        end: date,
        api_version: str = GOOGLE_ADS_API_VERSION,
        sync_schema_version: int = SYNC_SCHEMA_VERSION,
    ) -> SyncRunHandle:
        if start > end:
            raise ValueError("sync start must be <= end")
        if not request_id.strip():
            raise ValueError("request_id is required for resumable idempotency")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                self._advisory_xact_lock(cur, f"sync-request:{tenant_id}:{request_id}")
                cur.execute(
                    "SELECT * FROM recovery.sync_runs WHERE tenant_id=%s AND request_id=%s",
                    (tenant_id, request_id),
                )
                existing = cur.fetchone()
                expected = {
                    "account_id": account_id,
                    "api_version": api_version,
                    "sync_schema_version": sync_schema_version,
                    "window_start": start,
                    "window_end": end,
                    "currency_code": profile.currency_code,
                    "time_zone": profile.time_zone,
                }
                if existing is not None:
                    for key, value in expected.items():
                        if existing[key] != value:
                            raise IdempotencyConflict(
                                f"sync request_id already exists with different {key}"
                            )
                    return SyncRunHandle(existing["id"], account_id, tenant_id, request_id)

                sync_run_id = uuid4()
                cur.execute(
                    """
                    INSERT INTO recovery.sync_runs(
                        id, tenant_id, account_id, request_id, api_version, sync_schema_version,
                        window_start, window_end, currency_code, time_zone, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running')
                    """,
                    (
                        sync_run_id,
                        tenant_id,
                        account_id,
                        request_id,
                        api_version,
                        sync_schema_version,
                        start,
                        end,
                        profile.currency_code,
                        profile.time_zone,
                    ),
                )
                return SyncRunHandle(sync_run_id, account_id, tenant_id, request_id)

    def chunk_complete(self, *, handle: SyncRunHandle, chunk: SyncChunk) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, handle.tenant_id)
                cur.execute(
                    """
                    SELECT status FROM recovery.sync_chunks
                    WHERE tenant_id=%s AND sync_run_id=%s AND chunk_start=%s AND chunk_end=%s
                    """,
                    (handle.tenant_id, handle.sync_run_id, chunk.start, chunk.end),
                )
                row = cur.fetchone()
                return row is not None and row["status"] == "completed"

    def commit_sync_chunk(
        self,
        *,
        handle: SyncRunHandle,
        chunk: SyncChunk,
        search_terms: Sequence[SearchTermObservation],
        campaign_spend: Sequence[CampaignSpendObservation],
        api_version: str = GOOGLE_ADS_API_VERSION,
        sync_schema_version: int = SYNC_SCHEMA_VERSION,
    ) -> ChunkCommitResult:
        envelope = stable_chunk_payload(
            api_version=api_version,
            sync_schema_version=sync_schema_version,
            chunk_start=chunk.start.isoformat(),
            chunk_end=chunk.end.isoformat(),
            search_terms=search_terms,
            campaign_spend=campaign_spend,
            currency_code=(search_terms[0].currency_code if search_terms else campaign_spend[0].currency_code if campaign_spend else "XXX"),
        ) if (search_terms or campaign_spend) else None

        # Empty chunks need the authoritative run currency, not a fabricated code.
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, handle.tenant_id)
                self._advisory_xact_lock(
                    cur,
                    f"sync-chunk:{handle.tenant_id}:{handle.sync_run_id}:{chunk.key}",
                )
                cur.execute(
                    """
                    SELECT sr.account_id, sr.currency_code, sr.api_version, sr.sync_schema_version,
                           a.customer_id, sr.window_start, sr.window_end
                    FROM recovery.sync_runs sr
                    JOIN recovery.google_ads_accounts a
                      ON a.tenant_id=sr.tenant_id AND a.id=sr.account_id
                    WHERE sr.tenant_id=%s AND sr.id=%s
                    """,
                    (handle.tenant_id, handle.sync_run_id),
                )
                run = cur.fetchone()
                if run is None:
                    raise ValueError("sync run does not exist")
                if run["api_version"] != api_version or run["sync_schema_version"] != sync_schema_version:
                    raise IdempotencyConflict("chunk writer version differs from sync run")
                currency_code = run["currency_code"]
                if envelope is None:
                    envelope = stable_chunk_payload(
                        api_version=api_version,
                        sync_schema_version=sync_schema_version,
                        chunk_start=chunk.start.isoformat(),
                        chunk_end=chunk.end.isoformat(),
                        search_terms=(),
                        campaign_spend=(),
                        currency_code=currency_code,
                    )
                elif envelope["currency_code"] != currency_code:
                    raise ValueError("chunk currency differs from sync-run currency")
                digest = payload_sha256(envelope)
                visible = envelope["coverage"]["visible_search_term_cost_micros"]
                comparable = envelope["coverage"]["comparable_campaign_cost_micros"]

                cur.execute(
                    """
                    SELECT id, status, payload_sha256 FROM recovery.sync_chunks
                    WHERE tenant_id=%s AND sync_run_id=%s AND chunk_start=%s AND chunk_end=%s
                    """,
                    (handle.tenant_id, handle.sync_run_id, chunk.start, chunk.end),
                )
                existing = cur.fetchone()
                if existing is not None and existing["status"] == "completed":
                    if existing["payload_sha256"] != digest:
                        raise IdempotencyConflict(
                            "completed chunk was retried with different source data; start a new sync run"
                        )
                    return ChunkCommitResult(existing["id"], digest, 0, 0, True)

                chunk_id = existing["id"] if existing else uuid4()
                if existing is None:
                    cur.execute(
                        """
                        INSERT INTO recovery.sync_chunks(
                            id, tenant_id, sync_run_id, chunk_start, chunk_end, status
                        ) VALUES (%s,%s,%s,%s,%s,'pending')
                        """,
                        (chunk_id, handle.tenant_id, handle.sync_run_id, chunk.start, chunk.end),
                    )

                inserted_search = 0
                for row in search_terms:
                    if row.customer_id != run["customer_id"]:
                        raise ValueError("search-term row customer differs from sync account")
                    identity = observation_identity_sha256(row)
                    key_id = self._ensure_search_term_key(
                        cur, handle, run["account_id"], row, identity
                    )
                    row_payload = canonical_payload(row)
                    row_digest = payload_sha256(row)
                    version_id, inserted = self._ensure_search_term_version(
                        cur, handle.tenant_id, key_id, row, row_digest, row_payload
                    )
                    inserted_search += int(inserted)
                    cur.execute(
                        """
                        INSERT INTO recovery.search_term_version_occurrences(
                            tenant_id, version_id, sync_chunk_id
                        ) VALUES (%s,%s,%s)
                        ON CONFLICT (tenant_id, version_id, sync_chunk_id) DO NOTHING
                        """,
                        (handle.tenant_id, version_id, chunk_id),
                    )

                inserted_campaign = 0
                for row in campaign_spend:
                    if row.customer_id != run["customer_id"]:
                        raise ValueError("campaign-spend row customer differs from sync account")
                    identity = campaign_spend_identity_sha256(row)
                    key_id = self._ensure_campaign_spend_key(
                        cur, handle, run["account_id"], row, identity
                    )
                    row_payload = canonical_payload(row)
                    row_digest = payload_sha256(row)
                    version_id, inserted = self._ensure_campaign_spend_version(
                        cur, handle.tenant_id, key_id, row, row_digest, row_payload
                    )
                    inserted_campaign += int(inserted)
                    cur.execute(
                        """
                        INSERT INTO recovery.campaign_spend_version_occurrences(
                            tenant_id, version_id, sync_chunk_id
                        ) VALUES (%s,%s,%s)
                        ON CONFLICT (tenant_id, version_id, sync_chunk_id) DO NOTHING
                        """,
                        (handle.tenant_id, version_id, chunk_id),
                    )

                cur.execute(
                    """
                    UPDATE recovery.sync_chunks SET
                        status='completed', payload_sha256=%s,
                        search_term_rows=%s, campaign_spend_rows=%s,
                        visible_search_term_cost_micros=%s,
                        comparable_campaign_cost_micros=%s,
                        committed_at=now(), failure_code=NULL, failure_detail=NULL
                    WHERE tenant_id=%s AND id=%s
                    """,
                    (
                        digest,
                        len(search_terms),
                        len(campaign_spend),
                        visible,
                        comparable,
                        handle.tenant_id,
                        chunk_id,
                    ),
                )
                return ChunkCommitResult(
                    chunk_id, digest, inserted_search, inserted_campaign, False
                )

    def commit_waste_dimension_chunk(
        self, *, handle: SyncRunHandle, chunk: SyncChunk,
        campaign_segments: Sequence[CampaignPerformanceSegmentObservation],
        user_locations: Sequence[UserLocationObservation],
    ) -> None:
        payload = {
            "schema_version": 1,
            "chunk": {"start": chunk.start.isoformat(), "end": chunk.end.isoformat()},
            "campaign_segments": [canonical_payload(x) for x in campaign_segments],
            "user_locations": [canonical_payload(x) for x in user_locations],
        }
        digest = payload_sha256(payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_tenant(cur, handle.tenant_id)
            self._advisory_xact_lock(cur, f"waste-dimension:{handle.tenant_id}:{handle.sync_run_id}:{chunk.key}")
            cur.execute(
                """SELECT sr.account_id,a.customer_id,sr.currency_code
                   FROM recovery.sync_runs sr JOIN recovery.google_ads_accounts a
                     ON a.tenant_id=sr.tenant_id AND a.id=sr.account_id
                   WHERE sr.tenant_id=%s AND sr.id=%s""",
                (handle.tenant_id,handle.sync_run_id),
            )
            run=cur.fetchone()
            if run is None:
                raise ValueError("sync run does not exist")
            cur.execute(
                """SELECT id,payload_sha256 FROM recovery.waste_dimension_chunks
                   WHERE tenant_id=%s AND sync_run_id=%s AND chunk_start=%s AND chunk_end=%s""",
                (handle.tenant_id,handle.sync_run_id,chunk.start,chunk.end),
            )
            existing=cur.fetchone()
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise IdempotencyConflict("waste-dimension chunk retried with different source data")
                return
            chunk_id=uuid4()
            cur.execute(
                """INSERT INTO recovery.waste_dimension_chunks(
                       id,tenant_id,sync_run_id,chunk_start,chunk_end,payload_sha256,campaign_segment_rows,user_location_rows
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (chunk_id,handle.tenant_id,handle.sync_run_id,chunk.start,chunk.end,digest,len(campaign_segments),len(user_locations)),
            )
            for row in campaign_segments:
                if row.customer_id != run["customer_id"] or row.currency_code.upper() != run["currency_code"]:
                    raise ValueError("campaign segment row differs from sync account/currency")
                identity=payload_sha256({
                    "customer_id":row.customer_id,"campaign_id":row.campaign_id,"date":row.date.isoformat(),
                    "network":row.network.upper(),"device":row.device.upper(),"day_of_week":row.day_of_week.upper(),"hour":row.hour,
                })
                cur.execute(
                    """INSERT INTO recovery.campaign_performance_segments(
                      tenant_id,account_id,sync_run_id,dimension_chunk_id,identity_sha256,customer_id,campaign_id,campaign_name,
                      observation_date,network,device,day_of_week,hour,impressions,clicks,cost_micros,conversions,
                      conversions_value,all_conversions,all_conversions_value,currency_code
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,chunk_id,identity,row.customer_id,row.campaign_id,row.campaign_name,
                     row.date,row.network.upper(),row.device.upper(),row.day_of_week.upper(),row.hour,row.impressions,row.clicks,row.cost_micros,
                     row.conversions,row.conversions_value,row.all_conversions,row.all_conversions_value,row.currency_code.upper()),
                )
            for row in user_locations:
                if row.customer_id != run["customer_id"] or row.currency_code.upper() != run["currency_code"]:
                    raise ValueError("user-location row differs from sync account/currency")
                identity=payload_sha256({
                    "customer_id":row.customer_id,"campaign_id":row.campaign_id,"date":row.date.isoformat(),
                    "network":row.network.upper(),"location_resource":row.location_resource,
                    "targeting_location":row.targeting_location,
                })
                cur.execute(
                    """INSERT INTO recovery.user_location_observations(
                      tenant_id,account_id,sync_run_id,dimension_chunk_id,identity_sha256,customer_id,campaign_id,campaign_name,
                      observation_date,network,targeting_location,country_criterion_id,location_resource,location_name,canonical_name,
                      country_code,target_type,impressions,clicks,cost_micros,conversions,conversions_value,all_conversions,all_conversions_value,currency_code
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,chunk_id,identity,row.customer_id,row.campaign_id,row.campaign_name,
                     row.date,row.network.upper(),row.targeting_location,row.country_criterion_id,row.location_resource,row.location_name,row.canonical_name,
                     row.country_code.upper() if row.country_code else None,row.target_type,row.impressions,row.clicks,row.cost_micros,row.conversions,
                     row.conversions_value,row.all_conversions,row.all_conversions_value,row.currency_code.upper()),
                )

    def commit_monitoring_snapshot(
        self, *, handle: SyncRunHandle, campaign_health: Sequence[CampaignHealthObservation]
    ) -> str:
        payload={
            "schema_version":1,
            "campaign_health":[canonical_payload(x) for x in campaign_health],
        }
        digest=payload_sha256(payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_tenant(cur,handle.tenant_id)
            self._advisory_xact_lock(cur,f"monitoring-snapshot:{handle.tenant_id}:{handle.sync_run_id}")
            cur.execute(
                """SELECT sr.account_id,a.customer_id FROM recovery.sync_runs sr
                   JOIN recovery.google_ads_accounts a ON a.tenant_id=sr.tenant_id AND a.id=sr.account_id
                   WHERE sr.tenant_id=%s AND sr.id=%s""",
                (handle.tenant_id,handle.sync_run_id),
            )
            run=cur.fetchone()
            if run is None:
                raise ValueError("sync run does not exist")
            cur.execute(
                "SELECT id,payload_sha256 FROM recovery.monitoring_snapshots WHERE tenant_id=%s AND sync_run_id=%s",
                (handle.tenant_id,handle.sync_run_id),
            )
            existing=cur.fetchone()
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise IdempotencyConflict("monitoring snapshot retried with different provider data")
                return digest
            for row in campaign_health:
                if row.customer_id != run["customer_id"]:
                    raise ValueError("campaign health row differs from sync account")
            snapshot_id=uuid4()
            cur.execute(
                """INSERT INTO recovery.monitoring_snapshots(
                     id,tenant_id,account_id,sync_run_id,payload_sha256,campaign_health_rows
                   ) VALUES (%s,%s,%s,%s,%s,%s)""",
                (snapshot_id,handle.tenant_id,run["account_id"],handle.sync_run_id,digest,len(campaign_health)),
            )
            for row in campaign_health:
                identity=payload_sha256({"campaign_id":row.campaign_id})
                cur.execute(
                    """INSERT INTO recovery.campaign_health_observations(
                      tenant_id,account_id,sync_run_id,monitoring_snapshot_id,identity_sha256,customer_id,campaign_id,campaign_name,
                      advertising_channel_type,status,primary_status,primary_status_reasons
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.campaign_id,row.campaign_name,
                     row.advertising_channel_type.upper(),row.status.upper(),row.primary_status.upper(),Jsonb(list(row.primary_status_reasons))),
                )
        return digest

    def commit_measurement_snapshot(
        self, *, handle: SyncRunHandle,
        conversion_actions: Sequence[ConversionActionObservation],
        customer_goals: Sequence[CustomerConversionGoalObservation],
        campaign_goals: Sequence[CampaignConversionGoalObservation],
        campaign_goal_configs: Sequence[CampaignGoalConfigObservation],
        lag_observations: Sequence[ConversionLagObservation],
    ) -> str:
        payload={
            "schema_version":1,
            "conversion_actions":[canonical_payload(x) for x in conversion_actions],
            "customer_goals":[canonical_payload(x) for x in customer_goals],
            "campaign_goals":[canonical_payload(x) for x in campaign_goals],
            "campaign_goal_configs":[canonical_payload(x) for x in campaign_goal_configs],
            "lag_observations":[canonical_payload(x) for x in lag_observations],
        }
        digest=payload_sha256(payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_tenant(cur,handle.tenant_id)
            self._advisory_xact_lock(cur,f"measurement:{handle.tenant_id}:{handle.sync_run_id}")
            cur.execute(
                """SELECT sr.account_id,a.customer_id FROM recovery.sync_runs sr
                   JOIN recovery.google_ads_accounts a ON a.tenant_id=sr.tenant_id AND a.id=sr.account_id
                   WHERE sr.tenant_id=%s AND sr.id=%s""",
                (handle.tenant_id,handle.sync_run_id),
            )
            run=cur.fetchone()
            if run is None:
                raise ValueError("sync run does not exist")
            cur.execute(
                "SELECT id,payload_sha256 FROM recovery.measurement_snapshots WHERE tenant_id=%s AND sync_run_id=%s",
                (handle.tenant_id,handle.sync_run_id),
            )
            existing=cur.fetchone()
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise IdempotencyConflict("measurement snapshot retried with different provider data")
                return digest
            for row in (*conversion_actions,*customer_goals,*campaign_goals,*campaign_goal_configs,*lag_observations):
                if row.customer_id != run["customer_id"]:
                    raise ValueError("measurement row differs from sync account")
            snapshot_id=uuid4()
            cur.execute(
                """INSERT INTO recovery.measurement_snapshots(
                     id,tenant_id,account_id,sync_run_id,payload_sha256,conversion_action_rows,customer_goal_rows,
                     campaign_goal_rows,campaign_goal_config_rows,conversion_lag_rows
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (snapshot_id,handle.tenant_id,run["account_id"],handle.sync_run_id,digest,len(conversion_actions),len(customer_goals),
                 len(campaign_goals),len(campaign_goal_configs),len(lag_observations)),
            )
            for row in conversion_actions:
                identity=payload_sha256({"resource_name":row.resource_name})
                cur.execute(
                    """INSERT INTO recovery.conversion_action_observations(
                      tenant_id,account_id,sync_run_id,measurement_snapshot_id,identity_sha256,customer_id,resource_name,action_id,name,
                      status,action_type,category,origin,owner_customer,primary_for_goal,counting_type,click_through_lookback_days,
                      view_through_lookback_days,attribution_model,data_driven_model_status,default_value,default_currency_code,
                      always_use_default_value,all_conversions,all_conversions_value,last_conversion_date,last_received_request_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.resource_name,row.action_id,row.name,
                     row.status.upper(),row.action_type.upper(),row.category.upper(),row.origin.upper(),row.owner_customer,row.primary_for_goal,row.counting_type.upper(),
                     row.click_through_lookback_days,row.view_through_lookback_days,row.attribution_model.upper(),row.data_driven_model_status.upper(),row.default_value,
                     row.default_currency_code.upper() if row.default_currency_code else None,row.always_use_default_value,row.all_conversions,row.all_conversions_value,
                     row.last_conversion_date,row.last_received_request_at),
                )
            for row in customer_goals:
                identity=payload_sha256({"resource_name":row.resource_name})
                cur.execute(
                    """INSERT INTO recovery.customer_conversion_goal_observations(
                      tenant_id,account_id,sync_run_id,measurement_snapshot_id,identity_sha256,customer_id,resource_name,category,origin,biddable
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.resource_name,row.category.upper(),row.origin.upper(),row.biddable),
                )
            for row in campaign_goals:
                identity=payload_sha256({"resource_name":row.resource_name})
                cur.execute(
                    """INSERT INTO recovery.campaign_conversion_goal_observations(
                      tenant_id,account_id,sync_run_id,measurement_snapshot_id,identity_sha256,customer_id,campaign_id,campaign_name,campaign_status,
                      resource_name,category,origin,biddable
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.campaign_id,row.campaign_name,row.campaign_status.upper(),
                     row.resource_name,row.category.upper(),row.origin.upper(),row.biddable),
                )
            for row in campaign_goal_configs:
                identity=payload_sha256({"resource_name":row.resource_name})
                cur.execute(
                    """INSERT INTO recovery.campaign_goal_config_observations(
                      tenant_id,account_id,sync_run_id,measurement_snapshot_id,identity_sha256,customer_id,campaign_id,campaign_name,campaign_status,
                      resource_name,goal_config_level,custom_conversion_goal
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.campaign_id,row.campaign_name,row.campaign_status.upper(),
                     row.resource_name,row.goal_config_level.upper(),row.custom_conversion_goal),
                )
            for row in lag_observations:
                identity=payload_sha256({"conversion_action_resource":row.conversion_action_resource,"lag_bucket":row.lag_bucket.upper()})
                cur.execute(
                    """INSERT INTO recovery.conversion_lag_observations(
                      tenant_id,account_id,sync_run_id,measurement_snapshot_id,identity_sha256,customer_id,conversion_action_resource,
                      conversion_action_name,category,lag_bucket,conversions,all_conversions,conversions_value,all_conversions_value
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (handle.tenant_id,run["account_id"],handle.sync_run_id,snapshot_id,identity,row.customer_id,row.conversion_action_resource,
                     row.conversion_action_name,row.category.upper(),row.lag_bucket.upper(),row.conversions,row.all_conversions,row.conversions_value,row.all_conversions_value),
                )
        return digest

    def _ensure_search_term_key(
        self,
        cur: Any,
        handle: SyncRunHandle,
        account_id: UUID,
        row: SearchTermObservation,
        identity: str,
    ) -> UUID:
        key_id = uuid4()
        cur.execute(
            """
            INSERT INTO recovery.search_term_observation_keys(
                id, tenant_id, account_id, identity_sha256, customer_id, campaign_id,
                ad_group_id, normalized_query, observation_date, network, match_source,
                search_term_match_type, targeting_status, triggering_keyword,
                triggering_keyword_match_type
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, account_id, identity_sha256) DO NOTHING
            RETURNING id
            """,
            (
                key_id,
                handle.tenant_id,
                account_id,
                identity,
                row.customer_id,
                row.campaign_id,
                row.ad_group_id,
                normalize_query(row.search_term),
                row.date,
                row.network.upper(),
                row.match_source.upper(),
                row.search_term_match_type.upper(),
                row.targeting_status.upper(),
                row.triggering_keyword,
                row.triggering_keyword_match_type.upper() if row.triggering_keyword_match_type else None,
            ),
        )
        inserted = cur.fetchone()
        if inserted:
            return inserted["id"]
        cur.execute(
            """
            SELECT id, customer_id, campaign_id, ad_group_id, normalized_query,
                   observation_date, network, match_source, search_term_match_type,
                   targeting_status, triggering_keyword, triggering_keyword_match_type
            FROM recovery.search_term_observation_keys
            WHERE tenant_id=%s AND account_id=%s AND identity_sha256=%s
            """,
            (handle.tenant_id, account_id, identity),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("search-term key conflict could not be resolved")
        expected = (
            row.customer_id,
            row.campaign_id,
            row.ad_group_id,
            normalize_query(row.search_term),
            row.date,
            row.network.upper(),
            row.match_source.upper(),
            row.search_term_match_type.upper(),
            row.targeting_status.upper(),
            row.triggering_keyword,
            row.triggering_keyword_match_type.upper() if row.triggering_keyword_match_type else None,
        )
        actual = tuple(existing[k] for k in (
            "customer_id","campaign_id","ad_group_id","normalized_query","observation_date",
            "network","match_source","search_term_match_type","targeting_status",
            "triggering_keyword","triggering_keyword_match_type"
        ))
        if actual != expected:
            raise IdempotencyConflict("search-term identity hash collision/inconsistent identity")
        return existing["id"]

    def _ensure_search_term_version(
        self,
        cur: Any,
        tenant_id: UUID,
        key_id: UUID,
        row: SearchTermObservation,
        digest: str,
        payload: dict,
    ) -> tuple[UUID, bool]:
        version_id = uuid4()
        cur.execute(
            """
            INSERT INTO recovery.search_term_observation_versions(
                id, tenant_id, observation_key_id, payload_sha256, campaign_name,
                ad_group_name, raw_search_term, impressions, clicks, cost_micros,
                conversions, conversions_value, all_conversions, all_conversions_value,
                currency_code, payload
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, observation_key_id, payload_sha256) DO NOTHING
            RETURNING id
            """,
            (
                version_id, tenant_id, key_id, digest, row.campaign_name, row.ad_group_name,
                row.search_term, row.impressions, row.clicks, row.cost_micros,
                row.conversions, row.conversions_value, row.all_conversions,
                row.all_conversions_value, row.currency_code.upper(), Jsonb(payload),
            ),
        )
        inserted = cur.fetchone()
        if inserted:
            return inserted["id"], True
        cur.execute(
            """
            SELECT id FROM recovery.search_term_observation_versions
            WHERE tenant_id=%s AND observation_key_id=%s AND payload_sha256=%s
            """,
            (tenant_id, key_id, digest),
        )
        return cur.fetchone()["id"], False

    def _ensure_campaign_spend_key(
        self,
        cur: Any,
        handle: SyncRunHandle,
        account_id: UUID,
        row: CampaignSpendObservation,
        identity: str,
    ) -> UUID:
        key_id = uuid4()
        cur.execute(
            """
            INSERT INTO recovery.campaign_spend_observation_keys(
                id, tenant_id, account_id, identity_sha256, customer_id, campaign_id,
                observation_date, network
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, account_id, identity_sha256) DO NOTHING
            RETURNING id
            """,
            (
                key_id, handle.tenant_id, account_id, identity, row.customer_id,
                row.campaign_id, row.date, row.network.upper(),
            ),
        )
        inserted = cur.fetchone()
        if inserted:
            return inserted["id"]
        cur.execute(
            """
            SELECT id, customer_id, campaign_id, observation_date, network
            FROM recovery.campaign_spend_observation_keys
            WHERE tenant_id=%s AND account_id=%s AND identity_sha256=%s
            """,
            (handle.tenant_id, account_id, identity),
        )
        existing = cur.fetchone()
        expected = (row.customer_id, row.campaign_id, row.date, row.network.upper())
        actual = tuple(existing[k] for k in ("customer_id","campaign_id","observation_date","network"))
        if actual != expected:
            raise IdempotencyConflict("campaign-spend identity hash collision/inconsistent identity")
        return existing["id"]

    def _ensure_campaign_spend_version(
        self,
        cur: Any,
        tenant_id: UUID,
        key_id: UUID,
        row: CampaignSpendObservation,
        digest: str,
        payload: dict,
    ) -> tuple[UUID, bool]:
        version_id = uuid4()
        cur.execute(
            """
            INSERT INTO recovery.campaign_spend_observation_versions(
                id, tenant_id, observation_key_id, payload_sha256, campaign_name,
                cost_micros, currency_code, payload
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, observation_key_id, payload_sha256) DO NOTHING
            RETURNING id
            """,
            (
                version_id, tenant_id, key_id, digest, row.campaign_name,
                row.cost_micros, row.currency_code.upper(), Jsonb(payload),
            ),
        )
        inserted = cur.fetchone()
        if inserted:
            return inserted["id"], True
        cur.execute(
            """
            SELECT id FROM recovery.campaign_spend_observation_versions
            WHERE tenant_id=%s AND observation_key_id=%s AND payload_sha256=%s
            """,
            (tenant_id, key_id, digest),
        )
        return cur.fetchone()["id"], False

    def commit_inventory_snapshot(
        self,
        *,
        handle: SyncRunHandle,
        positive_keywords: Sequence[Any],
        existing_negatives: Sequence[Any],
        api_version: str = GOOGLE_ADS_API_VERSION,
        sync_schema_version: int = SYNC_SCHEMA_VERSION,
    ) -> str:
        payload = stable_inventory_payload(
            api_version=api_version,
            sync_schema_version=sync_schema_version,
            positive_keywords=positive_keywords,
            existing_negatives=existing_negatives,
        )
        digest = payload_sha256(payload)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, handle.tenant_id)
                self._advisory_xact_lock(cur, f"inventory:{handle.tenant_id}:{handle.sync_run_id}")
                cur.execute(
                    "SELECT window_start, window_end, status FROM recovery.sync_runs WHERE tenant_id=%s AND id=%s",
                    (handle.tenant_id, handle.sync_run_id),
                )
                run = cur.fetchone()
                if run is None:
                    raise ValueError("sync run does not exist")
                cur.execute(
                    """
                    SELECT chunk_start, chunk_end, status FROM recovery.sync_chunks
                    WHERE tenant_id=%s AND sync_run_id=%s
                    ORDER BY chunk_start, chunk_end
                    """,
                    (handle.tenant_id, handle.sync_run_id),
                )
                chunks = cur.fetchall()
                cursor_date = run["window_start"]
                if not chunks:
                    raise IdempotencyConflict("sync cannot complete without committed chunks")
                for item in chunks:
                    if item["status"] != "completed":
                        raise IdempotencyConflict("sync cannot complete while a chunk is incomplete")
                    if item["chunk_start"] != cursor_date:
                        raise IdempotencyConflict("sync chunks do not cover the requested window contiguously")
                    cursor_date = item["chunk_end"] + timedelta(days=1)
                if cursor_date != run["window_end"] + timedelta(days=1):
                    raise IdempotencyConflict("sync chunks do not cover the requested window end")
                cur.execute(
                    "SELECT payload_sha256 FROM recovery.keyword_inventory_snapshots WHERE tenant_id=%s AND sync_run_id=%s",
                    (handle.tenant_id, handle.sync_run_id),
                )
                existing = cur.fetchone()
                if existing:
                    if existing["payload_sha256"] != digest:
                        raise IdempotencyConflict(
                            "inventory changed during the same sync run; start a new sync run"
                        )
                else:
                    cur.execute(
                        """
                        INSERT INTO recovery.keyword_inventory_snapshots(
                            tenant_id, sync_run_id, payload_sha256, positive_keyword_rows,
                            negative_keyword_rows, payload
                        ) VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            handle.tenant_id, handle.sync_run_id, digest,
                            len(positive_keywords), len(existing_negatives), Jsonb(payload),
                        ),
                    )
                cur.execute(
                    """
                    UPDATE recovery.sync_runs SET status='completed', completed_at=COALESCE(completed_at, now()),
                        failure_code=NULL, failure_detail=NULL
                    WHERE tenant_id=%s AND id=%s AND status <> 'failed'
                    """,
                    (handle.tenant_id, handle.sync_run_id),
                )
        return digest

    def save_business_truth_snapshot(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        snapshot: BusinessTruthSnapshot,
        created_by: str,
    ) -> UUID:
        if not created_by.strip():
            raise ValueError("created_by is required")
        payload = canonical_payload(snapshot)
        digest = payload_sha256(snapshot)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.business_truth_snapshots(
                        tenant_id, account_id, truth_fingerprint, schema_version, payload_sha256,
                        payload, created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, truth_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, account_id, snapshot.fingerprint_sha256, snapshot.schema_version,
                        digest, Jsonb(payload), created_by.strip(),
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    return inserted["id"]
                cur.execute(
                    """
                    SELECT id, payload_sha256 FROM recovery.business_truth_snapshots
                    WHERE tenant_id=%s AND account_id=%s AND truth_fingerprint=%s
                    """,
                    (tenant_id, account_id, snapshot.fingerprint_sha256),
                )
                existing = cur.fetchone()
                if existing["payload_sha256"] != digest:
                    raise IdempotencyConflict("truth fingerprint maps to different payload")
                return existing["id"]

    def begin_analysis_run(
        self,
        *,
        tenant_id: UUID,
        request_id: str,
        account_id: UUID,
        sync_run_id: UUID,
        truth_snapshot_id: UUID,
        as_of: date,
        engine_versions: dict[str, str],
    ) -> UUID:
        if not request_id.strip() or not engine_versions:
            raise ValueError("analysis request_id and engine_versions are required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                self._advisory_xact_lock(cur, f"analysis-request:{tenant_id}:{request_id}")
                cur.execute(
                    "SELECT * FROM recovery.analysis_runs WHERE tenant_id=%s AND request_id=%s",
                    (tenant_id, request_id),
                )
                existing = cur.fetchone()
                if existing:
                    expected = (account_id, sync_run_id, truth_snapshot_id, as_of, engine_versions)
                    actual = (
                        existing["account_id"], existing["sync_run_id"],
                        existing["truth_snapshot_id"], existing["as_of"], existing["engine_versions"]
                    )
                    if actual != expected:
                        raise IdempotencyConflict("analysis request_id reused with different inputs")
                    return existing["id"]
                run_id = uuid4()
                cur.execute(
                    """
                    INSERT INTO recovery.analysis_runs(
                        id, tenant_id, request_id, account_id, sync_run_id, truth_snapshot_id,
                        as_of, engine_versions, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'running')
                    """,
                    (
                        run_id, tenant_id, request_id, account_id, sync_run_id,
                        truth_snapshot_id, as_of, Jsonb(engine_versions),
                    ),
                )
                return run_id

    def save_analysis_artifact(
        self,
        *,
        tenant_id: UUID,
        analysis_run_id: UUID,
        artifact_kind: str,
        external_id: str,
        value: Any,
        truth_fingerprint: str | None = None,
        currency_code: str | None = None,
        money_micros: int | None = None,
    ) -> ArtifactRef:
        if not external_id.strip():
            raise ValueError("artifact external_id is required")
        payload = canonical_payload(value)
        fingerprint = getattr(value, "fingerprint_sha256", None) or payload_sha256(value)
        schema_version = int(getattr(value, "schema_version", 1))
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.analysis_artifacts(
                        tenant_id, analysis_run_id, artifact_kind, external_id,
                        artifact_fingerprint, schema_version, truth_fingerprint,
                        currency_code, money_micros, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, analysis_run_id, artifact_kind, external_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, analysis_run_id, artifact_kind, external_id.strip(),
                        fingerprint, schema_version, truth_fingerprint,
                        currency_code.upper() if currency_code else None,
                        money_micros, Jsonb(payload),
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    return ArtifactRef(inserted["id"], fingerprint, False)
                cur.execute(
                    """
                    SELECT id, artifact_fingerprint FROM recovery.analysis_artifacts
                    WHERE tenant_id=%s AND analysis_run_id=%s AND artifact_kind=%s AND external_id=%s
                    """,
                    (tenant_id, analysis_run_id, artifact_kind, external_id.strip()),
                )
                existing = cur.fetchone()
                if existing["artifact_fingerprint"] != fingerprint:
                    raise IdempotencyConflict(
                        "analysis artifact external_id reused for a different result"
                    )
                return ArtifactRef(existing["id"], fingerprint, True)

    def save_analysis_summary(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        analysis_run_id: UUID,
        summary: dict[str, Any],
    ) -> UUID:
        required = {
            "currency_code", "potentially_avoidable_observed_micros",
            "visible_search_term_micros", "unobserved_search_micros", "coverage_band",
            "query_count", "irrelevant_count", "review_required_count", "proposal_count",
            "ai_routed_count", "baseline_fallback_count", "semantic_interpreter",
        }
        missing = sorted(required.difference(summary))
        if missing:
            raise ValueError(f"analysis summary missing fields: {', '.join(missing)}")
        payload = canonical_payload(summary)
        fingerprint = payload_sha256(payload)
        with self._connect() as conn, conn.cursor() as cur:
            self._set_tenant(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO recovery.analysis_summaries(
                    tenant_id, account_id, analysis_run_id, currency_code,
                    potentially_avoidable_observed_micros, visible_search_term_micros,
                    unobserved_search_micros, coverage_band, query_count, irrelevant_count,
                    review_required_count, proposal_count, ai_routed_count,
                    baseline_fallback_count, semantic_interpreter, summary_fingerprint, payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, analysis_run_id) DO NOTHING
                RETURNING id
                """,
                (
                    tenant_id, account_id, analysis_run_id, str(summary["currency_code"]).upper(),
                    int(summary["potentially_avoidable_observed_micros"]),
                    int(summary["visible_search_term_micros"]), int(summary["unobserved_search_micros"]),
                    str(summary["coverage_band"]), int(summary["query_count"]),
                    int(summary["irrelevant_count"]), int(summary["review_required_count"]),
                    int(summary["proposal_count"]), int(summary["ai_routed_count"]),
                    int(summary["baseline_fallback_count"]), str(summary["semantic_interpreter"]),
                    fingerprint, Jsonb(payload),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                return row["id"]
            cur.execute(
                """
                SELECT id, summary_fingerprint FROM recovery.analysis_summaries
                WHERE tenant_id=%s AND analysis_run_id=%s
                """,
                (tenant_id, analysis_run_id),
            )
            existing = cur.fetchone()
            if existing is None or existing["summary_fingerprint"] != fingerprint:
                raise IdempotencyConflict("analysis summary changed for the same analysis run")
            return existing["id"]

    def record_approval(
        self,
        *,
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        approval: ApprovalRecord,
        note: str | None = None,
    ) -> UUID:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    SELECT artifact_kind, external_id, artifact_fingerprint
                    FROM recovery.analysis_artifacts
                    WHERE tenant_id=%s AND id=%s
                    """,
                    (tenant_id, proposal_artifact_id),
                )
                proposal = cur.fetchone()
                if proposal is None:
                    raise ValueError("proposal artifact does not exist")
                if proposal["artifact_kind"] != "negative_keyword_proposal":
                    raise ValueError("approval can only target a negative-keyword proposal")
                if proposal["external_id"] != approval.proposal_id:
                    raise IdempotencyConflict("approval proposal_id differs from stored proposal")
                if proposal["artifact_fingerprint"] != approval.proposal_fingerprint:
                    raise IdempotencyConflict("approval fingerprint differs from stored proposal")
        payload = {
            "proposal_id": approval.proposal_id,
            "proposal_fingerprint": approval.proposal_fingerprint,
            "decision": "approved",
            "decided_by": approval.approved_by,
            "decided_at": approval.approved_at,
            "note": note,
        }
        event_fp = payload_sha256(payload)
        return self._insert_proposal_decision(
            tenant_id=tenant_id,
            proposal_artifact_id=proposal_artifact_id,
            proposal_fingerprint=approval.proposal_fingerprint,
            decision="approved",
            decided_by=approval.approved_by,
            decided_at=approval.approved_at,
            note=note,
            event_fingerprint=event_fp,
            payload=payload,
        )

    def _insert_proposal_decision(
        self,
        *,
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        proposal_fingerprint: str,
        decision: str,
        decided_by: str,
        decided_at: datetime,
        note: str | None,
        event_fingerprint: str,
        payload: Any,
    ) -> UUID:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.proposal_decision_events(
                        tenant_id, proposal_artifact_id, proposal_fingerprint, decision,
                        decided_by, decided_at, note, event_fingerprint, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, event_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, proposal_artifact_id, proposal_fingerprint, decision,
                        decided_by, decided_at, note, event_fingerprint,
                        Jsonb(canonical_payload(payload)),
                    ),
                )
                row = cur.fetchone()
                if row:
                    return row["id"]
                cur.execute(
                    "SELECT id FROM recovery.proposal_decision_events WHERE tenant_id=%s AND event_fingerprint=%s",
                    (tenant_id, event_fingerprint),
                )
                return cur.fetchone()["id"]

    def record_mutation_event(
        self,
        *,
        tenant_id: UUID,
        proposal_artifact_id: UUID,
        approval_event_id: UUID,
        event_type: str,
        resource_name: str | None,
        api_request_id: str | None,
        actor: str,
        occurred_at: datetime,
        payload: Any,
    ) -> UUID:
        if event_type in {"applied", "rolled_back"} and not (resource_name and resource_name.strip()):
            raise ValueError(f"{event_type} mutation event requires resource_name")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    SELECT decision, proposal_artifact_id FROM recovery.proposal_decision_events
                    WHERE tenant_id=%s AND id=%s
                    """,
                    (tenant_id, approval_event_id),
                )
                approval = cur.fetchone()
                if approval is None:
                    raise ValueError("approval event does not exist")
                if approval["decision"] != "approved":
                    raise ValueError("mutation requires an approved proposal decision")
                if approval["proposal_artifact_id"] != proposal_artifact_id:
                    raise IdempotencyConflict("mutation proposal differs from approval proposal")
        body = {
            "proposal_artifact_id": proposal_artifact_id,
            "approval_event_id": approval_event_id,
            "event_type": event_type,
            "resource_name": resource_name,
            "api_request_id": api_request_id,
            "actor": actor,
            "occurred_at": occurred_at,
            "payload": canonical_payload(payload),
        }
        event_fp = payload_sha256(body)
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.mutation_events(
                        tenant_id, proposal_artifact_id, approval_event_id, event_type,
                        resource_name, api_request_id, actor, occurred_at,
                        event_fingerprint, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, event_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, proposal_artifact_id, approval_event_id, event_type,
                        resource_name, api_request_id, actor, occurred_at, event_fp,
                        Jsonb(body),
                    ),
                )
                row = cur.fetchone()
                if row:
                    return row["id"]
                cur.execute(
                    "SELECT id FROM recovery.mutation_events WHERE tenant_id=%s AND event_fingerprint=%s",
                    (tenant_id, event_fp),
                )
                return cur.fetchone()["id"]

    def record_recovery_ledger(
        self,
        *,
        tenant_id: UUID,
        analysis_run_id: UUID,
        summary: RecoveryLedgerSummary,
        mutation_event_id: UUID | None = None,
    ) -> UUID:
        payload = canonical_payload(summary)
        # A summary fingerprint alone is not case identity. Two independent mutations can
        # legitimately have identical monetary summaries. Bind persisted ledger identity to
        # the exact mutation event whenever one exists so recovery evidence cannot collide
        # across cases from the same analysis run.
        ledger_fingerprint = (
            payload_sha256({"summary_fingerprint": summary.fingerprint_sha256, "mutation_event_id": str(mutation_event_id)})
            if mutation_event_id is not None else summary.fingerprint_sha256
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    INSERT INTO recovery.recovery_ledger_entries(
                        tenant_id, analysis_run_id, mutation_event_id, ledger_fingerprint,
                        currency_code, historical_candidate_micros, projected_prevented_micros,
                        observed_post_action_query_spend_micros, verified_recovery_micros,
                        causal_status, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, analysis_run_id, ledger_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        tenant_id, analysis_run_id, mutation_event_id,
                        ledger_fingerprint, summary.currency_code,
                        summary.historical_candidate_micros, summary.projected_prevented_micros,
                        summary.observed_post_action_query_spend_micros,
                        summary.verified_recovery_micros, summary.causal_status.value,
                        Jsonb(payload),
                    ),
                )
                row = cur.fetchone()
                if row:
                    return row["id"]
                cur.execute(
                    "SELECT id FROM recovery.recovery_ledger_entries WHERE tenant_id=%s AND analysis_run_id=%s AND ledger_fingerprint=%s",
                    (tenant_id, analysis_run_id, ledger_fingerprint),
                )
                return cur.fetchone()["id"]

    def append_audit_event(
        self,
        *,
        tenant_id: UUID,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        actor: str,
        payload: Any,
        occurred_at: datetime | None = None,
    ) -> str:
        occurred_at = occurred_at or datetime.now(timezone.utc)
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                lock = f"audit:{tenant_id}:{aggregate_type}:{aggregate_id}"
                self._advisory_xact_lock(cur, lock)
                cur.execute(
                    """
                    SELECT event_hash FROM recovery.audit_events
                    WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_id=%s
                    ORDER BY occurred_at DESC, id DESC LIMIT 1
                    """,
                    (tenant_id, aggregate_type, aggregate_id),
                )
                previous = cur.fetchone()
                previous_hash = previous["event_hash"] if previous else None
                event_body = {
                    "tenant_id": tenant_id,
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "event_type": event_type,
                    "actor": actor,
                    "occurred_at": occurred_at,
                    "previous_event_hash": previous_hash,
                    "payload": canonical_payload(payload),
                }
                event_hash = payload_sha256(event_body)
                cur.execute(
                    """
                    INSERT INTO recovery.audit_events(
                        tenant_id, aggregate_type, aggregate_id, event_type, actor,
                        occurred_at, previous_event_hash, event_hash, payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id, event_hash) DO NOTHING
                    """,
                    (
                        tenant_id, aggregate_type, aggregate_id, event_type, actor,
                        occurred_at, previous_hash, event_hash,
                        Jsonb(canonical_payload(payload)),
                    ),
                )
                return event_hash

    def fail_sync_run_by_request(
        self, *, tenant_id: UUID, request_id: str, failure_code: str, failure_detail: str
    ) -> None:
        if not request_id.strip():
            raise ValueError("request_id is required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    UPDATE recovery.sync_runs
                    SET status='failed', completed_at=COALESCE(completed_at, now()),
                        failure_code=%s, failure_detail=%s
                    WHERE tenant_id=%s AND request_id=%s AND status='running'
                    """,
                    (failure_code[:120], failure_detail[:4000], tenant_id, request_id),
                )

    def fail_analysis_run_by_request(
        self, *, tenant_id: UUID, request_id: str, failure_code: str, failure_detail: str
    ) -> None:
        if not request_id.strip():
            raise ValueError("request_id is required")
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    UPDATE recovery.analysis_runs
                    SET status='failed', completed_at=COALESCE(completed_at, now()),
                        failure_code=%s, failure_detail=%s
                    WHERE tenant_id=%s AND request_id=%s AND status='running'
                    """,
                    (failure_code[:120], failure_detail[:4000], tenant_id, request_id),
                )

    def complete_analysis_run(self, *, tenant_id: UUID, analysis_run_id: UUID) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_tenant(cur, tenant_id)
                cur.execute(
                    """
                    UPDATE recovery.analysis_runs
                    SET status='completed', completed_at=COALESCE(completed_at, now()),
                        failure_code=NULL, failure_detail=NULL
                    WHERE tenant_id=%s AND id=%s AND status <> 'failed'
                    """,
                    (tenant_id, analysis_run_id),
                )
                if cur.rowcount != 1:
                    raise ValueError("analysis run not found or already failed")
