# Phase 15 — Real staging integration validation contract

Phase 15 does not add a product feature. It proves the external boundaries built in Phases 1–14.

## Hard safety rule

The Phase-15 harness has no Google Ads mutate code path. It is read-only with respect to Google Ads.
It may write staging evidence to PostgreSQL: migrations, a staging tenant/account, immutable sync evidence,
Business Truth, analysis artifacts, and two staging audit events.

## Live gates

1. Exact pinned Python dependency versions.
2. PostgreSQL connectivity over SSL (reported, not silently assumed).
3. Migration 0001–0005 registry and byte hashes match the package.
4. All `recovery` application tables have RLS enabled and forced.
5. Optional behavioral RLS probe using a non-BYPASSRLS app role.
6. Real Google Ads advertiser profile can be read with v26 through a service account.
7. Search-only date-window sync persists atomically into PostgreSQL.
8. Replaying the same sync request skips all completed chunks and does not duplicate occurrences.
9. User-supplied Business Truth parses and can drive deterministic analysis over that exact sync.
10. A small real Gemini semantic sample runs against real search terms with no financial fields.
11. A live PostgreSQL audit hash chain can be recomputed from stored rows.
12. Representative immutable evidence rejects UPDATE.
13. Phase 15 performs zero Google Ads mutations.

## Credentials

Required for database validation:

- `RECOVERY_STAGING_DATABASE_URL` — migration/backend DSN.
- `RECOVERY_STAGING_TENANT_ID` — UUID dedicated to staging validation.
- `RECOVERY_STAGING_TENANT_SLUG`
- `RECOVERY_STAGING_TENANT_NAME`
- `RECOVERY_STAGING_CUSTOMER_ID` — 10-digit advertiser customer ID.
- `RECOVERY_PHASE15_READ_ONLY_ACK=READ_ONLY_ONLY`

Optional but strongly recommended:

- `RECOVERY_STAGING_APP_DATABASE_URL` — non-BYPASSRLS app role for behavioral isolation testing.

Required for live Google Ads read-only sync:

- `GOOGLE_ADS_JSON_KEY_FILE_PATH`
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` when using a manager hierarchy.

Developer tokens were sunset by Google on **2026-09-09**. The Google Cloud project owning the service account now carries the Google Ads API access level. For a production advertiser account, that project needs an access level that permits production access (Explorer, Basic, or Standard).

Required for real Gemini semantic sampling:

- `GEMINI_API_KEY`

## Business Truth

Phase 15 never fabricates Business Truth. Analysis/Gemini validation require a JSON file containing the
canonical Phase-2 schema confirmed for the advertiser. Use `--skip-analysis --skip-gemini` if that truth
has not been collected yet.

## Google Ads test accounts

Google test accounts are useful for API/configuration safety, but they do not serve ads and therefore
have no real impressions/cost/conversion data. To validate the financial ingestion path, use a production
advertiser account with read-only/service-account access and a Google Cloud project whose Google Ads API
access level permits production-account reads.

## What a PASS means

A PASS means the exact staging boundary executed successfully for this environment/account/date window.
It does not authorize Google Ads mutations and it does not promote an AI release.
