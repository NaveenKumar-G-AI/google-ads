# Phase 17 research decisions — billing & controlled onboarding

## Product boundary
Billing is an authorization input, not evidence of Google Ads performance. It must never alter historical findings or Recovery Ledger values.

## Razorpay authority
- Browser redirects and checkout UI state never grant product access.
- Webhook bodies are authenticated from the exact raw bytes using HMAC-SHA256.
- A webhook is a trigger to reconcile, not the source of subscription truth.
- After a valid webhook, the backend fetches the subscription from Razorpay and maps the returned provider plan ID to the configured internal plan.
- Duplicate webhook delivery is deduplicated by provider event ID when available, otherwise by exact raw-body SHA-256.
- Event order is irrelevant: each event causes a fresh provider fetch, so a late `pending` event cannot overwrite a currently `active` provider state.

## Entitlement state
Only provider status `active` maps to `full` product access in V1.
`created`, `authenticated`, and `pending` remain billing-pending.
`paused`, `halted`, `cancelled`, `completed`, and `expired` are read-only.
Unknown provider states fail closed as `blocked`.

Inactive billing does not delete or hide historical evidence. Read APIs and rollback remain available. New syncs, analyses, approvals and applies require full entitlement when billing is enabled.

## External-effect safety
Creating a subscription is not assumed idempotent across our PostgreSQL transaction and Razorpay.
A local checkout intent is persisted and moved to `in_flight` before the provider create call. A transport-ambiguous result becomes `ambiguous` and is never blindly replayed. Exact HTTP retries use the local idempotency key and return the already-created checkout without a second provider call.

## Price integrity
The public plan endpoint and checkout path fetch the configured Razorpay plan and compare amount + currency with `BILLING_PLANS_JSON`. A mismatch blocks display/checkout instead of showing a price the provider will not charge.

## Plan enforcement
V1 plans enforce two objective resources server-side:
- maximum linked Google Ads accounts
- maximum date range per sync

Account slots are assigned durably. A downgrade cannot make later-assigned slots silently eligible; account rank must remain inside the current plan limit.

## Plan changes
V1 deliberately does not implement in-place upgrades/downgrades. An active or pending subscription blocks creation of a second subscription. Plan-change semantics/proration need their own researched flow before release.

## Secrets
`RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` and provider plan IDs remain server-side. The Next.js app receives only public plan metadata and backend-derived billing status.
