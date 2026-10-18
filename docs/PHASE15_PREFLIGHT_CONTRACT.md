# Phase 15 staging preflight contract

Phase 15 preflight exists to fail **before** a long live validation run when credentials, connection modes, IDs, or local runtime are wrong. It performs no Google Ads mutation.

## What it proves offline

- Python is supported.
- The exact pinned external package versions are installed.
- `RECOVERY_PHASE15_READ_ONLY_ACK=READ_ONLY_ONLY` is present.
- Tenant ID and Google Ads customer ID are structurally valid.
- The staging admin DB URL is not a transaction-pooler URL.
- The optional RLS app-role URL is session-capable rather than transaction-pooled.
- Google Ads service-account key-path variable is present; the owning Google Cloud project is the authoritative API-access identity.
- The service-account JSON is structurally a service-account key without copying secrets into the report.
- Business Truth parses through the same Phase-2 domain validators used by the product.
- Gemini credential environment variables are present, and if both supported variables are set the report warns that `GOOGLE_API_KEY` takes precedence.

## Connection-mode rule

For Supabase staging:

- **Preferred for migrations/admin validation:** direct connection (`db.<project>.supabase.co:5432`) when reachable.
- **Acceptable with warning:** shared **session** pooler on port `5432` when a persistent direct connection is not reachable.
- **Rejected:** transaction pooler on port `6543` for Phase-15 admin/migration or behavioral RLS validation. Transaction pooling does not preserve the session semantics used by this staging harness.

The low-privilege `RECOVERY_STAGING_APP_DATABASE_URL` must be a role that is neither superuser nor `BYPASSRLS`; live preflight can verify that.

## Google Ads rule

Phase 15 expects:

- `GOOGLE_ADS_JSON_KEY_FILE_PATH`
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` when access is through a manager account
- `RECOVERY_STAGING_CUSTOMER_ID` as the target advertiser account

Google Ads developer tokens were sunset on **2026-09-09**. Current access levels are attached to the Google Cloud project that owns the service account/OAuth credentials. If an old deployment still sets `GOOGLE_ADS_DEVELOPER_TOKEN`, Phase 15 treats it as legacy/optional and warns; it is not a readiness requirement. A production advertiser read requires the owning Cloud project to have an access level that permits production accounts (Explorer, Basic, or Standard).

`GOOGLE_ADS_SERVICE_ACCOUNT_JSON` is used by the durable worker in another path. It is not silently substituted for the Phase-15 explicit key-file variable, because ambiguity around credential source is undesirable in staging evidence.

## Gemini rule

Use one intended server-side credential variable:

- `GEMINI_API_KEY`, or
- `GOOGLE_API_KEY`

When both are present, the SDK gives `GOOGLE_API_KEY` precedence; preflight reports this as a warning so the benchmark cannot accidentally bill/test a different project than intended.

## Live probes

`--probe-services` adds only safe connectivity probes:

1. PostgreSQL `SELECT` connectivity and app-role privilege inspection.
2. Google Ads advertiser profile read.
3. Minimal Gemini text call.

It does **not** run the full Google Ads data sync and does **not** execute Google Ads mutations. The full sync, replay/idempotency, RLS behavior, audit-chain, deterministic analysis, and semantic sample remain in `recovery-staging-validate`.

## Recommended order

```powershell
python examples_phase15_preflight.py `
  --business-truth .\business-truth.json `
  --conversion-lag-days 14 `
  --probe-services `
  --report .\phase15-preflight-report.json
```

Only when preflight has no `FAIL` entries should you run:

```powershell
python examples_phase15_staging.py `
  --start 2026-10-01 `
  --end 2026-10-07 `
  --business-truth .\business-truth.json `
  --conversion-lag-days 14 `
  --apply-migrations `
  --report .\phase15-staging-report.json
```
