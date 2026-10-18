# Phase 17 setup

1. Create the intended Razorpay Subscription plans in Razorpay Test Mode first.
2. Record each `plan_...` ID and configure `BILLING_PLANS_JSON` with the same amount/currency and your product limits.
3. Set server-only `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET`.
4. Set `BILLING_ENABLED=true` on the API server.
5. Apply migration `0007_phase17_billing_onboarding.sql`.
6. Configure Razorpay's webhook URL to `https://<api-host>/v1/billing/webhooks/razorpay`. Subscribe to the subscription lifecycle events you use (activation, pending/failure/halt, pause/resume, cancellation/completion/charges). The handler does not trust event ordering; it fetches the current subscription before changing access.
7. Test in Razorpay Test Mode. The billing page intentionally does not treat a browser return/callback as proof of payment.
8. Only after test-mode reconciliation is correct should equivalent live plan IDs/keys be configured.

`total_count` is explicit configuration because it is part of the commercial subscription term. Do not copy an example value without deciding the intended number of billing cycles.
