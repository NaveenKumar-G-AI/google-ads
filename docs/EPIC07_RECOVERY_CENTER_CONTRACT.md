# Epic 7 — Recovery Center Contract

Version: 0.26.0

## Purpose

Recovery Center is the financial-proof surface for Recovery OS. It is deliberately not a generic savings dashboard.

Five monetary classes remain distinct:

1. **Current observed candidate** — the latest completed analysis snapshot of potentially avoidable *observed* spend.
2. **Historical acted-on exposure** — candidate spend attached to interventions that have case-linked Recovery Ledger evidence.
3. **Projected prevented** — a historical run-rate projection. It is not observed savings and not verified recovery.
4. **Observed post-action query spend** — descriptive spend observed after the action. Reduction or absence alone is not causal proof.
5. **Verified recovery** — non-zero only when the ledger's causal status is `verified` and the action configuration satisfies the verification contract.

These classes are **non-additive**. Recovery OS does not produce a “total value” by summing them.

## Current Google measurement boundary

Google Ads direct experiment reporting provides control/treatment metrics plus statistical comparisons including point estimates, margins of error and p-values. Google recommends letting experiments run long enough to account for weekly cycles, conversion delay and learning/ramp-up effects. Recovery OS therefore keeps its existing conservative causal engine: post-action disappearance of a query is descriptive evidence, not proof of recovery.

Google conversion data is also delayed by conversion lag. Recent performance can look weaker because spend is present before all conversions have arrived. Recovery Center does not treat recent zero-conversion observations as mature financial proof without the configured Measurement Integrity policy.

Google ChangeEvent is useful audit evidence but is not causal evidence. It can lag by several minutes and only covers a bounded recent history. Recovery OS continues to use exact mutation response + resource read-back for immediate configuration proof, while financial recovery remains a separate causal question.

## Ledger identity hardening

A monetary summary is not case identity. Two different interventions can have identical monetary values. Epic 7 binds persisted ledger idempotency to the exact `mutation_event_id` whenever available. This prevents distinct cases from colliding merely because their summary numbers are equal.

## Initial ledger bootstrap

After an exact read-back-verified apply mutation:

- the historical baseline is created from the proposal's immutable observed evidence;
- if the baseline window ends before the action date, a projection of at most one baseline-window length may be created;
- action configuration is marked verified from the exact mutation/read-back path;
- causal status remains `not_evaluated`;
- `verified_recovery_micros` remains zero.

No apply operation can self-certify recovery.

## Aggregation rules

Recovery Center uses the latest Recovery Ledger snapshot per exact mutation event.

- superseded snapshots are not double counted;
- unlinked legacy ledger rows are excluded from recovery headlines because they cannot prove which external intervention they belong to;
- organization/portfolio/account totals remain separated by currency;
- unobserved Search spend is displayed only as a coverage limitation;
- unobserved spend is never converted into inferred waste or recovery.

## Timeline semantics

The timeline reconstructs end-of-day cumulative state by mutation event. When a ledger entry for a mutation is superseded, the newer state replaces the older state rather than being added to it.

## Breakdown semantics

Breakdowns are available by:

- account,
- campaign,
- primary leak family.

They use case-linked latest ledger evidence only. Leak family comes from the business-fit/semantic evidence associated with the proposal's source analysis; if a trustworthy family cannot be recovered, the case is labeled `unclassified_query_mismatch` rather than guessed.

## Current limitation

Epic 7 does not claim that every applied action can become verified recovery automatically. The existing causal engine requires appropriate experiment/outcome evidence. Experiment ingestion/orchestration remains a later capability; until such evidence exists, Recovery Center correctly displays verification pending, inconclusive, or zero verified recovery.
