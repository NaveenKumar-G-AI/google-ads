# Phase 7 — Real Google Ads Integration & Sync Decisions

## Scope

Phase 7 connects the accuracy core to a real Google Ads advertiser account without
turning the application into a public multi-user OAuth SaaS yet.

The founder-operated V1 uses Google's **service-account workflow**. The service-account
identity is invited to the Google Ads manager/account and the official Python client is
configured with `json_key_file_path` and, when traversing a manager, `login_customer_id`.
Google Ads developer tokens were sunset on **2026-09-09**; current API access levels are attached to the
Google Cloud project that owns the service-account credentials. The code still accepts a legacy token
only for backwards compatibility with older client configurations.

## Decisions

### 1. API version is pinned

- Google Ads API: **v26**
- Python client: **google-ads >= 34.0.0** (project currently pins 34.0.0)
- API-specific protobuf access stays inside `recovery.google_ads`.

This isolates Google's release cadence from the evidence and financial logic.

### 2. V1 authentication is service-account based

This is the correct workflow for an application managing accounts it has already been
given access to. It avoids storing customer user refresh tokens during the founder-led
phase. Public self-serve OAuth remains a later product/compliance phase.

Secrets are never copied into sync files, logs, manifests, proposal fingerprints, or
source code. The official client reads the JSON key file directly.

### 3. Manager and advertiser IDs have different roles

- `login_customer_id`: manager account used to establish access.
- target `customer_id`: advertiser account being audited.

The sync refuses to use a manager account as the V1 audit target.

### 4. Customer currency and time zone are immutable sync anchors

Every run first reads `customer.currency_code` and `customer.time_zone` from Google.
Imported rows must match the account currency. Relative dates are interpreted against
the Google Ads account time zone, not the server's local time or UTC calendar date.

### 5. SearchStream is used for bulk report retrieval, but imports are chunked

Google documents SearchStream as efficient for large report retrieval over a single
stream. Streaming failures can occur, so V1 downloads bounded date chunks (7 days by
default). A chunk is held in memory and atomically committed only after both the
search-term report and campaign-spend denominator finish and validate.

If a stream fails halfway, there is no persisted half-chunk. Retrying cannot silently
double-count previously yielded rows.

### 6. Resumability is checksum-based

Phase 8 will add the database. Phase 7 uses a small atomic on-disk manifest so real
imports are usable now. Completed chunks have SHA-256 checksums. A rerun skips a chunk
only if its file still exists and its content checksum matches the manifest.

### 7. Retries are intentionally narrow

Documented transient classes such as deadline/internal/transient/unavailable errors can
be retried with bounded exponential backoff. Generic quota exhaustion is **not** blindly
retried because it can represent a daily quota rather than temporary QPS pressure.
`RESOURCE_TEMPORARILY_EXHAUSTED` is retryable when the Google Ads failure identifies it.

### 8. Keyword inventory is synced before action planning

The real-account inventory includes:

- positive Search keywords;
- ad-group negative keywords;
- campaign negative keywords;
- effective attached shared negative lists;
- linked account-level negative keyword list criteria.

Unattached shared lists are not treated as currently effective exclusions.

### 9. Live mutation is two-step plus read-back

A live negative action cannot be constructed from arbitrary text. It must come from a
Phase-5 approved `NegativeMutationPlan`.

Execution sequence:

1. re-check proposal + human approval fingerprint;
2. build the exact ad-group criterion operation;
3. call Google with `validate_only=True`;
4. issue a short-lived validation receipt tied to the mutation-plan SHA-256;
5. make the live mutate call;
6. validate Google's returned resource name is inside the approved customer/ad group;
7. query the account and verify the exact live negative exists with the approved text
   and match type;
8. only then can Phase 6 record the applied change.

Rollback removes only the exact `ad_group_criterion.resource_name` created by that
receipt.

### 10. Phase 7 does not claim request IDs it cannot reliably capture

Google documents request IDs for troubleshooting. Successful SearchStream responses
carry request IDs, while successful unary request IDs live in response metadata. The
current official-client wrapper does not invent a request ID when the high-level method
does not expose one. We will add metadata interception only when the persistence/audit
log layer needs it.

## Official references used

- Google Ads API OAuth overview and service-account workflow
- Google Ads access model and login-customer-id behavior
- Python client configuration/authentication
- v26/client-library compatibility table
- SearchStream/reporting/paging guidance
- API quotas and rate limits
- timeout and common transient-error guidance
- customer resource fields (currency/time zone/status/manager)
- criteria and AdGroupCriterion mutate APIs
- validate-only and partial-failure behavior
- ad-group criterion resource-name format
