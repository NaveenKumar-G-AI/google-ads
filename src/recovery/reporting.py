from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import csv
import hashlib
import io
import json
import os
import secrets
from typing import Any, Iterable, Mapping
from uuid import UUID
from zoneinfo import ZoneInfo

from recovery.db.canonical import canonical_payload


REPORT_SCHEMA_VERSION = "recovery-report.v1"
REPORT_TEMPLATE_VERSION = "2026-10-16.1"


class ReportType(str, Enum):
    EXECUTIVE_RECOVERY = "executive_recovery"
    WASTE = "waste"
    MEASUREMENT_INTEGRITY = "measurement_integrity"
    SEARCH_DEMAND = "search_demand"
    ACCOUNT_HEALTH = "account_health"
    CHANGE_IMPACT = "change_impact"
    MONTHLY_CLIENT = "monthly_client"
    AGENCY_PORTFOLIO = "agency_portfolio"


class ReportScope(str, Enum):
    ORGANIZATION = "organization"
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"


REPORT_SCOPE_RULES: dict[ReportType, frozenset[ReportScope]] = {
    ReportType.EXECUTIVE_RECOVERY: frozenset({ReportScope.ORGANIZATION, ReportScope.PORTFOLIO, ReportScope.ACCOUNT}),
    ReportType.WASTE: frozenset({ReportScope.ACCOUNT}),
    ReportType.MEASUREMENT_INTEGRITY: frozenset({ReportScope.ACCOUNT}),
    ReportType.SEARCH_DEMAND: frozenset({ReportScope.ACCOUNT}),
    ReportType.ACCOUNT_HEALTH: frozenset({ReportScope.ACCOUNT}),
    ReportType.CHANGE_IMPACT: frozenset({ReportScope.ACCOUNT}),
    ReportType.MONTHLY_CLIENT: frozenset({ReportScope.ACCOUNT}),
    ReportType.AGENCY_PORTFOLIO: frozenset({ReportScope.ORGANIZATION, ReportScope.PORTFOLIO}),
}

DATE_BOUND_REPORTS = frozenset({ReportType.WASTE, ReportType.SEARCH_DEMAND, ReportType.MONTHLY_CLIENT})


@dataclass(frozen=True, slots=True)
class ReportRequest:
    report_type: ReportType
    scope_kind: ReportScope
    scope_id: str
    period_start: date | None = None
    period_end: date | None = None

    def __post_init__(self) -> None:
        if self.scope_kind not in REPORT_SCOPE_RULES[self.report_type]:
            raise ValueError(f"{self.report_type.value} does not support {self.scope_kind.value} scope")
        if not self.scope_id.strip():
            raise ValueError("scope_id is required")
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must be supplied together")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be <= period_end")
        if self.report_type in DATE_BOUND_REPORTS and self.period_start is None:
            raise ValueError(f"{self.report_type.value} requires an explicit reporting period")
        if self.period_start and self.period_end and (self.period_end - self.period_start).days > 366:
            raise ValueError("reporting period cannot exceed 367 calendar days")


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    schedule_id: UUID
    report_type: ReportType
    scope_kind: ReportScope
    scope_id: str
    frequency: str
    timezone_name: str
    hour: int
    minute: int
    weekday: int | None
    day_of_month: int | None
    recipients: tuple[str, ...]
    enabled: bool

    def __post_init__(self) -> None:
        if self.frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("frequency must be daily, weekly or monthly")
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise ValueError("invalid schedule hour/minute")
        ZoneInfo(self.timezone_name)
        if self.weekday is not None and not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be between 0 and 6")
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 28:
            raise ValueError("day_of_month must be between 1 and 28")
        if len(self.recipients) > 50:
            raise ValueError("a schedule can have at most 50 recipients")
        for email in self.recipients:
            if "@" not in email or len(email) > 320 or any(ch.isspace() for ch in email):
                raise ValueError("invalid schedule recipient")


def financial_disclosure() -> dict[str, Any]:
    return {
        "classes_are_non_additive": True,
        "current_observed_candidate": "Latest observed candidate evidence. Not recovered money.",
        "historical_acted_on_exposure": "Observed exposure tied to interventions. Not recovered money.",
        "projected_prevented": "Forward projection from an observed baseline. Not verified recovery.",
        "observed_post_action": "Descriptive post-action observation. Not causal proof.",
        "verified_recovery": "Only case-linked causally verified recovery may enter this class.",
        "unobserved_search_spend": "Coverage limitation. Never extrapolated into waste or recovery.",
    }


def canonical_report_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = canonical_payload(dict(payload))
    if value.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("report snapshot schema_version mismatch")
    if not value.get("generation_id"):
        raise ValueError("report snapshot generation_id is required")
    disclosure = value.get("financial_disclosure")
    if not isinstance(disclosure, dict) or disclosure.get("classes_are_non_additive") is not True:
        raise ValueError("report snapshot must carry the non-additive financial disclosure")
    return value


def report_snapshot_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(canonical_report_snapshot(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def new_share_token(tenant_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    token = f"{tenant_id}.{secret}"
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_share_tenant(token: str) -> UUID:
    if len(token) > 200 or "." not in token:
        raise ValueError("invalid report share token")
    prefix, secret = token.split(".", 1)
    if len(secret) < 32:
        raise ValueError("invalid report share token")
    return UUID(prefix)


def share_token_sha256(token: str) -> str:
    parse_share_tenant(token)
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def scheduled_period(*, frequency: str, scheduled_for: datetime, timezone_name: str) -> tuple[date, date]:
    if scheduled_for.tzinfo is None or scheduled_for.utcoffset() is None:
        raise ValueError("scheduled_for must be timezone-aware")
    local = scheduled_for.astimezone(ZoneInfo(timezone_name))
    today = local.date()
    if frequency == "daily":
        d = today - timedelta(days=1)
        return d, d
    if frequency == "weekly":
        this_monday = today - timedelta(days=today.weekday())
        end = this_monday - timedelta(days=1)
        return end - timedelta(days=6), end
    if frequency == "monthly":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        return end.replace(day=1), end
    raise ValueError("unsupported schedule frequency")


def next_schedule_due(*, frequency: str, timezone_name: str, hour: int, minute: int, after: datetime, weekday: int | None = None, day_of_month: int | None = None) -> datetime:
    if after.tzinfo is None or after.utcoffset() is None:
        raise ValueError("after must be timezone-aware")
    tz = ZoneInfo(timezone_name)
    local = after.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if frequency == "daily":
        if candidate <= local:
            candidate += timedelta(days=1)
    elif frequency == "weekly":
        target = 0 if weekday is None else weekday
        delta = (target - candidate.weekday()) % 7
        candidate += timedelta(days=delta)
        if candidate <= local:
            candidate += timedelta(days=7)
    elif frequency == "monthly":
        target_day = 1 if day_of_month is None else day_of_month
        candidate = candidate.replace(day=target_day)
        if candidate <= local:
            if candidate.month == 12:
                candidate = candidate.replace(year=candidate.year + 1, month=1, day=target_day)
            else:
                candidate = candidate.replace(month=candidate.month + 1, day=target_day)
    else:
        raise ValueError("unsupported schedule frequency")
    return candidate.astimezone(timezone.utc)


def _flatten(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key in sorted(value):
            new = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten(value[key], new)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            yield from _flatten(item, f"{prefix}[{idx}]")
    else:
        if value is None:
            text = ""
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        yield prefix, text


def render_report_csv(snapshot: Mapping[str, Any]) -> bytes:
    payload = canonical_report_snapshot(snapshot)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["report_generation_id", payload["generation_id"]])
    writer.writerow(["report_type", payload["report_type"]])
    writer.writerow(["generated_at", payload["generated_at"]])
    writer.writerow([])
    writer.writerow(["path", "value"])
    for path, value in _flatten(payload):
        writer.writerow([path, value])
    return out.getvalue().encode("utf-8-sig")


def render_report_pdf(snapshot: Mapping[str, Any]) -> bytes:
    """Generate a static Unicode-safe evidence PDF from the immutable snapshot.

    WeasyPrint/Pango is used deliberately instead of a single embedded TTFont so
    multilingual search queries and client names can use system font fallback and
    complex-script shaping. The PDF contains no remote assets and performs no live
    data lookup or client-side recomputation.
    """
    payload = canonical_report_snapshot(snapshot)
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("weasyprint is required for PDF report generation") from exc
    from html import escape

    def h(v: Any) -> str:
        return escape(str(v if v is not None else ""), quote=True)

    scope = payload.get("scope") or {}
    period = payload.get("period") or {}
    title = payload.get("title") or str(payload["report_type"]).replace("_", " ").title()
    period_text = f"{period.get('start') or 'as-of'} to {period.get('end') or 'as-of'}"
    meta_rows = [
        ("Generation", payload["generation_id"]),
        ("Generated", payload["generated_at"]),
        ("Scope", f"{scope.get('kind','')} - {scope.get('name','') or scope.get('id','')}"),
        ("Period", period_text),
        ("Template", f"{payload.get('template_version')} / {payload.get('schema_version')}"),
    ]

    section_html: list[str] = []
    for section in payload.get("sections") or []:
        rows = list(_flatten(section.get("data")))[:180]
        row_html = []
        for path, value in rows:
            display = value if len(value) <= 600 else value[:597] + "..."
            row_html.append(f"<tr><td class='field'>{h(path)}</td><td>{h(display)}</td></tr>")
        basis = section.get("time_basis")
        basis_html = f"<div class='basis'>Time basis: {h(basis)}</div>" if basis else ""
        section_html.append(
            f"<section><h2>{h(section.get('title') or section.get('key') or 'Section')}</h2>{basis_html}"
            f"<table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>{''.join(row_html)}</tbody></table></section>"
        )

    disclosures = "".join(f"<li>{h(x)}</li>" for x in (payload.get("disclosures") or []))
    meta_html = "".join(f"<tr><th>{h(k)}</th><td>{h(v)}</td></tr>" for k, v in meta_rows)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
@page {{ size:A4; margin:15mm 16mm 16mm; @bottom-left {{ content:"Immutable Recovery OS report · {h(payload['generation_id'])}"; font-size:7pt; color:#68707a; }} @bottom-right {{ content:"Page " counter(page) " of " counter(pages); font-size:7pt; color:#68707a; }} }}
* {{ box-sizing:border-box; }}
body {{ font-family:"Noto Sans","Noto Sans Tamil","Noto Sans Devanagari","Noto Sans Telugu","Noto Sans Kannada","Noto Sans Malayalam","Noto Sans Bengali","Noto Sans Gujarati",sans-serif; color:#15181d; font-size:8.6pt; line-height:1.35; }}
h1 {{ font-size:19pt; line-height:1.15; margin:0 0 8mm; font-weight:650; }}
h2 {{ font-size:12.5pt; margin:7mm 0 2mm; page-break-after:avoid; }}
.meta {{ width:100%; border-collapse:collapse; margin-bottom:6mm; }}
.meta th {{ width:32mm; text-align:left; color:#5e6670; font-weight:500; padding:1.2mm 2mm; }} .meta td {{ padding:1.2mm 2mm; }}
.contract {{ border-left:3px solid #667085; padding:2mm 3mm; margin:0 0 4mm; background:#f7f8fa; }}
.contract strong {{ display:block; margin-bottom:1mm; }}
section {{ break-inside:auto; }} .basis {{ font-size:7.4pt; color:#69727d; margin-bottom:1.4mm; }}
table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
thead {{ display:table-header-group; }} tr {{ break-inside:avoid; }}
th,td {{ border:0.25pt solid #d7dce2; text-align:left; vertical-align:top; padding:1.4mm 2mm; overflow-wrap:anywhere; white-space:pre-wrap; }}
thead th {{ background:#f0f2f4; color:#5a626d; font-size:7.4pt; font-weight:600; }}
td.field {{ width:37%; color:#5d6671; font-size:7.6pt; }}
ul {{ padding-left:5mm; color:#59636e; }}
.footer-note {{ margin-top:7mm; font-size:7.3pt; color:#68727d; }}
</style></head><body>
<h1>{h(title)}</h1>
<table class="meta">{meta_html}</table>
<div class="contract"><strong>Financial evidence contract</strong>These classes are non-additive. Observed candidate, historical acted-on exposure, projected prevented spend, post-action observation, and verified recovery answer different questions. Projected prevented is not verified recovery.</div>
{''.join(section_html)}
{f'<section><h2>Disclosures</h2><ul>{disclosures}</ul></section>' if disclosures else ''}
<div class="footer-note">Snapshot SHA is verified by the stored report artifact metadata. Financial classes are non-additive. Verified recovery requires case-linked causal evidence.</div>
</body></html>"""
    return HTML(string=html, base_url="about:blank").write_pdf()

