# Epic 12 — Research Decisions

Version: 0.31.0

## 1. Platform privilege is separate from customer tenant role

NIST least-privilege guidance distinguishes privileged accounts/functions from ordinary business access and requires privileged functions to be limited and logged. Recovery OS therefore does not interpret customer Owner/Admin as platform support authority.

## 2. No platform RLS bypass in the web path

All customer data already uses FORCE RLS. The internal product keeps that boundary: a minimal tenant directory allows selection, then customer diagnostics run with one explicit tenant context.

## 3. Cloud telemetry is not duplicated

Cloud Run already publishes service/worker metrics to Cloud Monitoring, sends container logs to Cloud Logging, and integrates errors with Error Reporting. Internal Admin records product-level operator decisions, job/evidence state, incidents, and remediation provenance rather than implementing an inferior duplicate logging platform.

## 4. Worker pool deployment is not health proof

Google documents that a successful Cloud Run Worker Pool deployment does not itself prove the runtime container is healthy. Recovery OS continues to use the existing deployment-probe job/acceptance system and surfaces successful probe observations as release history.

## 5. Reconciliation is not retry

An ambiguous external effect is precisely the state where blind replay is dangerous. The internal queue exposes it for investigation but provides no one-click replay for Google/billing external effects.

## 6. Operational controls are real enforcement, not decorative feature flags

Only controls that are enforced in execution paths are exposed. V1 therefore limits the control registry to Google Ads applies, Razorpay provider mutations, and scheduled report email.

## 7. No impersonation

Support investigation should use evidence/diagnostic views. Acting as the customer would collapse attribution and audit boundaries, so Epic 12 contains no impersonation workflow.
