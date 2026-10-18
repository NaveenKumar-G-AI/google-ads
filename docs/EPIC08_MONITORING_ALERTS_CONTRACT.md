# Epic 8 — Monitoring & Alerts Contract

Version: 0.27.0

## Purpose

Monitoring is an operating-safety layer. It does not create waste or recovery money merely because a condition is unusual.

## Truth model

Recovery OS separates monitors into two classes.

### Structural monitors

These are based on directly observable product/provider state:

- data freshness
- measurement integrity
- failed job health
- campaign serving state
- external-effect reconciliation

### Statistical monitors

These compare observed performance against an explicitly configured baseline and are disabled by default:

- spend anomaly
- conversion drop

There is no hidden AI anomaly score. Every statistical threshold and minimum-evidence gate is inspectable in policy configuration.

## Alert state is event sourced

Alert truth is derived from immutable records:

- `monitor_alert_instances` anchors one incident generation.
- `monitor_alert_events` records opened, observed, acknowledged, assigned, resolved, dismissed, reopened, commented, and automatic-resolution events.
- An active incident is re-observed without creating duplicate alerts.
- A condition that genuinely clears and later returns creates a new generation.
- Manual resolution alone does not prove the underlying condition disappeared.

## Policy truth is event sourced

`monitor_policy_events` is append-only. The latest organization-level event establishes the organization default. The latest account event overrides it for that account.

## Statistical minimum evidence gates

Spend anomaly exposes:

- baseline days
- recent days
- spend multiplier
- minimum cost delta
- minimum baseline daily spend

Conversion drop exposes:

- baseline days
- recent days
- conversion ratio threshold
- minimum baseline daily conversions
- minimum recent spend ratio
- configured conversion maturity lag from Measurement Integrity

These gates prevent low-volume noise from becoming incidents.

## Measurement dependency

Conversion-drop monitoring runs only when Measurement Integrity allows conversion-dependent claims. It also excludes provider data inside the configured conversion-maturity lag window.

## Provider semantics

Campaign serving uses Google `campaign.primary_status` and `campaign.primary_status_reasons` as observed provider evidence. These are output-only diagnostics and may take time to reflect recent account changes. Therefore an alert records the exact provider status/reasons and does not claim instantaneous causal truth.

Google ChangeEvent remains supplementary audit evidence. It may lag by roughly three minutes and is limited to a recent history window, so it is not used as immediate mutation truth.

Google landing-page reporting exposes performance/page-experience metrics such as mobile-friendly-click percentage and speed score. Those fields do not prove an HTTP 404/5xx response. Epic 8 therefore does not claim a landing page is technically broken without a direct HTTP-health evidence source.

## Query recurrence

`query_recurrence` is reserved but disabled. It is intentionally not offered as an active policy until the implementation can link a reappearing query to an exact previously applied intervention without inferring recurrence from aggregate volume.

## Financial boundary

Every alert evidence payload produced by the current monitors states that it is diagnostic/non-causal where applicable. Alert counts, severities, spend changes, and conversion changes are never automatically added to Waste Intelligence or Recovery Center financial totals.

## Durable execution

Monitoring uses the durable job type:

`monitoring_evaluation`

A successful Google Ads sync schedules a post-sync monitoring evaluation. Authorized Analysts/Admins/Owners can also queue a manual evaluation using an idempotency key.

## Permissions

- Viewer: monitoring read only
- Analyst: read, alert lifecycle management, manual evaluation
- Admin/Owner: all Analyst rights plus policy changes

Backend authorization is authoritative; frontend visibility is not the security boundary.
