# Epic 11 — Billing Research Decisions

Version: 0.30.0

## Existing foundation retained

Phase 17 already established the correct authority boundary:

- Razorpay plan price/currency are verified server-side;
- browser checkout success never unlocks the SaaS;
- signed webhook payloads trigger reconciliation but are not billing truth themselves;
- Recovery OS re-fetches subscription state;
- ambiguous checkout creation is not blindly retried;
- only provider-reconciled entitlement enables paid capabilities.

Epic 11 extends this model instead of replacing it.

## Subscription plan updates

Razorpay's subscription update API supports a `schedule_change_at` choice including `now` and `cycle_end`.

Decision: Recovery OS V1 supports **cycle_end only**.

Why:

- `now` creates an immediate financial side effect;
- proration/credits/tax treatment need additional evidence and customer communication;
- a future immediate-change flow should have its own explicit economic and reconciliation contract rather than being smuggled into V1.

Razorpay currently documents restrictions for updating UPI-authorised and eMandate subscription mandates.

Decision: automated V1 plan changes require provider-reported `card`. Other payment methods fail closed and explain that cancellation/new subscription is required.

## Cancellation

Razorpay's subscription cancellation API supports immediate cancellation or `cancel_at_cycle_end=true`, and Razorpay documentation states that a cancelled subscription cannot be restarted/renewed.

Decision: Recovery OS V1 exposes **cycle-end cancellation only**.

The provider response/read-back does not give Recovery OS permission to invent a dedicated pending-cancellation field. Therefore the lifecycle audit records accepted request + identity/cycle consistency instead of fabricating a provider boolean.

## Invoices

Razorpay exposes invoice entities and subscription-associated invoice retrieval.

Decision: invoice/payment history is imported as immutable provider snapshots. Recovery OS displays provider evidence; it does not create or rewrite Razorpay invoices.

## Grace policy

Razorpay provider status and Recovery OS product-access policy are different domains.

Decision: `BILLING_GRACE_HOURS` is a local business-policy setting, explicitly labelled as such. It defaults to zero. It is bounded and deployment readiness validates it.

## Billing contact and GST context

Decision: V1 billing profile is local Recovery OS metadata only. It is useful for operations/support and future billing integration, but changing it does not claim to change provider customer identity, GST invoice identity, or historic provider documents.

## Account capacity

Decision: plan-capacity slots must be releasable without deleting history. Epic 11 therefore projects capacity from append-only slot assignment/release events rather than permanent rows.

## External-effect fencing

Decision: provider lifecycle mutations follow the same safety philosophy as Google Ads mutations:

- immutable request identity;
- prepared/in-flight evidence before mutation;
- explicit provider read-back;
- ambiguous state for unknown outcomes;
- no blind replay;
- deterministic idempotency replay after successful completion.
