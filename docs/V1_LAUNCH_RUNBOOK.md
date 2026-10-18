# Recovery OS V1 Launch Runbook

## 1. Keep launch closed during production deployment

Deploy the exact candidate release with production configuration, HTTPS legal/public URLs, explicit Terms/Privacy version IDs, restricted-scope Google OAuth verification acknowledgement, Google Ads production access acknowledgement, Razorpay live activation acknowledgement and verified live webhook acknowledgement.

Do not set `public` merely because deployment succeeds.

## 2. Produce fresh production readiness and acceptance

Run the production readiness checker and deployed acceptance against the exact release ID. Acceptance must include the read-only Google Ads probe against a non-test production advertiser and full billing acceptance where required.

## 3. Complete external launch evidence

Populate the V1 launch evidence directory with real, operator-attributed evidence for every required launch item. Do not create synthetic `pass` evidence for an exercise that was not performed.

## 4. Run the launch gate

Use `recovery-launch-gate` with:

- the recent Epic-13 pilot-gate report;
- fresh production readiness report;
- fresh production acceptance report;
- production launch evidence directory;
- exact release ID.

A nonzero exit code means public launch remains blocked.

## 5. Import the qualified report

A `platform_admin` imports the generated `launch-gate-report.json` in `/internal/launch`. Import validation rejects stale, mismatched or non-pass reports.

## 6. Controlled canary before public

Prefer `pilot_only` or `invite_only` while exercising final production onboarding with explicitly granted addresses. Verify that workspace creation records the exact current Terms/Privacy acceptance event and that billing/Google activation completes normally.

## 7. Promote exact release

Only after the above evidence is fresh, a `platform_admin` appends a `public` launch event with the exact release ID and a meaningful reason.

## 8. Monitor launch

Watch infrastructure monitoring, Recovery OS monitoring, billing webhooks, Google provider errors, support cases and signup-abuse controls. Use tenant kill switches for consequential provider writes where necessary.

## 9. Emergency close

If new-customer onboarding must stop, append launch mode `closed`. This blocks new workspace creation without deleting tenants or changing existing customer authorization.

If provider writes are unsafe, additionally use their independent operational kill switches. Follow the incident and rollback runbooks rather than deleting evidence.
