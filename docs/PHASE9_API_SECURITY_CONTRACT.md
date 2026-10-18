# Phase 9 API Security Contract

The backend must preserve all of the following invariants.

1. A request without a verified end-user JWT cannot access tenant data.
2. A valid JWT alone grants no tenant access.
3. Tenant access comes only from an active database membership.
4. A disabled application user is denied even with a cryptographically valid JWT.
5. Viewer/analyst roles cannot approve or execute Google Ads mutations.
6. Business Truth submitter/time are server-owned fields.
7. Business Truth is bound to one exact Google Ads account and cannot be reused across accounts.
8. Business Truth version history cannot branch or skip via the public API.
9. Every queued side-effecting operation uses an idempotency key.
10. The same idempotency key with different canonical inputs returns a conflict.
11. Mutation execution requires an approved immutable proposal.
12. A proposal already applied cannot be applied again; a fresh proposal is required.
13. Rollback requires a recorded applied Google resource and must reject already rolled-back actions.
14. Authorization errors do not reveal whether another tenant/resource exists.
15. Validation responses do not echo complete request bodies.
16. CORS wildcard origins are rejected by environment configuration.
17. Browser clients never receive/use backend database secrets, Google credentials, or Supabase service-role credentials.
18. The API never treats a queued job as proof that Google changed anything.
19. Financial/recovery truth remains governed by Phases 4 and 6; API permissions cannot upgrade evidence quality.

19. Different HTTP idempotency keys cannot create two apply jobs for the same proposal.
20. New Business Truth inserts must have an exact Google Ads account binding at the database layer.
21. Analysis runs are database-constrained so their Business Truth snapshot belongs to the same advertiser account.
22. Business Truth HTTP retries return the original immutable snapshot when the same Idempotency-Key/request is replayed.
