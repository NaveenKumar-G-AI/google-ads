from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from recovery.api.idempotency import canonical_request_sha256
from recovery.reporting import DATE_BOUND_REPORTS, ReportType, next_schedule_due, scheduled_period

from recovery.api.jobs import JobType
from recovery.db.canonical import canonical_payload
from recovery.db.postgres import PostgresRecoveryRepository

from .domain import ClaimedJob, EffectState, ExternalEffect, LeaseLost


class WorkerStore(Protocol):
    def claim_next(self, *, worker_id: str, lease_seconds: int, worker_version: str) -> ClaimedJob | None: ...
    def heartbeat(self, *, job: ClaimedJob, extend_seconds: int) -> datetime: ...
    def succeed(self, *, job: ClaimedJob, result: dict[str, Any]) -> None: ...
    def retry(self, *, job: ClaimedJob, delay_seconds: float, code: str, detail: str) -> None: ...
    def fail(self, *, job: ClaimedJob, code: str, detail: str) -> None: ...
    def needs_reconciliation(self, *, job: ClaimedJob, code: str, detail: str,
                             context: dict[str, Any] | None = None) -> None: ...
    def prepare_external_effect(self, *, job: ClaimedJob, effect_key: str, effect_kind: str,
                                plan_fingerprint: str, proposal_artifact_id: UUID | None,
                                payload: dict[str, Any]) -> ExternalEffect: ...
    def mark_effect_in_flight(self, *, job: ClaimedJob, effect_id: UUID) -> ExternalEffect: ...
    def commit_external_effect(self, *, job: ClaimedJob, effect_id: UUID, resource_name: str | None,
                               google_request_id: str | None, payload: dict[str, Any]) -> ExternalEffect: ...
    def reconcile_external_effect(self, *, job: ClaimedJob, effect_id: UUID, state: EffectState,
                                  resource_name: str | None, detail: str,
                                  payload: dict[str, Any] | None = None) -> ExternalEffect: ...
    def get_external_effect(self, *, tenant_id: UUID, effect_key: str) -> ExternalEffect | None: ...
    def sweep_ambiguous_expired_effects(self, *, worker_id: str) -> int: ...
    def enqueue_due_report_jobs(self) -> int: ...


class PostgresWorkerStore:
    """Cross-tenant durable worker store.

    Use a dedicated backend worker DSN/role with only the privileges needed for the
    recovery schema and with cross-tenant access by design. Never expose this DSN to
    browser/API clients.
    """

    def __init__(self, core: PostgresRecoveryRepository) -> None:
        self.core = core

    def _connect(self):
        return self.core._connect()

    @staticmethod
    def _require_worker_id(worker_id: str) -> str:
        value = worker_id.strip()
        if not value or len(value) > 200:
            raise ValueError("worker_id must be 1..200 characters")
        return value

    @staticmethod
    def _row_to_job(row: Any) -> ClaimedJob:
        return ClaimedJob(
            job_id=row["id"], tenant_id=row["tenant_id"], job_type=JobType(row["job_type"]),
            payload=dict(row["payload"]), requested_by=row["requested_by"],
            operation_key=row["operation_key"], attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]), run_token=row["run_token"],
            lease_owner=row["lease_owner"], lease_expires_at=row["lease_expires_at"],
        )

    @staticmethod
    def _row_to_effect(row: Any) -> ExternalEffect:
        return ExternalEffect(
            effect_id=row["id"], tenant_id=row["tenant_id"], job_id=row["job_id"],
            effect_key=row["effect_key"], effect_kind=row["effect_kind"],
            state=EffectState(row["state"]), plan_fingerprint=row["plan_fingerprint"],
            proposal_artifact_id=row["proposal_artifact_id"], run_token=row["run_token"],
            resource_name=row["resource_name"], google_request_id=row["google_request_id"],
            started_at=row["in_flight_at"],
        )

    @staticmethod
    def _json(value: Any) -> Any:
        try:
            from psycopg.types.json import Jsonb
            return Jsonb(canonical_payload(value))
        except ImportError:
            return canonical_payload(value)

    def claim_next(self, *, worker_id: str, lease_seconds: int, worker_version: str) -> ClaimedJob | None:
        worker_id = self._require_worker_id(worker_id)
        if lease_seconds < 30 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 30 and 3600")
        version = worker_version.strip()
        if not version or len(version) > 100:
            raise ValueError("worker_version must be 1..100 characters")
        run_token = uuid4()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH candidate AS (
                    SELECT j.id
                    FROM recovery.api_jobs j
                    WHERE (
                        (j.status='queued' AND j.available_at <= now())
                        OR
                        (j.status='running' AND j.lease_expires_at <= now()
                         AND NOT EXISTS (
                            SELECT 1 FROM recovery.external_effects e
                            WHERE e.tenant_id=j.tenant_id AND e.job_id=j.id AND e.state='in_flight'
                         ))
                    )
                    AND j.attempts < j.max_attempts
                    ORDER BY j.available_at, j.created_at, j.id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE recovery.api_jobs j
                SET status='running', attempts=j.attempts+1, run_token=%s,
                    lease_owner=%s, leased_at=now(), heartbeat_at=now(),
                    lease_expires_at=now() + (%s * interval '1 second'),
                    last_attempt_at=now(), worker_version=%s,
                    started_at=COALESCE(j.started_at, now()), completed_at=NULL,
                    failure_code=NULL, failure_detail=NULL, failure_class=NULL
                FROM candidate c
                WHERE j.id=c.id
                RETURNING j.*
                """,
                (run_token, worker_id, lease_seconds, version),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """
                INSERT INTO recovery.job_attempts(
                    tenant_id, job_id, attempt_number, run_token, worker_id,
                    claimed_at, lease_expires_at, outcome
                ) VALUES (%s,%s,%s,%s,%s,now(),%s,'running')
                """,
                (row["tenant_id"], row["id"], row["attempts"], run_token,
                 worker_id, row["lease_expires_at"]),
            )
            return self._row_to_job(row)

    def _owned_job(self, cur: Any, job: ClaimedJob, *, require_live_lease: bool = True) -> None:
        condition = "AND lease_expires_at > now()" if require_live_lease else ""
        cur.execute(
            f"""
            SELECT 1 FROM recovery.api_jobs
            WHERE id=%s AND tenant_id=%s AND status='running'
              AND run_token=%s AND lease_owner=%s {condition}
            FOR UPDATE
            """,
            (job.job_id, job.tenant_id, job.run_token, job.lease_owner),
        )
        if cur.fetchone() is None:
            raise LeaseLost("worker no longer owns this job run token", code="LEASE_LOST")

    def heartbeat(self, *, job: ClaimedJob, extend_seconds: int) -> datetime:
        if extend_seconds < 30 or extend_seconds > 3600:
            raise ValueError("extend_seconds must be between 30 and 3600")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE recovery.api_jobs
                SET heartbeat_at=now(), lease_expires_at=now() + (%s * interval '1 second')
                WHERE id=%s AND tenant_id=%s AND status='running'
                  AND run_token=%s AND lease_owner=%s AND lease_expires_at > now()
                RETURNING lease_expires_at
                """,
                (extend_seconds, job.job_id, job.tenant_id, job.run_token, job.lease_owner),
            )
            row = cur.fetchone()
            if row is None:
                raise LeaseLost("heartbeat rejected because lease was lost or expired", code="LEASE_LOST")
            cur.execute(
                """
                UPDATE recovery.job_attempts SET heartbeat_at=now(), lease_expires_at=%s
                WHERE tenant_id=%s AND job_id=%s AND run_token=%s AND outcome='running'
                """,
                (row["lease_expires_at"], job.tenant_id, job.job_id, job.run_token),
            )
            return row["lease_expires_at"]

    def _finish_attempt(self, cur: Any, job: ClaimedJob, *, outcome: str,
                        error_code: str | None = None, error_detail: str | None = None) -> None:
        cur.execute(
            """
            UPDATE recovery.job_attempts
            SET finished_at=now(), outcome=%s, error_code=%s, error_detail=%s
            WHERE tenant_id=%s AND job_id=%s AND run_token=%s AND outcome='running'
            """,
            (outcome, error_code, error_detail[:4000] if error_detail else None,
             job.tenant_id, job.job_id, job.run_token),
        )

    def succeed(self, *, job: ClaimedJob, result: dict[str, Any]) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._owned_job(cur, job)
            cur.execute(
                """
                UPDATE recovery.api_jobs
                SET status='succeeded', result=%s, completed_at=now(),
                    run_token=NULL, lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                WHERE id=%s AND tenant_id=%s AND run_token=%s
                """,
                (self._json(result), job.job_id, job.tenant_id, job.run_token),
            )
            self._finish_attempt(cur, job, outcome="succeeded")

    def retry(self, *, job: ClaimedJob, delay_seconds: float, code: str, detail: str) -> None:
        if delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        if job.attempts >= job.max_attempts:
            self.fail(job=job, code="MAX_ATTEMPTS", detail=detail)
            return
        with self._connect() as conn, conn.cursor() as cur:
            self._owned_job(cur, job)
            cur.execute(
                """
                UPDATE recovery.api_jobs
                SET status='queued', available_at=now() + (%s * interval '1 second'),
                    failure_code=%s, failure_detail=%s, failure_class='transient',
                    last_error_at=now(), run_token=NULL, lease_owner=NULL,
                    lease_expires_at=NULL, heartbeat_at=NULL
                WHERE id=%s AND tenant_id=%s AND run_token=%s
                """,
                (delay_seconds, code[:100], detail[:4000], job.job_id, job.tenant_id, job.run_token),
            )
            self._finish_attempt(cur, job, outcome="retry_scheduled", error_code=code, error_detail=detail)

    def fail(self, *, job: ClaimedJob, code: str, detail: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._owned_job(cur, job)
            cur.execute(
                """
                UPDATE recovery.api_jobs
                SET status='failed', completed_at=now(), failure_code=%s,
                    failure_detail=%s, failure_class='permanent', last_error_at=now(),
                    run_token=NULL, lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                WHERE id=%s AND tenant_id=%s AND run_token=%s
                """,
                (code[:100], detail[:4000], job.job_id, job.tenant_id, job.run_token),
            )
            self._finish_attempt(cur, job, outcome="failed", error_code=code, error_detail=detail)

    def needs_reconciliation(self, *, job: ClaimedJob, code: str, detail: str,
                             context: dict[str, Any] | None = None) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            # Reconciliation is permitted for the exact run token even if its lease
            # expired while the remote call was in flight; no new worker may claim an
            # in-flight effect, so preserving ambiguity is safer than losing it.
            self._owned_job(cur, job, require_live_lease=False)
            cur.execute(
                """
                UPDATE recovery.api_jobs
                SET status='needs_reconciliation', result=%s, completed_at=now(),
                    failure_code=%s, failure_detail=%s, failure_class='reconciliation',
                    last_error_at=now(), run_token=NULL, lease_owner=NULL,
                    lease_expires_at=NULL, heartbeat_at=NULL
                WHERE id=%s AND tenant_id=%s AND run_token=%s
                """,
                (self._json({"reconciliation": context or {}}), code[:100], detail[:4000],
                 job.job_id, job.tenant_id, job.run_token),
            )
            self._finish_attempt(cur, job, outcome="needs_reconciliation", error_code=code, error_detail=detail)

    def prepare_external_effect(self, *, job: ClaimedJob, effect_key: str, effect_kind: str,
                                plan_fingerprint: str, proposal_artifact_id: UUID | None,
                                payload: dict[str, Any]) -> ExternalEffect:
        if not effect_key.strip() or len(effect_key) > 240:
            raise ValueError("effect_key must be 1..240 characters")
        if effect_kind not in {"apply_negative", "rollback_negative"}:
            raise ValueError("unsupported external effect kind")
        with self._connect() as conn, conn.cursor() as cur:
            self._owned_job(cur, job)
            self.core._advisory_xact_lock(cur, f"external-effect:{job.tenant_id}:{effect_key}")
            cur.execute(
                """
                INSERT INTO recovery.external_effects(
                    tenant_id, job_id, effect_key, effect_kind, state, plan_fingerprint,
                    proposal_artifact_id, prepared_payload, prepared_at
                ) VALUES (%s,%s,%s,%s,'prepared',%s,%s,%s,now())
                ON CONFLICT (tenant_id, effect_key) DO NOTHING
                RETURNING *
                """,
                (job.tenant_id, job.job_id, effect_key, effect_kind, plan_fingerprint,
                 proposal_artifact_id, self._json(payload)),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT * FROM recovery.external_effects WHERE tenant_id=%s AND effect_key=%s FOR UPDATE",
                    (job.tenant_id, effect_key),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("external effect conflict lookup failed")
                if row["job_id"] != job.job_id or row["plan_fingerprint"] != plan_fingerprint:
                    raise RuntimeError("external effect key is bound to a different job or plan")
            return self._row_to_effect(row)

    def mark_effect_in_flight(self, *, job: ClaimedJob, effect_id: UUID) -> ExternalEffect:
        with self._connect() as conn, conn.cursor() as cur:
            self._owned_job(cur, job)
            cur.execute(
                """
                UPDATE recovery.external_effects
                SET state='in_flight', run_token=%s, in_flight_at=now()
                WHERE tenant_id=%s AND id=%s AND job_id=%s AND state='prepared'
                RETURNING *
                """,
                (job.run_token, job.tenant_id, effect_id, job.job_id),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("external effect is not in prepared state")
            return self._row_to_effect(row)

    def commit_external_effect(self, *, job: ClaimedJob, effect_id: UUID, resource_name: str | None,
                               google_request_id: str | None, payload: dict[str, Any]) -> ExternalEffect:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE recovery.external_effects
                SET state='committed', committed_at=now(), resource_name=%s,
                    google_request_id=%s, result_payload=%s
                WHERE tenant_id=%s AND id=%s AND job_id=%s
                  AND state='in_flight' AND run_token=%s
                RETURNING *
                """,
                (resource_name, google_request_id, self._json(payload), job.tenant_id,
                 effect_id, job.job_id, job.run_token),
            )
            row = cur.fetchone()
            if row is None:
                raise LeaseLost("external effect fence token no longer matches", code="EFFECT_FENCE_LOST")
            return self._row_to_effect(row)

    def reconcile_external_effect(self, *, job: ClaimedJob, effect_id: UUID, state: EffectState,
                                  resource_name: str | None, detail: str,
                                  payload: dict[str, Any] | None = None) -> ExternalEffect:
        if state not in {EffectState.RECONCILED, EffectState.AMBIGUOUS}:
            raise ValueError("reconciliation state must be reconciled or ambiguous")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT state, run_token FROM recovery.external_effects
                WHERE tenant_id=%s AND id=%s AND job_id=%s
                FOR UPDATE
                """,
                (job.tenant_id, effect_id, job.job_id),
            )
            current = cur.fetchone()
            if current is None or current["state"] not in {"prepared", "in_flight", "ambiguous"}:
                raise RuntimeError("external effect cannot be reconciled from current state")
            if current["state"] == "prepared":
                # Before the remote side effect starts, the job lease is the fencing token.
                self._owned_job(cur, job)
            elif current["run_token"] != job.run_token:
                # Once in-flight, the effect's own run token remains the fence even if the
                # job lease expires while we are preserving an ambiguous outcome.
                raise LeaseLost("external effect belongs to another worker run", code="EFFECT_FENCE_LOST")
            cur.execute(
                """
                UPDATE recovery.external_effects
                SET state=%s, reconciled_at=now(), resource_name=COALESCE(%s, resource_name),
                    reconciliation_detail=%s, result_payload=COALESCE(%s, result_payload)
                WHERE tenant_id=%s AND id=%s AND job_id=%s
                  AND state IN ('prepared','in_flight','ambiguous')
                RETURNING *
                """,
                (state.value, resource_name, detail[:4000],
                 self._json(payload) if payload is not None else None,
                 job.tenant_id, effect_id, job.job_id),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("external effect cannot be reconciled from current state")
            return self._row_to_effect(row)

    def get_external_effect(self, *, tenant_id: UUID, effect_key: str) -> ExternalEffect | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM recovery.external_effects WHERE tenant_id=%s AND effect_key=%s",
                (tenant_id, effect_key),
            )
            row = cur.fetchone()
            return self._row_to_effect(row) if row else None

    def sweep_ambiguous_expired_effects(self, *, worker_id: str) -> int:
        self._require_worker_id(worker_id)
        with self._connect() as conn, conn.cursor() as cur:
            # If a verified immutable mutation event was persisted before the worker
            # crashed, finish the job from that proof rather than re-calling Google.
            cur.execute(
                """
                SELECT j.id AS job_id, j.tenant_id, j.run_token, e.id AS effect_id,
                       e.effect_kind, e.proposal_artifact_id, m.resource_name,
                       m.id AS mutation_event_id
                FROM recovery.api_jobs j
                JOIN recovery.external_effects e
                  ON e.tenant_id=j.tenant_id AND e.job_id=j.id AND e.state='in_flight'
                JOIN LATERAL (
                    SELECT id, resource_name, event_type, occurred_at
                    FROM recovery.mutation_events m
                    WHERE m.tenant_id=e.tenant_id
                      AND m.proposal_artifact_id=e.proposal_artifact_id
                      AND m.event_type = CASE
                          WHEN e.effect_kind='apply_negative' THEN 'applied'
                          ELSE 'rolled_back' END
                      AND m.occurred_at >= e.in_flight_at
                    ORDER BY m.occurred_at DESC, m.id DESC LIMIT 1
                ) m ON true
                WHERE j.status='running' AND j.lease_expires_at <= now()
                FOR UPDATE OF j, e SKIP LOCKED
                """
            )
            proven = cur.fetchall()
            for row in proven:
                result = {
                    "recovered_after_worker_crash": True,
                    "mutation_event_id": str(row["mutation_event_id"]),
                    "resource_name": row["resource_name"],
                }
                cur.execute(
                    """
                    UPDATE recovery.external_effects
                    SET state='committed', committed_at=now(), resource_name=%s,
                        result_payload=%s
                    WHERE tenant_id=%s AND job_id=%s AND state='in_flight'
                    """,
                    (row["resource_name"], self._json(result), row["tenant_id"], row["effect_id"]),
                )
                cur.execute(
                    """
                    UPDATE recovery.api_jobs
                    SET status='succeeded', completed_at=now(), result=%s,
                        run_token=NULL, lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                    WHERE tenant_id=%s AND id=%s AND status='running'
                    """,
                    (self._json(result), row["tenant_id"], row["job_id"]),
                )
                cur.execute(
                    """
                    UPDATE recovery.job_attempts SET finished_at=now(), outcome='succeeded'
                    WHERE tenant_id=%s AND job_id=%s AND run_token=%s AND outcome='running'
                    """,
                    (row["tenant_id"], row["job_id"], row["run_token"]),
                )

            # Any remaining expired in-flight side effect has no durable proof. It is
            # quarantined instead of being automatically replayed.
            cur.execute(
                """
                WITH ambiguous AS (
                    SELECT j.id, j.tenant_id, j.run_token
                    FROM recovery.api_jobs j
                    JOIN recovery.external_effects e
                      ON e.tenant_id=j.tenant_id AND e.job_id=j.id AND e.state='in_flight'
                    WHERE j.status='running' AND j.lease_expires_at <= now()
                    FOR UPDATE OF j, e SKIP LOCKED
                )
                UPDATE recovery.api_jobs j
                SET status='needs_reconciliation', completed_at=now(),
                    failure_code='AMBIGUOUS_EXTERNAL_EFFECT',
                    failure_detail='worker lease expired while a non-idempotent external effect was in flight',
                    failure_class='reconciliation', last_error_at=now(),
                    run_token=NULL, lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                FROM ambiguous a
                WHERE j.id=a.id
                RETURNING j.id, j.tenant_id, a.run_token
                """
            )
            ambiguous = cur.fetchall()
            for row in ambiguous:
                cur.execute(
                    """
                    UPDATE recovery.external_effects
                    SET state='ambiguous', reconciled_at=COALESCE(reconciled_at, now()),
                        reconciliation_detail=COALESCE(
                            reconciliation_detail,
                            'worker lease expired while external effect was in flight'
                        )
                    WHERE tenant_id=%s AND job_id=%s AND state='in_flight'
                    """,
                    (row["tenant_id"], row["id"]),
                )
                cur.execute(
                    """
                    UPDATE recovery.job_attempts
                    SET finished_at=now(), outcome='needs_reconciliation',
                        error_code='AMBIGUOUS_EXTERNAL_EFFECT',
                        error_detail='lease expired with external side effect in flight'
                    WHERE tenant_id=%s AND job_id=%s AND run_token=%s AND outcome='running'
                    """,
                    (row["tenant_id"], row["id"], row["run_token"]),
                )

            # A safe/replayable job whose final permitted attempt died after its lease
            # expired must not remain RUNNING forever. Mutation jobs are included only
            # when no external effect is in-flight, so this cannot replay/quarantine a
            # possibly committed Google mutation.
            cur.execute(
                """
                WITH exhausted AS (
                    SELECT j.id, j.tenant_id, j.run_token, j.job_type
                    FROM recovery.api_jobs j
                    WHERE j.status='running' AND j.lease_expires_at <= now()
                      AND j.attempts >= j.max_attempts
                      AND NOT EXISTS (
                          SELECT 1 FROM recovery.external_effects e
                          WHERE e.tenant_id=j.tenant_id AND e.job_id=j.id
                            AND e.state='in_flight'
                      )
                    FOR UPDATE OF j SKIP LOCKED
                )
                UPDATE recovery.api_jobs j
                SET status='failed', completed_at=now(),
                    failure_code='LEASE_EXPIRED_MAX_ATTEMPTS',
                    failure_detail='final worker attempt lost its lease before a terminal result was persisted',
                    failure_class='permanent', last_error_at=now(),
                    run_token=NULL, lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=NULL
                FROM exhausted x
                WHERE j.id=x.id
                RETURNING j.id, j.tenant_id, x.run_token, x.job_type
                """
            )
            exhausted = cur.fetchall()
            for row in exhausted:
                cur.execute(
                    """
                    UPDATE recovery.job_attempts
                    SET finished_at=now(), outcome='failed',
                        error_code='LEASE_EXPIRED_MAX_ATTEMPTS',
                        error_detail='final worker attempt lease expired'
                    WHERE tenant_id=%s AND job_id=%s AND run_token=%s AND outcome='running'
                    """,
                    (row["tenant_id"], row["id"], row["run_token"]),
                )
                request_id = f"worker-job:{row['id']}"
                if row["job_type"] == JobType.GOOGLE_ADS_SYNC.value:
                    cur.execute(
                        """
                        UPDATE recovery.sync_runs
                        SET status='failed', completed_at=COALESCE(completed_at, now()),
                            failure_code='LEASE_EXPIRED_MAX_ATTEMPTS',
                            failure_detail='worker exhausted its attempt budget after lease expiry'
                        WHERE tenant_id=%s AND request_id=%s AND status='running'
                        """,
                        (row["tenant_id"], request_id),
                    )
                elif row["job_type"] == JobType.ANALYSIS_RUN.value:
                    cur.execute(
                        """
                        UPDATE recovery.analysis_runs
                        SET status='failed', completed_at=COALESCE(completed_at, now()),
                            failure_code='LEASE_EXPIRED_MAX_ATTEMPTS',
                            failure_detail='worker exhausted its attempt budget after lease expiry'
                        WHERE tenant_id=%s AND request_id=%s AND status='running'
                        """,
                        (row["tenant_id"], request_id),
                    )
            return len(proven) + len(ambiguous) + len(exhausted)

    def enqueue_due_report_jobs(self) -> int:
        """Project latest report schedule events and enqueue at most one overdue run per schedule.

        This is intentionally called by durable workers, not browser/API timers. Unique
        operation keys and schedule-run rows make concurrent worker ticks safe.
        """
        now=datetime.now(timezone.utc); enqueued=0
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (tenant_id,schedule_id)
                       tenant_id,schedule_id,report_type,scope_kind,scope_id,frequency,timezone_name,
                       hour,minute,weekday,day_of_month,recipients,enabled,actor_user_id,occurred_at
                FROM recovery.report_schedule_events
                ORDER BY tenant_id,schedule_id,occurred_at DESC,id DESC
            """)
            schedules=[dict(r) for r in cur.fetchall() if bool(r["enabled"])]
            for row in schedules:
                cur.execute("SELECT max(scheduled_for) AS last_for FROM recovery.report_schedule_runs WHERE tenant_id=%s AND schedule_id=%s",(row["tenant_id"],row["schedule_id"]))
                last=cur.fetchone()["last_for"]
                after=last or row["occurred_at"]
                # Avoid an email/report storm after a long worker outage: at most one
                # catch-up period per schedule becomes due on recovery.
                cap_days={"daily":2,"weekly":8,"monthly":35}[row["frequency"]]
                floor=now-timedelta(days=cap_days)
                if after<floor: after=floor
                due=next_schedule_due(
                    frequency=row["frequency"],timezone_name=row["timezone_name"],hour=row["hour"],minute=row["minute"],
                    weekday=row["weekday"],day_of_month=row["day_of_month"],after=after,
                )
                if due>now: continue
                rt=ReportType(row["report_type"])
                if rt in DATE_BOUND_REPORTS:
                    start,end=scheduled_period(frequency=row["frequency"],scheduled_for=due,timezone_name=row["timezone_name"])
                else: start=end=None
                payload={
                    "report_type":row["report_type"],"scope_kind":row["scope_kind"],"scope_id":row["scope_id"],
                    "period_start":start.isoformat() if start else None,"period_end":end.isoformat() if end else None,
                    "schedule_id":str(row["schedule_id"]),"scheduled_for":due.isoformat(),
                }
                endpoint=f"system:report-schedule:{row['schedule_id']}"
                idem=due.strftime("%Y%m%dT%H%M%SZ")
                op=f"report-schedule:{row['schedule_id']}:{idem}"
                request_hash=canonical_request_sha256(method="SYSTEM",path=endpoint,payload=payload)
                job_id=uuid4()
                cur.execute("""
                    INSERT INTO recovery.api_jobs(
                        id,tenant_id,job_type,status,payload,requested_by,endpoint,operation_key,
                        idempotency_key,request_sha256,available_at,max_attempts
                    ) VALUES (%s,%s,'report_generation','queued',%s,%s,%s,%s,%s,%s,now(),3)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """,(job_id,row["tenant_id"],self._json(payload),row["actor_user_id"],endpoint,op,idem,request_hash))
                inserted=cur.fetchone()
                if inserted is None:
                    cur.execute("SELECT id FROM recovery.api_jobs WHERE tenant_id=%s AND job_type='report_generation' AND operation_key=%s",(row["tenant_id"],op))
                    existing=cur.fetchone()
                    if existing is None: continue
                    job_id=existing["id"]
                cur.execute("""INSERT INTO recovery.report_schedule_runs(tenant_id,schedule_id,scheduled_for,job_id)
                               VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",(row["tenant_id"],row["schedule_id"],due,job_id))
                if cur.fetchone() is not None: enqueued+=1
        return enqueued
