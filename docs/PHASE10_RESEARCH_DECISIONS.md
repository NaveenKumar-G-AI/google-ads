# Phase 10 research decisions — durable worker runtime

## Accuracy goal

Queued work must survive process/network failure without silently duplicating a Google Ads
mutation or turning an uncertain external outcome into a claimed success.

## 1. PostgreSQL is the job authority

Workers claim jobs with `FOR UPDATE SKIP LOCKED`. A claim creates a unique `run_token`, lease,
and attempt record. Every heartbeat and terminal transition must still own that exact token.
This prevents an expired worker from overwriting a newer worker's result.

## 2. Safe jobs and external mutations have different retry semantics

Read-only sync/analysis jobs may retry bounded transient failures. Google Ads mutations are
non-idempotent from our application's perspective: our PostgreSQL transaction and API
idempotency key cannot be atomically committed with Google's remote mutation.

Therefore the mutation state machine is:

`prepared -> in_flight -> committed`

If an exception or worker death occurs after `in_flight`, automatic Google replay is forbidden.
The job becomes `needs_reconciliation` unless durable local evidence proves the first attempt
completed.

## 3. Google request IDs are diagnostic, not our idempotency primitive

Request IDs are retained when available for troubleshooting. They are never treated as proof
that replaying a mutation is safe.

## 4. Crash recovery prefers proof over retry

Before quarantining an expired in-flight effect, the sweep looks for an immutable matching
`mutation_events` record written after the effect entered in-flight state. If that proof exists,
the worker can finish the local effect/job without calling Google again. Otherwise it requires
reconciliation.

## 5. No universal conversion lag is assumed

Analysis jobs require an explicit `conversion_lag_days` accuracy policy. Phase 10 does not
invent one value for every advertiser/business.

## 6. Production semantic AI is not silently introduced

The worker currently runs the conservative Phase-3 lexical interpreter. Unknown meaning stays
UNKNOWN. A paid/LLM semantic model must first pass an evaluation/calibration phase before it is
allowed to create financial findings or action proposals.
