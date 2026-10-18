# Phase 8 research decisions — production persistence & provenance

## 1. PostgreSQL is the source of record

Phase 8 targets PostgreSQL rather than a document store. The data model needs relational
constraints across tenant → account → sync run → source observation → analysis → approval
→ mutation → recovery verification. Financial identity and provenance must be enforced by
the database as well as Python.

PostgreSQL `INSERT ... ON CONFLICT` provides an atomic insert-or-conflict primitive under
concurrency. We use uniqueness constraints plus explicit idempotency request IDs rather
than "check then insert" logic outside a transaction.

## 2. Same logical Google row can have multiple immutable metric versions

Conversion lag means refreshing the same historical reporting window can legitimately
change conversion metrics. Therefore:

- logical observation identity excludes mutable metrics;
- each distinct full payload gets its own immutable version;
- each sync chunk records which version it observed;
- a later refresh is a new sync run, not an overwrite.

This is necessary to reconstruct exactly what the engine knew when an older finding was
created.

## 3. Retry idempotency is not refresh deduplication

A `request_id` identifies one intended sync execution. Retrying the same request reuses the
same sync run. A genuinely new refresh must use a new request ID even when it covers the
same dates.

Within one run, a completed chunk may be replayed only if its order-independent checksum
matches. If it differs, the run is rejected and a new sync must begin. This avoids silently
mixing data captured at different moments.

## 4. Chunk checksum must not depend on API row order

Google reporting order is not treated as a semantic guarantee. Before hashing, rows are
sorted by stable identity + payload hash. The same data in a different transport order
therefore produces the same idempotency fingerprint.

## 5. Immutable evidence, mutable operational state

Operational tables such as `sync_runs`, `sync_chunks`, `google_ads_accounts`, and
`analysis_runs` may change status. Evidence and decision history are append-only:

- source observation keys/versions/occurrences;
- inventory snapshots;
- Business Truth snapshots;
- analysis artifacts;
- proposal decision events;
- mutation events;
- recovery ledger entries;
- audit events.

PostgreSQL triggers reject UPDATE and DELETE on these append-only tables.

## 6. Tenant isolation exists in the database

Every customer-owned row carries `tenant_id`. Row Level Security is enabled and forced.
The backend sets `recovery.tenant_id` locally inside each transaction; missing tenant
context means no tenant rows are visible.

This RLS design is a backend defense-in-depth model. It is **not** authorization for an
untrusted browser with a direct SQL/Data-API connection, because a client capable of
setting arbitrary database session variables would defeat it. If direct frontend database
access is introduced later, RLS must instead derive membership from authenticated JWT/user
identity. The V1 backend must keep direct database credentials server-side.

## 7. Secrets are references, not database payloads

The production schema contains `credential_ref` and an optional SHA-256 fingerprint. It
does not contain developer tokens, OAuth refresh tokens, service-account private keys, or
raw service-account JSON. Secret bytes belong in environment/secret-manager infrastructure.

## 8. Approval and mutation remain distinct events

An analysis proposal is immutable. Approval is an append-only event tied to the exact
proposal fingerprint. A mutation event can only reference an approved proposal decision.
Applied/rolled-back events require the exact Google resource name.

## 9. Recovery remains a separate financial truth

The database stores historical candidate, projected prevented, observed post-action spend,
and causally verified recovery as separate columns. A non-zero verified recovery amount is
invalid unless causal status is `verified`.

## 10. Audit history is tamper-evident at the application boundary

Audit events are append-only and form a per-aggregate SHA-256 chain. A transaction-scoped
PostgreSQL advisory lock serializes writers for the same aggregate while the next hash is
created. This helps expose missing/reordered events. It is not a substitute for external
WORM storage against a database superuser; that can be added later for enterprise audit
requirements.

## 11. PostgreSQL transaction semantics are part of correctness

Chunk persistence occurs inside one database transaction. If any row/version/occurrence or
chunk finalization fails, the transaction rolls back. PostgreSQL transaction-scoped advisory
locks are used only where application-level serialization is required; they release at the
transaction boundary.

## 12. Supabase is optional infrastructure, not part of the data contract

The schema uses standard PostgreSQL primitives and can run on Supabase, managed Postgres,
or self-hosted PostgreSQL. If Supabase is used, the service-role/secret key remains backend
only. Exposed schemas require RLS plus least-privilege grants.
