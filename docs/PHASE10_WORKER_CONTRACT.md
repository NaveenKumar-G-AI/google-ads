# Phase 10 worker contract

## Job lifecycle

`queued -> running -> succeeded | failed | needs_reconciliation`

A retry moves a safe job back to `queued` with a future `available_at`. Expired leases may be
reclaimed only when no unresolved external effect is in-flight.

## Lease fencing

Every claim has `(worker_id, run_token, lease_expires_at)`. Heartbeats and transitions require
that exact ownership. Losing the lease means the old worker stops writing job state.

## Attempt budget

Attempts are durable. Transient retries use bounded exponential backoff and stop at
`max_attempts`. Permanent validation/configuration failures are not retried.

## Mutation contract

1. Re-read immutable proposal + approval from PostgreSQL.
2. Re-read current Google state (preflight).
3. Apply requests run `validate_only` first.
4. Persist external effect as `in_flight` **before** the live mutate call.
5. Execute one live mutate.
6. Read back exact Google resource / verify removal.
7. Persist immutable mutation event.
8. Commit external effect and job.

If step 5 has an ambiguous exception, do not replay automatically.

## Rollback contract

Rollback targets the exact Google `resource_name` created by the recorded apply mutation. If
that resource is already absent before rollback, desired state is achieved but attribution is
not claimed.

## Worker database credential

The queue is cross-tenant by design, whereas browser/API data access is tenant-scoped. The
worker therefore requires a dedicated backend database role/DSN with only the required schema
privileges. It must never be shipped to the browser.
