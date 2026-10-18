# Epic 6 — Recovery Cases + Action Center Contract

Version: 0.25.0

## Purpose

Epic 6 turns immutable findings/proposals into an operational Recovery Case without duplicating or rewriting the underlying evidence truth.

A Recovery Case is a projection over:

1. immutable negative-keyword proposal artifact,
2. financial finding evidence from the same analysis/query scope,
3. immutable approval/rejection event,
4. durable worker job state,
5. durable external-effect state,
6. Google mutation events,
7. case-specific Recovery Ledger entries,
8. append-only operator collaboration events.

The proposal artifact ID is the stable case ID for V1. There is deliberately no mutable `recovery_cases.status` table.

## Lifecycle

`blocked/review_required -> ready_for_review -> approved -> execution_queued -> validating -> applied -> verification_pending -> verified/inconclusive`

Exceptional states:

- `failed`
- `needs_reconciliation`
- `rolled_back`
- `rejected`
- `closed`

State is derived from source events. Operators cannot manually rewrite an applied event into an approved state.

## Approval safety

Approval is allowed only when:

- stored proposal fingerprint matches the request,
- current Business Truth fingerprint equals proposal truth fingerprint,
- proposal comes from the latest completed analysis,
- case is not closed,
- Measurement Integrity allows conversion-dependent claims,
- actor has proposal-decision permission.

An approval is immutable. If evidence changes, a new analysis/proposal is required rather than editing the approved evidence.

## Execution safety

New Google Ads mutation requires:

- exact approved proposal fingerprint,
- fresh Business Truth,
- latest completed analysis,
- open case,
- current Measurement Integrity gate,
- durable operation key,
- current Google preflight,
- Google `validate_only` before mutation,
- `partial_failure=false`,
- exact resource-name response validation,
- exact resource read-back after mutate.

The worker repeats freshness and measurement checks at execution time so queue delay cannot authorize an obsolete action.

## Durable external-effect safety

The Action Center surfaces job/effect state independently from mutation events.

If the effect is `in_flight` or `ambiguous`, the case becomes `needs_reconciliation`; automatic replay is forbidden.

If an exact negative is already present before Recovery OS mutates it, ownership is not claimed. The effect is reconciled as ambiguous and requires operator review.

## Rollback

Rollback is a safety escape hatch and is intentionally different from new action execution.

Rollback:

- is allowed even if newer Business Truth/analysis exists,
- remains available if the case was closed,
- is bound to the exact Google resource name recorded by the applied mutation,
- removes only that resource,
- verifies by read-back that the exact resource is absent.

New-action freshness gates must never disable rollback.

## Recovery verification boundary

A case is `verified` only from Recovery Ledger entries linked through this case's own mutation event.

A ledger entry merely sharing the same analysis run cannot verify another case.

Candidate exposure remains separate from verified recovery.

## Measurement Integrity integration

Epic 5 is operational here. A case can still be inspected when measurement is constrained/blocked, but money-bearing approval/execution is blocked when the current measurement assessment does not allow conversion-dependent claims.

Rollback does not depend on that gate.

## Collaboration

Append-only case events support:

- assign,
- unassign,
- comment,
- request review,
- close,
- reopen.

They do not duplicate approval or Google mutation truth.

## Current action family

The executable V1 action remains the safest implemented action family: exact ad-group negative keywords produced by the existing evidence engine.

Epic 6 generalizes the product workflow around the action. It does not pretend that bid, budget, location, device, or campaign mutations are already supported.
