# Deployment templates

These files intentionally contain **secret references only**, not secret values.

## Backend image

`Dockerfile.backend` produces one non-root Python image for the API and Worker Pool.

## Cloud Run API

`gcloud-api.ps1` deploys the API with `/healthz` startup/liveness probes and `/readyz` readiness probing.

The service remains publicly reachable because Supabase bearer authentication and Razorpay webhooks enter through HTTP. Application endpoints still enforce JWT/tenant authorization.

## Cloud Run Worker Pool

`gcloud-worker.ps1` deploys the same image as a Worker Pool and overrides the command to `recovery-worker`.

Worker Pools have no public load-balanced URL. Start V1 with one instance.

## Database migrations

Use a migration-capable direct PostgreSQL connection when available:

```powershell
$env:DATABASE_URL="postgresql://..."
recovery-migrate
```

Runtime API/worker DSNs may use a session pooler when that is the appropriate Supabase connection path. Do not use transaction pooling for this product's session-context/RLS workflows.

## Dashboard

Deploy `web/` to Vercel. `NEXT_PUBLIC_*` values are browser-visible and therefore only the Supabase project URL and publishable key are allowed there.

## Phase 19 release gate

For a staging release, prefer `release-staging.ps1`. It builds one image, resolves it to an immutable Artifact Registry digest, applies migrations, deploys the same digest to API + Worker Pool, optionally deploys Vercel, writes a release manifest, and runs `recovery-staging-accept` when a staging admin bearer token and tenant ID are supplied.

Cloud Run worker pools accept image digests directly and create immutable revisions. V1 acceptance requires the API and worker to report the exact same `RECOVERY_RELEASE_ID` through the deployment probe round trip.

## Epic 13 pilot hardening

Use `pilot-staging.ps1` for the controlled staging rehearsal. It requires a selected Google Ads account, full billing acceptance, deployed read-only Google Ads provider proof, and Google `test_account=true` enforcement.

The worker exposes `/startup` and `/health` on `RECOVERY_WORKER_HEALTH_PORT`. Apply Worker Pool probes via `configure-worker-health.py`; default mode is validation only.

Use `pilot-cloudsql-backup-check.ps1` and `pilot-observability-check.ps1` to capture provider configuration evidence. Backup configuration is not a restore drill.

Run `recovery-pilot-gate` only after all real external review/drill evidence exists. Example evidence files intentionally remain `pending` and cannot qualify unchanged.
