# Phase 18 — Deployment & Operations Contract

## Chosen production topology

- **API:** Google Cloud Run service (HTTP, autoscaled, request-based service).
- **Durable worker:** Google Cloud Run Worker Pool with a fixed initial instance count of 1.
- **Database/Auth:** Supabase PostgreSQL + Supabase Auth.
- **Dashboard:** Vercel, with Next.js server-side auth proxying to the API.
- **Secrets:** Google Secret Manager for backend/worker; Vercel encrypted environment variables for the dashboard.

Cloud Run Worker Pools are used because the Recovery worker performs continuous polling/background work and does not need a public HTTP endpoint. The API and worker use the **same immutable backend image** with different commands.

## Hard deployment invariants

1. `/healthz` proves only that the API process is alive.
2. `/readyz` proves database connectivity **and exact migration-byte integrity**. It fails with 503 and does not expose SQL errors.
3. Production CORS origins are explicit HTTPS origins. Wildcards are forbidden.
4. Production deployment requires an operator acknowledgement that PITR or daily backups have been verified.
5. Staging billing requires a Razorpay test key; production billing requires a live key when billing is enabled.
6. Google Ads service-account key material is mounted/read server-side only.
7. Worker Pool has no public endpoint and runs `recovery-worker` with durable leases.
8. SIGTERM stops new worker claims. If Cloud Run terminates an in-flight job, existing leases/retry/reconciliation rules remain authoritative.
9. Database migrations are version-controlled and applied with `recovery-migrate`; production database edits must not be performed manually from a dashboard.
10. A deployment is not "ready" merely because containers started: `recovery-production-check` must pass against the target environment.

## Database connection policy

Use a migration-capable direct PostgreSQL connection for migrations when reachable. Runtime API/worker connections may use Supabase's session pooler where appropriate. Do not use transaction pooling for workflows that depend on session state such as the RLS context used by this product.

## Release sequence

1. Build one backend image and push by immutable digest.
2. Run `recovery-migrate` against the target database.
3. Run `recovery-production-check`.
4. Deploy/update Cloud Run API by exact image digest.
5. Verify `/healthz` and `/readyz`.
6. Deploy/update the Cloud Run Worker Pool by the same image digest.
7. Deploy the Next.js dashboard with only its three allowed environment variables.
8. Run Razorpay Test Mode checkout/webhook/reconciliation in staging.
9. Run one read-only Google Ads sync and one analysis.
10. Only after staging passes, repeat with production secrets and live billing credentials.

## Rollback

- **API:** route traffic/redeploy to the previous Cloud Run revision/image digest.
- **Worker:** deploy the previous image digest. Do not delete or rewrite durable queue rows.
- **Dashboard:** promote the previous Vercel deployment.
- **Database:** migrations are forward-only. Do not auto-reverse evidence schema migrations. Restore from backup/PITR only for a true database disaster and reconcile external Google/Razorpay effects afterward.

## Operational alarms

At minimum alert on:

- API `/readyz` failures.
- Worker Pool instance count dropping below intended count.
- `api_jobs.status='needs_reconciliation'` > 0.
- expired `running` leases persisting after the sweeper interval.
- repeated permanent job failures.
- webhook signature failures or unreconciled billing events.
- database storage/connection exhaustion.
- Supabase backup/PITR failures.

