from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

from recovery.api.jobs import JobType

from .domain import ClaimedJob, EffectState, JobSuccess, PermanentWorkerError, ReconciliationRequired
from .retry import mutation_exception_context
from .store import WorkerStore


class JobHandler(Protocol):
    def __call__(self, job: ClaimedJob) -> JobSuccess: ...


class SafeRunner(Protocol):
    def __call__(self, *, tenant_id: UUID, job_id: UUID, payload: dict[str, Any]) -> dict[str, Any]: ...


class MutationRunner(Protocol):
    """Mutation runner boundary used by the durable worker.

    `validate` must not change Google Ads. `preflight` must read current Google state.
    `apply` / `rollback` are the only non-idempotent remote calls.
    """
    def preflight(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]: ...
    def validate(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]: ...
    def apply(self, *, tenant_id: UUID, payload: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]: ...
    def rollback(self, *, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(slots=True)
class SafeJobHandler:
    runner: SafeRunner
    on_terminal_failure: Callable[[ClaimedJob, BaseException], None] | None = None

    def __call__(self, job: ClaimedJob) -> JobSuccess:
        return JobSuccess(self.runner(tenant_id=job.tenant_id, job_id=job.job_id, payload=job.payload))

    def terminal_failure(self, job: ClaimedJob, exc: BaseException) -> None:
        callback = self.on_terminal_failure or getattr(self.runner, "terminal_failure", None)
        if callable(callback):
            callback(job, exc)


@dataclass(slots=True)
class DurableMutationHandler:
    store: WorkerStore
    runner: MutationRunner
    rollback: bool = False

    def __call__(self, job: ClaimedJob) -> JobSuccess:
        proposal_raw = job.payload.get("proposal_artifact_id")
        if not proposal_raw:
            raise PermanentWorkerError("mutation payload is missing proposal_artifact_id", code="BAD_MUTATION_PAYLOAD")
        proposal_id = UUID(str(proposal_raw))
        plan_fp = str(job.payload.get("proposal_fingerprint") or "").strip().lower()
        if len(plan_fp) != 64:
            # Rollback payloads are bound to the immutable applied mutation resource rather
            # than a proposal fingerprint, so use that stable resource as the plan seed.
            resource = str(job.payload.get("resource_name") or "")
            if self.rollback and resource:
                import hashlib
                plan_fp = hashlib.sha256(resource.encode()).hexdigest()
            else:
                raise PermanentWorkerError("mutation payload has invalid proposal fingerprint", code="BAD_PLAN_FINGERPRINT")

        effect_kind = "rollback_negative" if self.rollback else "apply_negative"
        effect_key = job.operation_key or f"proposal:{proposal_id}:{'rollback' if self.rollback else 'apply'}"
        effect = self.store.prepare_external_effect(
            job=job, effect_key=effect_key, effect_kind=effect_kind,
            plan_fingerprint=plan_fp, proposal_artifact_id=proposal_id, payload=job.payload,
        )
        if effect.state.value in {"committed", "reconciled"}:
            return JobSuccess({
                "effect_id": str(effect.effect_id), "effect_state": effect.state.value,
                "resource_name": effect.resource_name, "idempotent_replay": True,
            })
        if effect.state.value in {"in_flight", "ambiguous"}:
            raise ReconciliationRequired(
                "external mutation has an unresolved prior in-flight attempt; automatic replay is forbidden",
                code="AMBIGUOUS_PRIOR_EFFECT",
                context={"effect_id": str(effect.effect_id), "state": effect.state.value},
            )

        preflight = self.runner.preflight(tenant_id=job.tenant_id, payload=job.payload)
        if not self.rollback and preflight.get("exact_negative_present"):
            # A negative appeared after proposal approval but before our mutation. We do
            # not claim ownership or create another copy.
            self.store.reconcile_external_effect(
                job=job, effect_id=effect.effect_id, state=EffectState.AMBIGUOUS,
                resource_name=preflight.get("resource_name"),
                detail="approved exact negative already exists before live mutation; ownership is not provable",
                payload={"preflight": preflight},
            )
            raise ReconciliationRequired(
                "approved exact negative already exists before mutation; manual reconciliation required",
                code="PREEXISTING_NEGATIVE_AFTER_APPROVAL",
                context={"preflight": preflight, "effect_id": str(effect.effect_id)},
            )
        if self.rollback and preflight.get("resource_absent"):
            # Desired end state already holds. We can reconcile outcome without claiming
            # that this worker removed it.
            reconciled = self.store.reconcile_external_effect(
                job=job, effect_id=effect.effect_id, state=EffectState.RECONCILED,
                resource_name=str(job.payload.get("resource_name") or "") or None,
                detail="rollback target was already absent before live remove; outcome achieved without attribution",
                payload={"preflight": preflight, "attribution": "not_claimed"},
            )
            return JobSuccess({
                "effect_id": str(reconciled.effect_id), "effect_state": reconciled.state.value,
                "resource_name": reconciled.resource_name, "attribution": "not_claimed",
            })

        validation: dict[str, Any] = {}
        if not self.rollback:
            validation = self.runner.validate(tenant_id=job.tenant_id, payload=job.payload)

        self.store.mark_effect_in_flight(job=job, effect_id=effect.effect_id)
        try:
            result = (
                self.runner.rollback(tenant_id=job.tenant_id, payload=job.payload)
                if self.rollback
                else self.runner.apply(tenant_id=job.tenant_id, payload=job.payload, validation=validation)
            )
        except BaseException as exc:
            context = mutation_exception_context(exc)
            self.store.reconcile_external_effect(
                job=job, effect_id=effect.effect_id,
                state=EffectState.AMBIGUOUS,
                resource_name=None,
                detail="live Google mutate returned an exception after effect entered in-flight state",
                payload=context,
            )
            raise ReconciliationRequired(
                "live Google mutate outcome is ambiguous; automatic retry is forbidden",
                code="GOOGLE_MUTATE_OUTCOME_AMBIGUOUS", context=context,
            ) from exc

        resource_name = str(result.get("resource_name") or job.payload.get("resource_name") or "").strip() or None
        committed = self.store.commit_external_effect(
            job=job, effect_id=effect.effect_id, resource_name=resource_name,
            google_request_id=result.get("google_request_id"), payload=result,
        )
        return JobSuccess({
            **result,
            "effect_id": str(committed.effect_id),
            "effect_state": committed.state.value,
            "resource_name": committed.resource_name,
        })


class HandlerRegistry:
    def __init__(self, handlers: Mapping[JobType, JobHandler]) -> None:
        self.handlers = dict(handlers)

    def handler_for(self, job_type: JobType) -> JobHandler:
        try:
            return self.handlers[job_type]
        except KeyError as exc:
            raise PermanentWorkerError(
                f"no handler registered for job type {job_type.value}", code="NO_JOB_HANDLER"
            ) from exc
