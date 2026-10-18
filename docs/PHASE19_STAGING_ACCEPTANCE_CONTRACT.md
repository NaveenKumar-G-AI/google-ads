# Phase 19 — Deployment execution and staging acceptance contract

Phase 19 does not claim deployment without real infrastructure credentials. It makes a deployed staging environment prove the following before customer access:

1. `/healthz` is live and `/readyz` verifies exact migration bytes.
2. `/buildz` exposes a non-secret `RECOVERY_RELEASE_ID` and must not be `unversioned`.
3. The dashboard origin serves successfully.
4. A real Supabase bearer token authenticates and belongs to the target tenant.
5. An admin/owner can enqueue a `deployment_probe` job; the deployed Worker Pool must claim and complete it.
6. The worker result `release_id` must exactly equal the API release ID. Mixed API/worker releases fail acceptance.
7. Optional launch gate: Razorpay Test Mode must have reconciled the tenant to `full` entitlement before acceptance passes with `--require-billing-full`.
8. The acceptance harness contains no Google Ads mutation executor and the deployment probe has no external effects.

The deployment probe is billing-independent so an operator can prove infrastructure health even before a test subscription is activated.

## Release execution

`deploy/release-staging.ps1` uses Cloud Build to build/push one backend image, resolves the image tag to an immutable Artifact Registry digest, applies migrations before deploying traffic, then deploys that exact digest to both the Cloud Run API service and Worker Pool. The generated `phase19-release-manifest.json` records the non-secret release identity and digest.

Vercel deployment is optional in the script. A preconfigured dashboard URL can be supplied instead. When `-DeployDashboard` is used, the project under `web/` must already be linked/configured in Vercel and `vercel deploy --prod --yes` is used.

The release script does not create Google Ads mutations or a Razorpay payment. `--require-billing-full` in acceptance means the operator must first complete a Razorpay Test Mode subscription authorization and reconciliation using the existing UI/API; acceptance then verifies that the deployed tenant is actually fully entitled.
