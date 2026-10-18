from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .domain import LeaseLost, PermanentWorkerError, ReconciliationRequired, RetryableWorkerError
from .handlers import HandlerRegistry
from .retry import WorkerRetryPolicy, classify_safe_job_failure
from .store import WorkerStore


class LeaseHeartbeat:
    def __init__(self, *, store: WorkerStore, job, lease_seconds: int,
                 interval_seconds: float | None = None) -> None:
        self.store = store
        self.job = job
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds or max(5.0, lease_seconds / 3)
        if self.interval_seconds >= lease_seconds:
            raise ValueError("heartbeat interval must be shorter than lease")
        self._stop = threading.Event()
        self._lost: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self):
        def loop() -> None:
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.store.heartbeat(job=self.job, extend_seconds=self.lease_seconds)
                except BaseException as exc:
                    self._lost = exc
                    self._stop.set()
                    break
        self._thread = threading.Thread(target=loop, name=f"lease-{self.job.job_id}", daemon=True)
        self._thread.start()
        return self

    def assert_owned(self) -> None:
        if self._lost is not None:
            raise LeaseLost(f"lease heartbeat failed: {self._lost}", code="LEASE_LOST")

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1))
        if exc is None:
            self.assert_owned()
        return False


@dataclass(slots=True)
class WorkerRuntime:
    store: WorkerStore
    registry: HandlerRegistry
    worker_id: str
    worker_version: str = "phase10"
    lease_seconds: int = 300
    heartbeat_interval_seconds: float | None = None
    retry_policy: WorkerRetryPolicy = WorkerRetryPolicy()
    sleeper: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id is required")
        if self.lease_seconds < 30 or self.lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 30 and 3600")

    @staticmethod
    def _terminal_failure_hook(handler, job, exc: BaseException) -> None:
        hook = getattr(handler, "terminal_failure", None)
        if callable(hook):
            try:
                hook(job, exc)
            except BaseException:
                # The job's durable terminal state is authoritative. A cleanup hook is
                # best-effort and must never turn the original failure into a replay.
                pass

    @staticmethod
    def _lease_safe_transition(call: Callable[[], None]) -> bool:
        try:
            call()
            return True
        except LeaseLost:
            # Another worker now owns the job. Never overwrite its newer state.
            return False

    def run_once(self) -> bool:
        # First quarantine expired non-idempotent calls. This is done before claims so
        # another worker can never silently replay an ambiguous Google mutation.
        self.store.sweep_ambiguous_expired_effects(worker_id=self.worker_id)
        # Report schedules are projected by the durable worker rather than a browser timer.
        # Test/fake stores from earlier phases need not implement this optional maintenance hook.
        tick=getattr(self.store,"enqueue_due_report_jobs",None)
        if callable(tick):
            tick()
        job = self.store.claim_next(
            worker_id=self.worker_id, lease_seconds=self.lease_seconds,
            worker_version=self.worker_version,
        )
        if job is None:
            return False
        handler = None
        try:
            handler = self.registry.handler_for(job.job_type)
            with LeaseHeartbeat(
                store=self.store, job=job, lease_seconds=self.lease_seconds,
                interval_seconds=self.heartbeat_interval_seconds,
            ) as heartbeat:
                outcome = handler(job)
                heartbeat.assert_owned()
            self._lease_safe_transition(lambda: self.store.succeed(job=job, result=outcome.result))
        except ReconciliationRequired as exc:
            self._lease_safe_transition(lambda: self.store.needs_reconciliation(
                job=job, code=exc.code, detail=str(exc), context=exc.context,
            ))
        except LeaseLost:
            return True
        except PermanentWorkerError as exc:
            if handler is not None:
                self._terminal_failure_hook(handler, job, exc)
            self._lease_safe_transition(lambda: self.store.fail(job=job, code=exc.code, detail=str(exc)))
        except BaseException as exc:
            retry = classify_safe_job_failure(exc, attempt=job.attempts, policy=self.retry_policy)
            if retry is not None and job.attempts < job.max_attempts:
                self._lease_safe_transition(lambda: self.store.retry(
                    job=job, delay_seconds=retry.delay_seconds,
                    code=retry.code, detail=retry.detail,
                ))
            elif retry is not None:
                terminal = PermanentWorkerError(
                    f"maximum attempts reached after retryable failure: {retry.detail}",
                    code="MAX_ATTEMPTS",
                )
                if handler is not None:
                    self._terminal_failure_hook(handler, job, terminal)
                self._lease_safe_transition(lambda: self.store.fail(
                    job=job, code=terminal.code, detail=str(terminal),
                ))
            else:
                if handler is not None:
                    self._terminal_failure_hook(handler, job, exc)
                code = getattr(exc, "code", None) or type(exc).__name__.upper()[:100]
                self._lease_safe_transition(lambda: self.store.fail(job=job, code=str(code), detail=str(exc)))
        return True

    def run_forever(self, *, idle_sleep_seconds: float = 2.0,
                    stop_event: threading.Event | None = None) -> None:
        if idle_sleep_seconds < 0:
            raise ValueError("idle_sleep_seconds cannot be negative")
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            did_work = self.run_once()
            if not did_work:
                stop_event.wait(idle_sleep_seconds)
