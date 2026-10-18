# Phase 18 research decisions — 2026-10-15

1. Cloud Run Worker Pools reached GA in April 2026 and are explicitly intended for continuous background work. This is a better semantic fit for the durable polling worker than relying on idle request-driven service instances.
2. Cloud Run services now support startup, liveness, and readiness HTTP probes. `/healthz` and `/readyz` are intentionally different.
3. Worker Pools use a fixed instance count and do not autoscale; V1 starts with one worker. The queue/lease model already supports adding more workers later.
4. Secret Manager references are used rather than embedding backend credentials in deploy scripts or container images.
5. Supabase's current production maturity guidance recommends migrations and separate staging/production environments, restricted production access, and PITR as data grows.
6. Vercel/Next.js `NEXT_PUBLIC_*` variables are browser-visible at build time. The dashboard therefore exposes only the Supabase project URL and publishable key; Recovery API base URL remains server-side.
7. Database migration rollback is deliberately not automated. Immutable evidence/audit migrations are forward-only; database disaster recovery uses backup/PITR and external-effect reconciliation.
