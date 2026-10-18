# Recovery OS web dashboard

Next.js 16.4 + React 19.3 + Supabase SSR auth.

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
npm install
npm run validate
npm run dev
```

Authenticated pages are dynamically rendered. Browser code does not query Recovery PostgreSQL directly.
