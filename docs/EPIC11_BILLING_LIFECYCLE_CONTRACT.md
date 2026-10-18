# Epic 11 — Billing Lifecycle Contract

Version: 0.30.0

Recovery OS billing is provider-authoritative. Browser checkout completion, redirect parameters, local UI state, and webhook payload fields never independently grant paid entitlement.

## Authoritative loop

```text
checkout / provider lifecycle request
        ↓
server-side Razorpay API
        ↓
provider subscription fetch/read-back
        ↓
plan ID + configured price/currency verification
        ↓
immutable provider snapshot / lifecycle event
        ↓
server entitlement projection
```

Razorpay webhook delivery is a reconciliation trigger. The webhook payload is not accepted as the final billing truth; Recovery OS re-fetches the subscription from Razorpay.

## Product entitlement states

Recovery OS projects provider billing into product states:

- `full`
- `grace`
- `billing_pending`
- `read_only`
- `unsubscribed`
- `blocked`

`grace` is explicitly a Recovery OS business policy, not a Razorpay subscription status. `BILLING_GRACE_HOURS` is bounded to 0–720 hours and defaults to `0` (disabled). Production readiness fails closed when this setting is malformed or outside the allowed range.

During inactive billing, read access and rollback remain available while new value-producing sync, analysis, approval and mutation capabilities remain gated according to the existing entitlement contract.

## Plan changes

Razorpay supports scheduling subscription updates immediately or at cycle end. Recovery OS V1 intentionally exposes only **cycle-end plan changes**.

Immediate changes/proration are excluded from V1 because they are immediate financial side effects and require a larger credit/refund/tax/reconciliation contract.

V1 automated plan changes are allowed only when the provider-reported subscription payment method is `card`. Current Razorpay subscription-update documentation rejects UPI-authorised updates and also documents eMandate update restrictions. Unsupported payment methods fail closed and require cancel/re-subscribe rather than pretending an upgrade/downgrade can be automated.

Plan-change flow:

1. verify current provider subscription ownership;
2. verify target configured plan against Razorpay plan price/currency;
3. preview account-slot impact;
4. require explicit `Idempotency-Key`;
5. append `prepared` lifecycle operation;
6. append `in_flight` before external mutation;
7. call Razorpay with `schedule_change_at=cycle_end`;
8. fetch current subscription and pending scheduled change;
9. require exact target provider plan in read-back;
10. snapshot pending provider state;
11. reconcile provider subscription;
12. append `reconciled`.

Unknown external outcomes become `ambiguous`. They are not blindly replayed.

## Cancellation

Razorpay supports immediate cancellation or cancellation at the current cycle end. Recovery OS V1 exposes only **cycle-end cancellation**.

The provider cancellation response must identify the exact requested subscription and must not contradict the previously observed current-cycle boundary. Recovery OS then re-fetches the same subscription. Razorpay's subscription response does not provide a dedicated product-neutral "cycle-end cancellation pending" flag that Recovery OS can safely invent; therefore the audit event records only:

- provider accepted the cycle-end request;
- response identity/cycle matched;
- subsequent provider read-back did not contradict identity/cycle;
- local operation effective time is the previously observed `current_end`.

Recovery OS does not label a fabricated provider flag as proof. Once a Razorpay subscription reaches cancelled state, reactivation is not represented as possible; a future customer return requires a new subscription.

## Payment-recovery grace

If an entitled subscription transitions into the provider's payment-recovery state and a positive Recovery OS grace policy is configured, one bounded grace window may begin. Reconciliation preserves the original grace deadline rather than extending it on every provider fetch.

If grace is disabled, provider-derived entitlement restrictions apply immediately.

## Invoice/payment history

Recovery OS can explicitly refresh invoices for the provider subscription. Razorpay invoice entities are captured as immutable snapshots. Latest invoice presentation is a projection over those immutable snapshots.

Stored evidence includes:

- provider invoice ID;
- provider payment ID when present;
- status;
- currency;
- amount / amount paid / amount due;
- issued/paid timestamps;
- exact provider payload SHA-256.

Invoice refresh does not manufacture tax documents and does not alter provider invoices.

## Billing profile

Recovery OS keeps a local append-only billing contact/tax-context profile:

- legal/billing name;
- billing email;
- ISO tax country;
- state/region;
- India GSTIN when applicable.

This is **Recovery OS-local metadata only** in V1. Editing it does not update Razorpay customer identity and does not rewrite historical Razorpay invoices.

## Account-slot lifecycle

Phase 17 account slots were permanent assignment rows. Epic 11 introduces append-only `assign` / `release` slot events. This lets organizations rotate the Google Ads accounts consuming plan capacity without deleting the historical assignment record.

A plan downgrade preview shows active slots beyond the target plan's account limit. The product will not silently discard account access or historical data to make the downgrade fit.

## Lifecycle event model

Consequential billing operations are represented by immutable operations and events:

```text
prepared
   ↓
in_flight
   ↓
provider_observed
   ↓
reconciled
```

Failure branches:

```text
in_flight → failed
in_flight → ambiguous
```

Operation types:

- `plan_change_cycle_end`
- `cancel_plan_change`
- `cancel_cycle_end`

An idempotency key is bound to tenant + user + exact lifecycle request. Reusing a successful key returns the original operation even when the provider has since moved to the requested state. Reusing the same key for a different request is a conflict.

## Immutable evidence

Migration `0019_epic11_billing_lifecycle.sql` adds:

- `billing_lifecycle_operations`
- `billing_lifecycle_events`
- `billing_pending_change_snapshots`
- `billing_invoice_snapshots`
- `billing_profile_events`
- `billing_account_slot_events`

These evidence/history tables are append-only and FORCE-RLS tenant isolated. Provider counters may be unknown (`NULL`) but cannot be negative when present.

`billing_tenant_current` remains the mutable server projection derived from reconciliation; it is not append-only history.

## Authorization

Billing lifecycle administration is intentionally organization-level:

- Viewer: no organization billing API access.
- Analyst: no organization billing API access.
- Admin: billing read/manage.
- Owner: billing read/manage.

The browser is not the authorization boundary.

## V1 exclusions

Not represented as complete:

- immediate prorated plan upgrade/downgrade;
- refunds/credits;
- provider customer/tax identity mutation;
- automatic UPI/eMandate plan migration;
- accounting/GST invoice generation by Recovery OS;
- dunning strategy beyond provider state + bounded Recovery OS grace;
- live-provider validation against a real merchant account.
