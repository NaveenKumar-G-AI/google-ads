# Phase 8 production data contract

## Financial/provenance invariants

1. Money values are integer micros in typed columns; binary floats are forbidden in audit fingerprints.
2. Search-term logical identity does not contain mutable conversion metrics.
3. A changed historical metric creates a new immutable version, never an UPDATE.
4. A completed chunk cannot be replaced by different bytes under the same sync request.
5. Search-term visible spend cannot exceed the comparable campaign/network denominator for a chunk.
6. A sync cannot be marked complete until completed chunks contiguously cover the requested date window.
7. Inventory captured for a sync is immutable; if it changes during the same request, start a new sync.
8. Business Truth snapshots are immutable and addressed by their truth fingerprint.
9. Analysis artifacts are immutable inside an analysis run.
10. Approval must refer to the exact stored proposal ID and fingerprint.
11. Mutation must refer to an approved proposal decision.
12. Applied/rolled-back mutation events require the exact Google Ads resource name.
13. `verified_recovery_micros > 0` requires causal status `verified` and verified live configuration in the domain model.
14. Raw integration secret material is not persisted in the application database.
15. Every tenant-owned table is protected by tenant RLS in addition to application authorization.

## Refresh semantics

```text
same request_id + same completed chunk bytes
    => idempotent retry / no duplicate

same request_id + different completed chunk bytes
    => hard conflict; begin a new sync

new request_id + same logical Google row + same metrics
    => existing immutable version reused, new occurrence linked

new request_id + same logical Google row + changed metrics
    => new immutable metric version + new occurrence
```

## Why this matters

A finding made on October 1 must still be reconstructable after Google reports a late
conversion on October 5. The product must be able to answer both:

- "What does the account look like now?"
- "What exact data did the engine use when it made this older recommendation?"

Those are different questions, and the Phase-8 schema preserves both answers.
