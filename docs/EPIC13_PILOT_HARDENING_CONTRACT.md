# Epic 13 — Pilot Hardening Contract

Version target: 0.32.0

Epic 13 is a fail-closed launch-safety milestone, not customer feature breadth. A locally green package is necessary but insufficient for pilot qualification.

## Qualification layers

1. **Local package qualification** — compile, complete tests, frontend contract, TypeScript parse, secret scan, exact-ZIP rerun.
2. **Fresh deployed acceptance** — readiness and staging-acceptance reports must be no more than 24 hours old and prove API health, exact release identity, dashboard reachability, authenticated tenant access, API→queue→worker round trip, read-only Google Ads provider access, and billing entitlement when required.
3. **Fresh external operational evidence** — backup/PITR configuration, real restore drill, privileged-access review, security review, observability alerts, incident-response drill, reconciliation/rollback drill, and pilot-tenant setup.

Missing, pending, stale, future-dated or mismatched evidence fails the gate. No flag converts absent operational evidence into pass.

## Google Ads read-only probe

Durable job `pilot_google_ads_read_probe` uses the production credential resolver and reads only the exact customer profile. It returns customer ID, safe account metadata, `test_account`, API version and `external_effect=read_only`. It never returns credential references and contains no mutation executor. Only tenant Admin/Owner can queue it.

Google test accounts are used in staging because they cannot serve ads; therefore they validate credentials/configuration/query paths, not real impressions, conversions, cost or recovery economics.

## Worker health

The long-running worker exposes internal `/startup` and `/health` endpoints when `RECOVERY_WORKER_HEALTH_PORT` is configured. These endpoints intentionally do not call PostgreSQL, Google Ads, Razorpay or Gemini so dependency outages do not create liveness restart loops.

## Recovery/observability boundary

Cloud Monitoring/Logging remains infrastructure telemetry. Recovery OS Monitoring remains advertiser/product monitoring. Backup/PITR configuration is not a restore drill; the restore drill must use a disposable target.

## First real advertiser

The first real advertiser starts read-only with `google_ads_mutations=false`, exact customer identity/currency/timezone verification, read-only sync, Business Truth and Measurement Integrity review. Only after those checks may mutations be explicitly enabled; the first write remains human-approved with validate-only and exact provider read-back.

Razorpay Test Mode is integration evidence, not live merchant activation evidence.
