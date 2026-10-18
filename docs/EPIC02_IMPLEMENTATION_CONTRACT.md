# Epic 2 Implementation Contract

## Canonical paths
- `/signup`
- `/login`
- `/onboarding`
- `/api/auth/callback`
- `/api/google-ads/oauth/callback`

## API capabilities
- create organization (idempotent)
- onboarding status
- start/complete Google OAuth
- list discovered accounts
- select advertiser accounts
- guided Business Truth creation
- measurement maturity profile
- existing durable sync/analysis jobs
- onboarding completion after completed analysis

## Google account credentials
`google_ads_account_connections` binds a selected advertiser to an OAuth grant and manager context. The worker resolves that exact grant at execution time. If its OAuth connection is revoked or missing, the job fails closed with reauthorization-required semantics.

## Compatibility
The internal/staging service-account resolver remains available only for legacy accounts with no OAuth-backed credential reference.

## External prerequisites not proven by unit tests
- Google Cloud OAuth consent-screen restricted-scope verification
- real Secret Manager IAM
- real OAuth callback from Google
- real agency/MCC hierarchy discovery
- real advertiser sync using a customer refresh token
These must be proven in staging before launch.
