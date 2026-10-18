from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class RecoveryProofTotals:
    """Financial proof classes that must never be collapsed into one number."""

    currency_code: str
    current_observed_candidate_micros: int = 0
    acted_on_historical_candidate_micros: int = 0
    projected_prevented_micros: int = 0
    observed_post_action_query_spend_micros: int = 0
    verified_recovery_micros: int = 0

    def __post_init__(self) -> None:
        if len(self.currency_code) != 3 or not self.currency_code.isalpha() or self.currency_code != self.currency_code.upper():
            raise ValueError("currency_code must be a 3-letter uppercase code")
        values=(
            self.current_observed_candidate_micros,
            self.acted_on_historical_candidate_micros,
            self.projected_prevented_micros,
            self.observed_post_action_query_spend_micros,
            self.verified_recovery_micros,
        )
        if any(v < 0 for v in values):
            raise ValueError("recovery proof amounts cannot be negative")

    @property
    def descriptive_difference_vs_projection_micros(self) -> int:
        """Observed arithmetic difference, never a causal/recovery claim."""
        return max(self.projected_prevented_micros - self.observed_post_action_query_spend_micros, 0)

    @property
    def additive_total_micros(self) -> int:
        """Intentionally forbidden: these classes describe different questions."""
        raise RuntimeError("Recovery proof classes are non-additive by contract")


def latest_ledger_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the latest ledger snapshot for each mutation event.

    Unlinked legacy rows are excluded from case/account recovery headlines because they
    cannot prove which external intervention they belong to.
    """
    latest: dict[str, dict[str, Any]] = {}
    for raw in entries:
        mutation_id=raw.get("mutation_event_id")
        if not mutation_id:
            continue
        key=str(mutation_id)
        row=dict(raw)
        current=latest.get(key)
        if current is None:
            latest[key]=row
            continue
        a=(row.get("created_at"), str(row.get("entry_id") or row.get("id") or ""))
        b=(current.get("created_at"), str(current.get("entry_id") or current.get("id") or ""))
        if a > b:
            latest[key]=row
    return list(latest.values())


def aggregate_latest_ledger(entries: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in latest_ledger_entries(entries):
        currency=str(row.get("currency_code") or "").upper()
        if len(currency) != 3:
            raise ValueError("ledger entry has invalid currency")
        causal=str(row.get("causal_status") or "not_evaluated")
        verified=int(row.get("verified_recovery_micros") or 0)
        if verified and causal != "verified":
            raise ValueError("non-verified ledger row cannot contribute verified recovery")
        bucket=buckets.setdefault(currency, {
            "acted_on_historical_candidate_micros":0,
            "projected_prevented_micros":0,
            "observed_post_action_query_spend_micros":0,
            "verified_recovery_micros":0,
            "ledger_action_count":0,
            "verified_action_count":0,
            "inconclusive_action_count":0,
            "verification_pending_action_count":0,
        })
        bucket["acted_on_historical_candidate_micros"] += int(row.get("historical_candidate_micros") or 0)
        bucket["projected_prevented_micros"] += int(row.get("projected_prevented_micros") or 0)
        bucket["observed_post_action_query_spend_micros"] += int(row.get("observed_post_action_query_spend_micros") or 0)
        bucket["verified_recovery_micros"] += verified
        bucket["ledger_action_count"] += 1
        if causal == "verified": bucket["verified_action_count"] += 1
        elif causal == "inconclusive": bucket["inconclusive_action_count"] += 1
        else: bucket["verification_pending_action_count"] += 1
    return buckets


def safe_ratio(numerator: int, denominator: int) -> float | None:
    if numerator < 0 or denominator < 0:
        raise ValueError("ratio inputs cannot be negative")
    return None if denominator == 0 else numerator / denominator
