# Epic 13 — Pilot SLO / Alerting Contract

Version target: 0.32.0

These are Recovery OS pilot operating targets, not Google/Razorpay/Cloud Run guarantees.

## API availability

Pilot target: **99.5% monthly successful availability** for authenticated customer API traffic, excluding announced maintenance.

## API latency

Track p50/p95/p99 by endpoint family. Do not create a launch-blocking numeric latency target before real staging/pilot samples establish a baseline.

## Durable work

- no unresolved `needs_reconciliation` job may be silently ignored;
- oldest queued-job age must be monitored;
- expired leases/repeated failures require operator investigation;
- consequential provider effects are never blindly replayed.

## Health separation

- **Cloud Run startup/liveness**: process/runtime health only.
- **Cloud Monitoring/Logging**: infrastructure and service telemetry.
- **Recovery OS Monitoring**: advertiser/product conditions such as stale data, blocked measurement and reconciliation.
- **Pilot gate**: release decision assembled from deployed acceptance and external evidence.

Data freshness and financial proof never get relaxed by an SLO. Missing evidence remains stale/pending/inconclusive according to existing truth contracts.
