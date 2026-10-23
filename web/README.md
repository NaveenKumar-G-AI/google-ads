# Recovery OS website and dashboard

Next.js 16.4 + React 19.3 + Supabase SSR auth.

The public homepage is at `/`, the interactive synthetic tour is at `/demo`, and the authenticated application remains at `/app`. Public pages can be previewed without Supabase credentials. Account creation and activation use the existing authenticated setup.

See [Landing experience](../docs/LANDING_EXPERIENCE.md) for routes, optional booking/support/legal destinations, analytics, Render configuration and browser verification. The [product truth inventory](../docs/LANDING_PRODUCT_TRUTH_INVENTORY.md) governs public claims and demo data.

## Environment

Copy `.env.example` to `.env.local` and set:

```text
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
RECOVERY_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

Never put a Supabase service-role key, PostgreSQL DSN, Google Ads service-account key or Gemini key in this directory.

On Render, set `RECOVERY_API_BASE_URL` to the API's HTTPS origin and `NEXT_PUBLIC_SITE_URL` to the frontend's HTTPS origin. Enter origins without page paths, credentials, queries or fragments. Production auth callbacks require the configured site origin; they do not trust an incoming request host as a fallback. Rebuild after changing public variables. The shared server transport validates the API origin, uses a maximum 30-second timeout and makes one attempt per request. Check operation status before resubmitting an action after a timeout.

## Run

```powershell
npm ci
npm run validate
npm run dev
```

Authenticated pages are dynamically rendered. Browser code does not query Recovery PostgreSQL directly.

## Verify a release

Use Node `24.14.0` to match the production-checks workflow. Run each command after the preceding command succeeds:

```powershell
npm ci
npm run validate
npm run test:runtime
npm run build
npx tsc --noEmit --incremental false
```

`test:runtime` checks marketing event truth, authentication callbacks/actions and the actual API transport with mocked provider/network boundaries. These checks do not sign in to Supabase or exercise a live Google Ads account. The build creates Next.js route types used by the final type check.

From the repository root, run the read-only deployment diagnostic after deploying the reviewed release:

```powershell
python .\src\recovery\deployment_contract.py --api-url https://YOUR-API-HOST --dashboard-url https://YOUR-DASHBOARD-HOST --expected-release-id YOUR-RELEASE-ID --require-build-identity
```

The script uses only Python's standard library and needs no credentials. It checks public pages, backend readiness/build identity and the two initial onboarding API routes. Both protected routes should return `401` without a token. It cannot prove authenticated onboarding, worker processing, billing or Google authorization; complete those checks using the [Render guide](../docs/RENDER_DEPLOYMENT_STEP_BY_STEP.md). Append `--require-public` only when verifying a deliberately qualified public launch.

See [Production hardening release](../docs/PRODUCTION_HARDENING_RELEASE.md) for the change record, validation status and update steps for the existing services.
