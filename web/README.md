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
```

Never put a Supabase service-role key, PostgreSQL DSN, Google Ads service-account key or Gemini key in this directory.

## Run

```powershell
npm ci
npm run validate
npm run dev
```

Authenticated pages are dynamically rendered. Browser code does not query Recovery PostgreSQL directly.
