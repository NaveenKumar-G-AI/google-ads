from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class RecoveryCaseState(str, Enum):
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTION_QUEUED = "execution_queued"
    VALIDATING = "validating"
    APPLIED = "applied"
    FAILED = "failed"
    VERIFICATION_PENDING = "verification_pending"
    VERIFIED = "verified"
    INCONCLUSIVE = "inconclusive"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    ROLLED_BACK = "rolled_back"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class CaseProjection:
    state: RecoveryCaseState
    stale: bool
    stale_reasons: tuple[str, ...]
    execution_allowed: bool
    rollback_allowed: bool
    verification_status: str
    assigned_to: str | None
    closed: bool


def _latest_event(events: Iterable[dict[str, Any]], event_types: set[str]) -> dict[str, Any] | None:
    eligible = [e for e in events if str(e.get("event_type")) in event_types]
    if not eligible:
        return None
    return max(eligible, key=lambda e: (e.get("occurred_at"), str(e.get("id", ""))))


def derive_case_projection(
    *,
    proposal: dict[str, Any],
    proposal_analysis_run_id: str,
    latest_completed_analysis_run_id: str | None,
    latest_truth_fingerprint: str | None,
    decision: dict[str, Any] | None,
    mutation_events: list[dict[str, Any]],
    ledger_entries: list[dict[str, Any]],
    case_events: list[dict[str, Any]],
    queued_execution: bool = False,
    execution_job_status: str | None = None,
    external_effect_state: str | None = None,
) -> CaseProjection:
    """Derive operational state without rewriting immutable source evidence.

    The proposal artifact remains the case identity. Decisions, mutation events,
    ledger evidence and case collaboration events are append-only inputs.
    """

    stale_reasons: list[str] = []
    proposal_truth = str(proposal.get("truth_fingerprint") or "")
    if latest_truth_fingerprint and proposal_truth and latest_truth_fingerprint != proposal_truth:
        stale_reasons.append("business_truth_changed")
    if latest_completed_analysis_run_id and latest_completed_analysis_run_id != proposal_analysis_run_id:
        stale_reasons.append("newer_analysis_available")
    stale = bool(stale_reasons)

    latest_close = _latest_event(case_events, {"closed", "reopened"})
    closed = bool(latest_close and latest_close.get("event_type") == "closed")

    latest_assignment = _latest_event(case_events, {"assigned", "unassigned"})
    assigned_to: str | None = None
    if latest_assignment and latest_assignment.get("event_type") == "assigned":
        assigned_to = str((latest_assignment.get("payload") or {}).get("assigned_to") or "") or None

    latest_mutation = _latest_event(
        mutation_events, {"validate_only_passed", "applied", "rolled_back", "failed"}
    )
    latest_ledger = max(
        ledger_entries,
        key=lambda e: (e.get("created_at"), str(e.get("entry_id") or e.get("id") or "")),
        default=None,
    )
    verification_status = str((latest_ledger or {}).get("causal_status") or "not_evaluated")

    disposition = str(proposal.get("disposition") or "")
    decision_value = str((decision or {}).get("decision") or "")
    mutation_type = str((latest_mutation or {}).get("event_type") or "")

    if closed:
        state = RecoveryCaseState.CLOSED
    elif execution_job_status == "needs_reconciliation" or external_effect_state in {"ambiguous", "in_flight"}:
        state = RecoveryCaseState.NEEDS_RECONCILIATION
    elif mutation_type == "rolled_back":
        state = RecoveryCaseState.ROLLED_BACK
    elif mutation_type == "failed":
        state = RecoveryCaseState.FAILED
    elif mutation_type == "applied":
        if verification_status == "verified":
            state = RecoveryCaseState.VERIFIED
        elif verification_status == "inconclusive":
            state = RecoveryCaseState.INCONCLUSIVE
        elif verification_status in {"not_evaluated", "ineligible"}:
            state = RecoveryCaseState.VERIFICATION_PENDING
        else:
            state = RecoveryCaseState.APPLIED
    elif mutation_type == "validate_only_passed" or execution_job_status == "running":
        state = RecoveryCaseState.VALIDATING
    elif execution_job_status == "failed":
        state = RecoveryCaseState.FAILED
    elif queued_execution or execution_job_status == "queued":
        state = RecoveryCaseState.EXECUTION_QUEUED
    elif decision_value == "approved":
        state = RecoveryCaseState.APPROVED
    elif decision_value == "rejected":
        state = RecoveryCaseState.REJECTED
    elif disposition == "ready_for_approval":
        state = RecoveryCaseState.READY_FOR_REVIEW
    elif disposition == "review_required":
        state = RecoveryCaseState.REVIEW_REQUIRED
    else:
        state = RecoveryCaseState.BLOCKED

    execution_allowed = (
        decision_value == "approved"
        and not stale
        and mutation_type not in {"applied", "rolled_back"}
        and not closed
        and execution_job_status is None
        and external_effect_state is None
    )
    rollback_allowed = mutation_type == "applied"

    return CaseProjection(
        state=state,
        stale=stale,
        stale_reasons=tuple(stale_reasons),
        execution_allowed=execution_allowed,
        rollback_allowed=rollback_allowed,
        verification_status=verification_status,
        assigned_to=assigned_to,
        closed=closed,
    )
