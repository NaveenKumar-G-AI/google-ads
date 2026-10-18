# Epic 9 — Research Decisions

## Market floor

Current Google Ads reporting already supports saved/custom reports, downloads and scheduled report delivery. Mature PPC management products add reusable templates, multi-account reporting, PDFs/share links, schedules and white-label presentation. Recovery OS therefore cannot differentiate merely by exporting charts.

## Recovery OS differentiation

Reporting is differentiated by provenance:

- exact immutable source snapshot;
- template/schema version;
- generated-at time;
- explicit scope and period;
- artifact hashes;
- financial claim labels;
- share/delivery history;
- no conversion of projections into verified savings.

## V1 boundary

V1 deliberately ships a finite set of audited report families. Arbitrary report composition/drag-drop and white-label designer are deferred until the underlying report-component contract can preserve the same evidence semantics.

## PDF decision

A single-font ReportLab test silently omitted Tamil text. Because search queries and client names can be multilingual, the production renderer uses WeasyPrint with Pango/system Noto font fallback and was visually validated with Tamil content. This is an accuracy requirement, not styling polish.

## Delivery decision

SMTP delivery is recipient-isolated. A post-handoff error is treated as ambiguous rather than retryable because duplicate external email is a consequential side effect.
