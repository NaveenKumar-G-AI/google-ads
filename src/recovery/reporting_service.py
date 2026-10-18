from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from recovery.reporting import (
    REPORT_SCHEMA_VERSION, REPORT_TEMPLATE_VERSION, ReportRequest, ReportScope, ReportType,
    canonical_report_snapshot, financial_disclosure,
)


class ReportDataSource(Protocol):
    def list_accounts(self, *, tenant_id: UUID) -> list[dict[str, Any]]: ...
    def portfolio_detail(self, *, tenant_id: UUID, portfolio_id: UUID) -> dict[str, Any]: ...
    def workspace_summary(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def recovery_center_overview(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]: ...
    def recovery_center_cases(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, causal_status: str | None, limit: int) -> list[dict[str, Any]]: ...
    def recovery_center_breakdown(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None, dimension: str) -> dict[str, Any]: ...
    def recovery_center_timeline(self, *, tenant_id: UUID, account_id: UUID | None, portfolio_id: UUID | None) -> dict[str, Any]: ...
    def waste_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None) -> dict[str, Any]: ...
    def waste_intelligence_queries(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, family: str | None, disposition: str | None, page: int, page_size: int) -> dict[str, Any]: ...
    def measurement_integrity_overview(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def measurement_conversion_actions(self, *, tenant_id: UUID, account_id: UUID) -> list[dict[str, Any]]: ...
    def measurement_goals(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def measurement_lag(self, *, tenant_id: UUID, account_id: UUID) -> dict[str, Any]: ...
    def search_intelligence_overview(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None) -> dict[str, Any]: ...
    def search_intelligence_terms(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, query: str | None, network: str | None, fit: str | None, sort: str, direction: str, page: int, page_size: int) -> dict[str, Any]: ...
    def search_intelligence_breakdown(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, dimension: str) -> dict[str, Any]: ...
    def search_intelligence_ngrams(self, *, tenant_id: UUID, account_id: UUID, start: date | None, end: date | None, n: int, sort: str, limit: int, without_conversions: bool) -> dict[str, Any]: ...
    def monitoring_overview(self, *, tenant_id: UUID, account_id: UUID | None) -> dict[str, Any]: ...
    def monitoring_alerts(self, *, tenant_id: UUID, account_id: UUID | None, state: str | None, severity: str | None, monitor_type: str | None, limit: int) -> list[dict[str, Any]]: ...


def _account(repo: ReportDataSource, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
    for row in repo.list_accounts(tenant_id=tenant_id):
        if row["id"] == account_id:
            return row
    raise ValueError("report account is not accessible in this tenant")


def _scope(repo: ReportDataSource, tenant_id: UUID, req: ReportRequest) -> tuple[str, UUID | None, UUID | None]:
    if req.scope_kind is ReportScope.ORGANIZATION:
        if req.scope_id != str(tenant_id):
            raise ValueError("organization report scope_id must equal tenant_id")
        return "Organization", None, None
    if req.scope_kind is ReportScope.ACCOUNT:
        aid = UUID(req.scope_id)
        a = _account(repo, tenant_id, aid)
        return a.get("descriptive_name") or a.get("customer_id") or req.scope_id, aid, None
    pid = UUID(req.scope_id)
    p = repo.portfolio_detail(tenant_id=tenant_id, portfolio_id=pid)
    return p["name"], None, pid


def _section(key: str, title: str, time_basis: str, data: Any) -> dict[str, Any]:
    return {"key": key, "title": title, "time_basis": time_basis, "data": data}


def _period_text(req: ReportRequest) -> str:
    return f"{req.period_start.isoformat()} to {req.period_end.isoformat()}" if req.period_start else "current/cumulative as-of generation"


def build_report_snapshot(
    *, repo: ReportDataSource, tenant_id: UUID, generation_id: UUID, generated_by: UUID,
    request: ReportRequest, generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    scope_name, account_id, portfolio_id = _scope(repo, tenant_id, request)
    period = {"start": request.period_start.isoformat() if request.period_start else None, "end": request.period_end.isoformat() if request.period_end else None}
    sections: list[dict[str, Any]] = []
    disclosures = [
        "Generated reports are immutable snapshots. Later account changes do not rewrite this version.",
        "Financial evidence classes are non-additive and must never be presented as one combined savings total.",
        "Unobserved or privacy-hidden search spend remains a coverage limitation and is not inferred as waste.",
    ]

    rt = request.report_type
    title = rt.value.replace("_", " ").title()

    if rt is ReportType.EXECUTIVE_RECOVERY:
        recovery = repo.recovery_center_overview(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id)
        breakdown = repo.recovery_center_breakdown(tenant_id=tenant_id, account_id=account_id, portfolio_id=portfolio_id, dimension="account" if account_id is None else "leak_type")
        sections += [
            _section("recovery_summary", "Recovery proof", "current/cumulative as of generation", recovery),
            _section("recovery_breakdown", "Recovery breakdown", "latest ledger snapshot per case-linked mutation", breakdown),
        ]
        title = "Executive Recovery Report"

    elif rt is ReportType.WASTE:
        assert account_id is not None
        overview = repo.waste_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end)
        queries = repo.waste_intelligence_queries(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end, family=None, disposition=None, page=1, page_size=100)
        sections += [
            _section("waste_summary", "Waste intelligence summary", _period_text(request), overview),
            _section("query_leaks", "Observed query leakage", _period_text(request), queries),
        ]
        disclosures.append("Device/daypart/network diagnostic dimensions are not automatically financial waste claims.")
        title = "Waste Intelligence Report"

    elif rt is ReportType.MEASUREMENT_INTEGRITY:
        assert account_id is not None
        sections += [
            _section("measurement_confidence", "Measurement confidence", "latest completed measurement snapshot", repo.measurement_integrity_overview(tenant_id=tenant_id, account_id=account_id)),
            _section("conversion_actions", "Conversion actions", "latest completed measurement snapshot", repo.measurement_conversion_actions(tenant_id=tenant_id, account_id=account_id)),
            _section("goal_configuration", "Goal configuration", "latest completed measurement snapshot", repo.measurement_goals(tenant_id=tenant_id, account_id=account_id)),
            _section("conversion_lag", "Observed conversion lag", "latest completed measurement snapshot", repo.measurement_lag(tenant_id=tenant_id, account_id=account_id)),
        ]
        title = "Measurement Integrity Report"

    elif rt is ReportType.SEARCH_DEMAND:
        assert account_id is not None
        sections += [
            _section("search_overview", "Search demand overview", _period_text(request), repo.search_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end)),
            _section("top_queries", "Top observed queries", _period_text(request), repo.search_intelligence_terms(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end, query=None, network=None, fit=None, sort="cost", direction="desc", page=1, page_size=50)),
            _section("intent_breakdown", "Intent breakdown", _period_text(request), repo.search_intelligence_breakdown(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end, dimension="intent")),
            _section("top_ngrams", "Top lexical phrases", _period_text(request), repo.search_intelligence_ngrams(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end, n=2, sort="cost", limit=50, without_conversions=False)),
        ]
        title = "Search Demand Report"

    elif rt is ReportType.ACCOUNT_HEALTH:
        assert account_id is not None
        sections += [
            _section("workspace", "Account data and analysis status", "current as of generation", repo.workspace_summary(tenant_id=tenant_id, account_id=account_id)),
            _section("measurement", "Measurement integrity", "latest completed measurement snapshot", repo.measurement_integrity_overview(tenant_id=tenant_id, account_id=account_id)),
            _section("monitoring", "Active monitoring conditions", "current incident projection as of generation", repo.monitoring_overview(tenant_id=tenant_id, account_id=account_id)),
        ]
        title = "Account Health Report"

    elif rt is ReportType.CHANGE_IMPACT:
        assert account_id is not None
        sections += [
            _section("recovery_cases", "Intervention outcomes", "latest ledger snapshot per case-linked mutation", repo.recovery_center_cases(tenant_id=tenant_id, account_id=account_id, portfolio_id=None, causal_status=None, limit=300)),
            _section("recovery_timeline", "Recovery proof timeline", "cumulative end-of-day latest snapshot state", repo.recovery_center_timeline(tenant_id=tenant_id, account_id=account_id, portfolio_id=None)),
        ]
        title = "Change Impact Report"

    elif rt is ReportType.MONTHLY_CLIENT:
        assert account_id is not None
        sections += [
            _section("search", "Search demand", _period_text(request), repo.search_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end)),
            _section("waste", "Observed leakage", _period_text(request), repo.waste_intelligence_overview(tenant_id=tenant_id, account_id=account_id, start=request.period_start, end=request.period_end)),
            _section("measurement", "Measurement integrity", "latest completed measurement snapshot as of generation", repo.measurement_integrity_overview(tenant_id=tenant_id, account_id=account_id)),
            _section("monitoring", "Operational monitoring", "current incident projection as of generation", repo.monitoring_overview(tenant_id=tenant_id, account_id=account_id)),
            _section("recovery", "Recovery proof", "current/cumulative as of generation; not limited to the monthly period", repo.recovery_center_overview(tenant_id=tenant_id, account_id=account_id, portfolio_id=None)),
        ]
        disclosures.append("The Recovery section is cumulative/current as-of generation and is intentionally not relabeled as monthly recovery.")
        title = "Monthly Client Report"

    elif rt is ReportType.AGENCY_PORTFOLIO:
        recovery = repo.recovery_center_overview(tenant_id=tenant_id, account_id=None, portfolio_id=portfolio_id)
        breakdown = repo.recovery_center_breakdown(tenant_id=tenant_id, account_id=None, portfolio_id=portfolio_id, dimension="account")
        monitoring = repo.monitoring_overview(tenant_id=tenant_id, account_id=None)
        sections += [
            _section("portfolio_recovery", "Portfolio recovery proof", "current/cumulative as of generation", recovery),
            _section("account_breakdown", "Account recovery breakdown", "latest ledger snapshot per case-linked mutation", breakdown),
            _section("organization_monitoring", "Organization monitoring context", "current organization incident projection; may include accounts outside the selected portfolio", monitoring),
        ]
        disclosures.append("Organization monitoring is not filtered to portfolio in V1; this limitation is stated rather than hidden.")
        title = "Agency Portfolio Report"

    else:  # pragma: no cover
        raise ValueError("unsupported report type")

    snapshot = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "template_version": REPORT_TEMPLATE_VERSION,
        "generation_id": str(generation_id),
        "report_type": rt.value,
        "title": title,
        "scope": {"kind": request.scope_kind.value, "id": request.scope_id, "name": scope_name},
        "period": period,
        "generated_at": generated_at.isoformat(),
        "financial_disclosure": financial_disclosure(),
        "sections": sections,
        "disclosures": disclosures,
    }
    return canonical_report_snapshot(snapshot)
