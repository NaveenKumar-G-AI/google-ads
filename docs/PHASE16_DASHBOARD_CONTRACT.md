# Phase 16 Dashboard Contract

## Authority boundary

The dashboard is a presentation/control surface. It is not a financial calculation engine.

- PostgreSQL + domain engines remain the source of truth.
- `analysis_summaries` is immutable and written by the analysis worker.
- `verified_recovery_micros` is read from the Recovery Ledger only.
- hidden/unobserved search spend is displayed but never transformed into estimated waste.
- tenant roles are enforced by FastAPI/PostgreSQL; UI role checks only improve usability.

## Authentication

Next.js uses Supabase SSR cookie auth. Server code calls `getClaims()` before using `getSession()` solely to obtain the raw access token for forwarding to FastAPI. FastAPI independently verifies that JWT and resolves tenant membership from PostgreSQL.

## Pages

- Overview: backend workspace summary, coverage and pipeline status.
- Findings: account-scoped immutable financial findings.
- Proposals: exact proposal + immutable decision + latest mutation state.
- Recovery: account-scoped Recovery Ledger with all four money classes separated.
- Data status: sync, Business Truth and analysis orchestration.

## Dangerous actions

Approval does not directly mutate Google Ads. Apply/rollback forms only enqueue existing Phase-10 worker jobs. Validation-only, proposal fingerprinting, resource read-back and rollback identity remain mandatory.
