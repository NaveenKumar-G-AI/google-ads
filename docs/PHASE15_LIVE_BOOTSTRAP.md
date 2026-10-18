# Phase 15 Live Bootstrap

This is the first command intended to be run against real staging infrastructure. It is deliberately read-only with respect to Google Ads. It can apply the bundled PostgreSQL migrations when the preflight passes.

## What you need before running it

### 1. Google Cloud / Google Ads API

Use one Google Cloud project for the staging integration.

- Enable the **Google Ads API** in that project.
- Check **Google Ads API → Overview** in Google Cloud Console.
- For a production advertiser account, the project needs **Explorer, Basic, or Standard** access. Test access can only reach test accounts.
- Create a **service account** in that project and download its JSON key to a private local location.
- Add the service-account email as a user on the target Google Ads advertiser or on a manager account that has access to that advertiser.
- If access flows through a manager account, provide the manager's 10-digit customer ID as `GOOGLE_ADS_LOGIN_CUSTOMER_ID`.
- New setups do **not** need a developer token. Google sunset developer tokens on 2026-09-09; access is attached to the Google Cloud project. Old tokens may still be sent but are ignored.

The live preflight performs a real read-only advertiser-profile call. If the Cloud project does not have production access, or the service account lacks account permission, the run stops before importing search terms.

### 2. PostgreSQL / Supabase

For `RECOVERY_STAGING_DATABASE_URL`, use:

- a direct PostgreSQL connection for migrations whenever possible; or
- Supabase session-pooler mode when direct connectivity is unavailable.

Do **not** use Supabase transaction-pooler mode (`:6543`) for the Phase-15 migration/RLS-session validation path.

`RECOVERY_STAGING_APP_DATABASE_URL` is optional but strongly recommended. It should use a real non-superuser role that does not have `BYPASSRLS`; the staging validator then proves cross-tenant isolation behavior rather than only checking RLS catalog flags.

### 3. Gemini

Use one intended key only:

- `GEMINI_API_KEY`, or
- `GOOGLE_API_KEY`.

If both exist, Google's SDK gives `GOOGLE_API_KEY` precedence. The live bootstrap prompts for `GEMINI_API_KEY` only when neither is already set.

### 4. Business Truth

For deterministic analysis or Gemini semantic sampling, provide the user-confirmed Phase-2 Business Truth JSON for this exact advertiser.

Do not invent missing services, non-offers, audiences, geographies, or intent policies merely to make the file complete. Unknown information should remain unknown.

## Windows one-command path

After extracting the ZIP, open PowerShell in the folder and run:

```powershell
.\run-phase15-live.ps1 `
  -Start "2026-10-01" `
  -End "2026-10-07" `
  -BusinessTruth ".\business-truth.json" `
  -ConversionLagDays 14
```

The wrapper:

1. creates `.venv` if needed;
2. installs the artifact's pinned dependencies;
3. securely prompts for missing database/Gemini secrets without echoing them;
4. prompts for non-secret Google Ads IDs/key-file path if not already set;
5. runs live preflight first;
6. stops immediately if any preflight check fails;
7. only then runs the read-only Phase-15 staging validator;
8. writes only redacted reports to `phase15-live-reports/`.

No Google Ads secret is written to a report. Database URLs are redacted in diagnostic evidence. The service-account private key and Gemini key are never written to report files.

## If Business Truth is not ready yet

You can validate infrastructure only:

```powershell
.\run-phase15-live.ps1 `
  -Start "2026-10-01" `
  -End "2026-10-07" `
  -SkipAnalysis `
  -SkipGemini
```

This still validates PostgreSQL, migrations, RLS metadata, real Google Ads authentication/read access, real search-term sync, sync replay/idempotency, the audit chain, append-only evidence protection, and the no-mutation guarantee.

## PASS means

A true Phase-15 PASS means this exact artifact proved, against real staging infrastructure:

- exact runtime pins;
- database connectivity and migration integrity;
- RLS catalog invariants and, when configured, behavioral tenant isolation;
- real Google Ads service-account permission;
- production/test-account compatibility with the Cloud project's API access level;
- real read-only search-term import;
- replay without duplicate evidence;
- deterministic analysis from the supplied Business Truth;
- a small Gemini semantic sample with no financial inputs;
- audit hash-chain integrity;
- append-only evidence protection;
- zero Google Ads mutations during the run.

Until that report passes, the core should not be described as externally validated.
