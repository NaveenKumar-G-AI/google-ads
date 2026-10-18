# Epic 9 — Reporting Contract

Version: 0.28.0

Recovery OS reporting is an evidence-export system. A generated report is an immutable snapshot of server-authoritative product state, not a live dashboard and not a client-side recomputation.

## V1 report families

- Executive Recovery
- Waste Intelligence
- Measurement Integrity
- Search Demand
- Account Health
- Change Impact
- Monthly Client
- Agency Portfolio

The arbitrary drag/drop report builder and full white-label designer remain V1.5 rather than shallow placeholders.

## Financial truth contract

Every generated snapshot carries the non-additive financial disclosure. These classes answer different questions and MUST NOT be summed into a synthetic savings number:

1. current observed candidate;
2. historical acted-on exposure;
3. projected prevented;
4. observed post-action;
5. verified recovery.

Unobserved Search spend is a coverage limitation and never becomes waste or recovery through reporting.

## Immutable generation

`report_generations` stores the canonical JSON snapshot and SHA-256. `report_artifacts` stores exact PDF/CSV bytes plus SHA-256. An old report never changes because the live account changes later.

## Static exports

CSV is UTF-8 with BOM and preserves the entire immutable snapshot.

PDF is generated server-side with WeasyPrint/Pango and Noto system-font fallback so multilingual query/client text can be shaped rather than silently discarded. The backend image installs the required Pango runtime and `fonts-noto-core`. PDF rendering performs no remote fetch and no live data lookup.

## Secure sharing

Share URLs are capability links:

- high-entropy raw token is returned only when a share is created;
- database stores only SHA-256 of the token;
- expiry is mandatory (1–90 days);
- revocation is an append-only event;
- public responses use `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Robots-Tag: noindex, nofollow`;
- public access events are append-only.

## Schedules

Schedules are durable, event-sourced worker state and use explicit IANA timezone + clock settings. Complete-period semantics:

- daily → previous complete local day;
- weekly → previous complete Monday–Sunday;
- monthly → previous complete calendar month.

The worker creates one durable `report_generation` job for a schedule occurrence. Browser timers are not authoritative.

Report generation is idempotent on the durable job ID. A worker retry reuses the exact existing generation/artifacts instead of producing a second report version.

## Email delivery safety

Scheduled email is optional. Each recipient is sent independently so recipient addresses are not disclosed to other clients. Delivery events are append-only. Once SMTP handoff for a recipient becomes ambiguous, Recovery OS records `ambiguous` and does not auto-retry that recipient, preventing duplicate client delivery.
 A retry that finds only a prior `prepared` event treats that unfinished handoff as ambiguous and does not resend.

SMTP credentials are worker-only secrets. Cloud Run Worker Pool deployment enables email only when explicitly configured.

## Authorization

- Viewer: read generated reports and artifacts.
- Analyst: read, generate, create/revoke share links, manage schedules.
- Admin/Owner: same reporting capabilities plus their broader tenant controls.

Backend permissions are authoritative.

## Data model

Migration `0017_epic09_reporting.sql` adds append-only/RLS-protected:

- `report_generations`
- `report_artifacts`
- `report_share_links`
- `report_share_events`
- `report_schedule_events`
- `report_schedule_runs`
- `report_delivery_events`

No report table becomes a new financial source of truth. Reports snapshot existing authoritative evidence.
