# Recovery OS — Epic 2 Onboarding & Account Activation Specification v1

## Outcome
A new customer can reach a first defensible account analysis without developer assistance, raw JSON, Google Ads customer-ID hunting, or direct database access.

## Activation gates
1. Supabase signup / verified product session
2. Organization creation
3. Provider-reconciled paid entitlement (when billing is enabled)
4. Google Ads multi-user OAuth authorization
5. Automatic account hierarchy discovery
6. Advertiser-account selection within paid plan limits
7. Guided Business Truth confirmation
8. Measurement maturity policy
9. First read-only Google Ads sync
10. First analysis
11. First-value result (including the legitimate result “no actionable recovery opportunity found”)

## Security boundaries
- OAuth callback is bound to the product's authenticated Supabase session plus one-time hashed OAuth state.
- OAuth state expires and is consumed exactly once.
- Google refresh tokens are stored only in managed Secret Manager; PostgreSQL stores reference/fingerprint metadata.
- OAuth-backed accounts never silently fall back to another Google credential.
- Customer account discovery and sync are durable-worker jobs.
- Manager accounts can be discovered but are not selectable as advertiser analysis targets.
- Account selection is plan-limited server-side, not by checkbox UI.
- Browser code never sees database, Google OAuth client secret, refresh token, Gemini secret, Razorpay secret, or service-account key.

## Multi-account behavior
Onboarding status is per advertiser account for Business Truth, measurement, first sync and first analysis. A workspace can reach first value on one selected account while clearly showing remaining selected accounts as incomplete; each can be resumed later through the same guided route.

## Failure/recovery states
- billing pending / inactive
- OAuth denied
- OAuth state expired/used
- refresh token absent
- Google authorization requires reauthorization
- account discovery running/failed
- no accessible advertiser accounts
- selected account outside plan limit
- truth validation error
- measurement policy missing
- sync running/failed
- analysis running/failed
- analysis completes with no proposal

None of these states may create an artificial recovery claim.
