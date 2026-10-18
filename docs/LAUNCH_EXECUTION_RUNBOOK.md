# Recovery OS Launch Execution Runbook

## 1. Deploy the exact closed candidate

Deploy the release with launch mode still `closed`. Configure production Turnstile with a hostname-restricted production widget, store the secret in Secret Manager, and configure `RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H` (default 1).

## 2. Run readiness and deployed acceptance

Regenerate both reports against the exact release. Do not reuse reports older than the launch-gate freshness window.

## 3. Collect machine public-surface evidence

```bash
recovery-launch-public-surface \
  --api-url https://api.example.com \
  --dashboard-url https://app.example.com \
  --data-deletion-url https://app.example.com/data-deletion \
  --operator operator@example.com \
  --release-id <EXACT_RELEASE_ID> \
  --evidence-dir deploy/launch-evidence
```

Review the generated files. A failed command is launch-blocking.

## 4. Complete remaining external evidence

Complete Google production API/OAuth approvals, Razorpay live activation/webhook proof, backup + restore, security/access review, observability/on-call, incident response, rollback/reconciliation and the other evidence required by `recovery-launch-gate`.

## 5. Run the final launch gate

Run `recovery-launch-gate` with the exact release, recent pilot/readiness/acceptance reports, and the combined evidence directory. Only a qualified report may be imported.

## 6. Canary and public promotion

Use controlled invite/pilot onboarding first. Public promotion still requires the exact qualified release. Once public, the workspace endpoint itself independently requires Siteverify success and the database rate boundary.

## 7. Emergency response

Close launch to stop new workspace creation. This does not delete existing tenants. Provider mutation/email kill switches remain independent.
