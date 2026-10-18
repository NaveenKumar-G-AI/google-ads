# Phase 17 billing contract

1. `BILLING_ENABLED=true` enables entitlement enforcement in the production API.
2. Reads and rollback are never blocked solely because billing became inactive.
3. New value-producing work requires a reconciled `full` entitlement.
4. Full entitlement requires Razorpay provider status `active` and a mapped provider plan ID.
5. A known `current_end` in the past fails closed until provider reconciliation updates the period.
6. Checkout success in the browser does not change entitlement.
7. Every webhook signature is verified over the exact raw body before JSON parsing.
8. Webhook event payload status is not trusted as current status; the subscription is re-fetched from Razorpay.
9. Duplicate/out-of-order events must not regress product access.
10. Subscription create ambiguity must not be retried automatically.
11. Configured plan amount/currency must match the live Razorpay plan before it is shown or used for checkout.
12. Browser/frontend source must never contain Razorpay secrets or `BILLING_PLANS_JSON`.
13. Provider snapshots and webhook receipts/results are append-only evidence.
14. `billing_tenant_current` is a mutable projection derived from immutable provider snapshots.
