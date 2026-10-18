from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class CampaignHealthObservation:
    customer_id: str
    campaign_id: str
    campaign_name: str
    advertising_channel_type: str
    status: str
    primary_status: str
    primary_status_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.customer_id.isdigit() or not self.campaign_id.isdigit():
            raise ValueError("campaign health ids must contain digits only")
        if not self.campaign_name.strip():
            raise ValueError("campaign health campaign_name is required")
        if not self.status.strip() or not self.primary_status.strip():
            raise ValueError("campaign health status fields are required")


@dataclass(frozen=True, slots=True)
class MonitorSignal:
    monitor_type: str
    source_key: str
    severity: AlertSeverity
    title: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.monitor_type.strip() or not self.source_key.strip() or not self.title.strip():
            raise ValueError("monitor signal identity/title is required")


def campaign_health_signal(row: CampaignHealthObservation) -> MonitorSignal | None:
    """Map Google's observed campaign primary status into an operational signal.

    A deliberately paused/removed campaign is not automatically an incident. Google
    documents primary_status as output-only and potentially delayed after changes, so
    the exact provider status/reasons are preserved in evidence rather than presented
    as instantaneous ground truth.
    """
    status = row.status.upper()
    primary = row.primary_status.upper()
    if status in {"PAUSED", "REMOVED"}:
        return None
    if primary in {"NOT_ELIGIBLE", "MISCONFIGURED"}:
        severity = AlertSeverity.CRITICAL
    elif primary == "LIMITED":
        severity = AlertSeverity.WARNING
    else:
        return None
    reasons = tuple(x.upper() for x in row.primary_status_reasons)
    return MonitorSignal(
        monitor_type="campaign_serving",
        source_key=f"campaign:{row.campaign_id}",
        severity=severity,
        title=f"{row.campaign_name} is {primary.lower().replace('_', ' ')}",
        evidence={
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "campaign_status": status,
            "primary_status": primary,
            "primary_status_reasons": list(reasons),
            "provider_semantics": "observed_google_primary_status_may_lag_changes",
            "financial_claim_supported": False,
            "causal_claim_supported": False,
        },
    )


def spend_anomaly_signal(
    *,
    campaign_id: str,
    campaign_name: str,
    currency_code: str,
    baseline_daily_cost_micros: float,
    recent_daily_cost_micros: float,
    baseline_days: int,
    recent_days: int,
    spend_multiplier: float = 2.0,
    min_cost_delta_micros: int = 10_000_000,
    min_baseline_daily_cost_micros: int = 5_000_000,
) -> MonitorSignal | None:
    if baseline_days < 7 or recent_days < 2:
        return None
    if min_baseline_daily_cost_micros < 0:
        raise ValueError("min_baseline_daily_cost_micros cannot be negative")
    if baseline_daily_cost_micros < min_baseline_daily_cost_micros:
        return None
    if recent_daily_cost_micros < baseline_daily_cost_micros * spend_multiplier:
        return None
    if recent_daily_cost_micros - baseline_daily_cost_micros < min_cost_delta_micros:
        return None
    return MonitorSignal(
        monitor_type="spend_anomaly",
        source_key=f"campaign:{campaign_id}",
        severity=AlertSeverity.WARNING,
        title=f"Spend increased sharply for {campaign_name}",
        evidence={
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "currency_code": currency_code,
            "baseline_daily_cost_micros": round(baseline_daily_cost_micros),
            "recent_daily_cost_micros": round(recent_daily_cost_micros),
            "baseline_days": baseline_days,
            "recent_days": recent_days,
            "threshold_multiplier": spend_multiplier,
            "minimum_delta_micros": min_cost_delta_micros,
            "minimum_baseline_daily_cost_micros": min_baseline_daily_cost_micros,
            "financial_claim_supported": False,
            "causal_claim_supported": False,
        },
    )


def conversion_drop_signal(
    *,
    campaign_id: str,
    campaign_name: str,
    currency_code: str,
    baseline_daily_cost_micros: float,
    recent_daily_cost_micros: float,
    baseline_daily_conversions: Decimal,
    recent_daily_conversions: Decimal,
    baseline_days: int,
    recent_days: int,
    conversion_ratio: float = 0.30,
    maturity_lag_days: int = 0,
    min_baseline_daily_conversions: Decimal = Decimal("1"),
    min_recent_spend_ratio: float = 0.5,
) -> MonitorSignal | None:
    if baseline_days < 7 or recent_days < 2:
        return None
    if maturity_lag_days < 0:
        raise ValueError("maturity_lag_days cannot be negative")
    if min_baseline_daily_conversions < 0 or min_recent_spend_ratio < 0:
        raise ValueError("conversion-drop minimum evidence gates cannot be negative")
    if baseline_daily_conversions < min_baseline_daily_conversions:
        return None
    if recent_daily_conversions > baseline_daily_conversions * Decimal(str(conversion_ratio)):
        return None
    if recent_daily_cost_micros < baseline_daily_cost_micros * min_recent_spend_ratio:
        return None
    return MonitorSignal(
        monitor_type="conversion_drop",
        source_key=f"campaign:{campaign_id}",
        severity=AlertSeverity.CRITICAL,
        title=f"Conversions dropped sharply for {campaign_name}",
        evidence={
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "currency_code": currency_code,
            "baseline_daily_conversions": str(baseline_daily_conversions),
            "recent_daily_conversions": str(recent_daily_conversions),
            "baseline_daily_cost_micros": round(baseline_daily_cost_micros),
            "recent_daily_cost_micros": round(recent_daily_cost_micros),
            "baseline_days": baseline_days,
            "recent_days": recent_days,
            "maturity_lag_days": maturity_lag_days,
            "minimum_baseline_daily_conversions": str(min_baseline_daily_conversions),
            "minimum_recent_spend_ratio": min_recent_spend_ratio,
            "financial_claim_supported": False,
            "causal_claim_supported": False,
        },
    )


def anomaly_signals(
    *,
    campaign_id: str,
    campaign_name: str,
    currency_code: str,
    baseline_daily_cost_micros: float,
    recent_daily_cost_micros: float,
    baseline_daily_conversions: Decimal,
    recent_daily_conversions: Decimal,
    baseline_days: int,
    recent_days: int,
    spend_multiplier: float = 2.0,
    min_cost_delta_micros: int = 10_000_000,
    conversion_ratio: float = 0.30,
) -> tuple[MonitorSignal, ...]:
    """Backward-compatible conservative anomaly helper used in focused tests.

    Production evaluation uses separate spend and conversion windows so conversion
    monitoring can respect the configured conversion-maturity lag.
    """
    out: list[MonitorSignal] = []
    spend = spend_anomaly_signal(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        currency_code=currency_code,
        baseline_daily_cost_micros=baseline_daily_cost_micros,
        recent_daily_cost_micros=recent_daily_cost_micros,
        baseline_days=baseline_days,
        recent_days=recent_days,
        spend_multiplier=spend_multiplier,
        min_cost_delta_micros=min_cost_delta_micros,
    )
    if spend:
        out.append(spend)
    conversion = conversion_drop_signal(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        currency_code=currency_code,
        baseline_daily_cost_micros=baseline_daily_cost_micros,
        recent_daily_cost_micros=recent_daily_cost_micros,
        baseline_daily_conversions=baseline_daily_conversions,
        recent_daily_conversions=recent_daily_conversions,
        baseline_days=baseline_days,
        recent_days=recent_days,
        conversion_ratio=conversion_ratio,
    )
    if conversion:
        out.append(conversion)
    return tuple(out)


def derive_alert_state(events: Sequence[Mapping[str, Any]]) -> AlertState:
    state = AlertState.OPEN
    for event in sorted(events, key=lambda x: (x.get("occurred_at"), str(x.get("id", "")))):
        kind = str(event.get("event_type") or "")
        if kind in {"opened", "reopened"}:
            state = AlertState.OPEN
        elif kind == "acknowledged":
            state = AlertState.ACKNOWLEDGED
        elif kind in {"resolved", "auto_resolved"}:
            state = AlertState.RESOLVED
        elif kind == "dismissed":
            state = AlertState.DISMISSED
    return state


def incident_observation_action(
    previous_state: str | None,
    previous_generation: int | None,
    *,
    condition_cleared_after_close: bool = True,
) -> tuple[str, int, str]:
    """Choose incident identity for a newly observed signal.

    A recurrence is a *new generation* only after the evaluator has observed the
    condition absent following closure. Manual resolution alone is not evidence
    that the underlying condition cleared. If a manually resolved condition is
    still present, the same generation is automatically reopened. A manually
    dismissed condition remains dismissed while it persists and is merely
    re-observed; it can generate a new incident only after a later clear pass.
    """
    if previous_state is None:
        return ("new", (previous_generation or 0) + 1, "opened")
    if previous_state in {AlertState.OPEN.value, AlertState.ACKNOWLEDGED.value}:
        return ("reuse", previous_generation or 1, "observed")
    if previous_state == AlertState.RESOLVED.value:
        if condition_cleared_after_close:
            return ("new", (previous_generation or 0) + 1, "opened")
        return ("reuse", previous_generation or 1, "reopened")
    if previous_state == AlertState.DISMISSED.value:
        if condition_cleared_after_close:
            return ("new", (previous_generation or 0) + 1, "opened")
        return ("reuse", previous_generation or 1, "observed")
    raise ValueError("unknown previous alert state")


def validate_alert_transition(current_state: str, event_type: str) -> None:
    if event_type == "commented":
        return
    active_only = {"assigned", "unassigned"}
    if event_type in active_only:
        if current_state not in {AlertState.OPEN.value, AlertState.ACKNOWLEDGED.value}:
            raise ValueError(f"event {event_type} is invalid from alert state {current_state}")
        return
    allowed = {
        AlertState.OPEN.value: {"acknowledged", "resolved", "dismissed"},
        AlertState.ACKNOWLEDGED.value: {"resolved", "dismissed"},
        AlertState.RESOLVED.value: {"reopened"},
        AlertState.DISMISSED.value: {"reopened"},
    }
    if event_type not in allowed.get(current_state, set()):
        raise ValueError(f"event {event_type} is invalid from alert state {current_state}")


@dataclass(frozen=True, slots=True)
class GoogleChangeEventObservation:
    """Supplementary Google account-change evidence.

    ChangeEvent is intentionally not used as immediate mutation truth because the
    provider can publish it after a delay.
    """
    change_date_time: datetime
    change_resource_type: str
    change_resource_name: str
    client_type: str
    user_email: str | None
    changed_fields: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        raw=json.dumps({
            "at": self.change_date_time.isoformat(),
            "type": self.change_resource_type,
            "resource": self.change_resource_name,
            "client": self.client_type,
            "fields": list(self.changed_fields),
        },sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()
