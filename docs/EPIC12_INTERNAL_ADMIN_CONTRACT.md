# Epic 12 — Internal Admin & Support Operations Contract

Version: 0.31.0

## Purpose

The internal surface is an operator-safety system, not a hidden customer superuser mode. Platform access is authorized separately from tenant roles and must never confer customer membership, impersonation, or unrestricted cross-tenant SQL access.

## Authorization plane

Platform roles:

- `support_viewer` — read tenant diagnostics, support cases, and incidents.
- `support_engineer` — support write + allow-listed remediation + incident updates.
- `platform_admin` — all platform permissions, including operational kill switches.
- `security_auditor` — read diagnostics/security evidence, no remediation.

A customer Owner/Admin/Analyst/Viewer role has no platform access by itself.

`platform_operator_events` is append-only. The web API exposes no operator-grant endpoint. Initial grants/revocations require the privileged maintenance path:

```bash
RECOVERY_MIGRATION_DATABASE_URL=... \
  recovery-platform-operator <user_uuid> platform_admin \
  --reason "Initial production platform administrator"
```

The selected migration role must have the database privilege needed to write the FORCE-RLS protected operator registry. The normal web API database role is intentionally insufficient.

## Tenant isolation

The platform tenant directory stores only:

- tenant UUID;
- slug;
- display name;
- first-seen timestamp.

It does not mirror customer evidence.

After an operator selects a tenant, diagnostics set the exact tenant RLS context and query the existing customer tables under that context. Epic 12 does not introduce a web-accessible BYPASSRLS path.

## No impersonation

The internal product has no "login as customer" action and does not mint customer tenant memberships. Support operators cannot use the internal UI to create proposal approvals, perform customer-facing decisions, or masquerade as a customer actor.

## Safe remediation

Automatic retry is deliberately restricted to terminal `failed` jobs in this allow-list:

- `google_ads_sync`
- `analysis_run`
- `semantic_shadow`
- `monitoring_evaluation`
- `google_ads_account_discovery`
- `deployment_probe`

Unsafe/consequential jobs are excluded, including:

- Google Ads apply mutation;
- rollback mutation;
- report generation/email delivery;
- billing provider mutations.

A safe retry creates a new durable job and an append-only `internal_remediation_events` audit record. The old job is never rewritten to hide the failure.

`needs_reconciliation` external effects are diagnostic evidence and are never blindly replayed.

## Operational kill switches

V1 has exactly three tenant-scoped operational controls:

- `google_ads_mutations`
- `billing_mutations`
- `scheduled_report_email`

They default to enabled. Only `platform_admin` can change them, and every state change is append-only with a required reason.

The Google Ads mutation control is enforced twice:

1. when a new mutation job is queued;
2. again immediately before the worker's external apply effect.

Rollback remains available when applies are disabled so an emergency control cannot prevent a safety reversal.

Billing mutation control blocks provider-changing checkout/plan/cancellation actions while leaving provider reads/reconciliation available.

Scheduled-report-email control suppresses outbound email while still allowing immutable report generation.

## Support cases

Support case anchors are immutable. Notes, assignment/status changes, close/reopen transitions are append-only `internal_support_case_events`.

Support cases can be categorized as product, data, Google Ads, billing, integration, security, access, or other.

## Platform incidents

`platform_incident_events` records operator context and customer-impact status. It is not a replacement for Google Cloud telemetry.

Cloud Run metrics/logs/Error Reporting remain the infrastructure observability source. The Recovery OS incident log records human decisions and communication state.

## AI release diagnostics

Tenant diagnostics expose the existing semantic release registry and its latest activate/deactivate/revoke event. Epic 12 does not create a second AI release truth source.

## Release observations

Internal release history is derived from successful `deployment_probe` durable jobs. This reuses the existing staging-acceptance proof of API/queue/worker release identity instead of adding a manually editable release-history table.

## Data operations boundary

Epic 12 intentionally does not provide arbitrary SQL, arbitrary row editing, destructive tenant deletion, or mass evidence rewriting.

Customer export/delete/retention workflows belong to the canonical Security & Data domain where legal retention, referential integrity, billing records, immutable audit evidence, and provider deletion semantics can be defined explicitly.

## Audit protection

Internal support/remediation/control/incident evidence is append-only. This follows the product rule that privileged functions must be separately authorized and logged; operators are not allowed to edit away prior privileged actions.
