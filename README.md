# Google Ads Recovery OS — Phase 16

Accuracy-first backend foundation for the Google Ads Revenue Recovery SaaS.

## Completed phases

- **Phase 1:** trusted Google Ads Search data, integer-micros money, coverage/maturity
- **Phase 2:** versioned Business Truth Model
- **Phase 3:** search-intent intelligence with UNKNOWN as a valid answer
- **Phase 4:** observed-only financial evidence / potentially avoidable spend
- **Phase 5:** safe negative-keyword proposals + human approval fingerprints
- **Phase 6:** Recovery Ledger; only causal verification can feed “money recovered”
- **Phase 7:** real Google Ads authentication, resumable sync, inventory, safe mutation boundary
- **Phase 8:** PostgreSQL production persistence, tenant isolation, immutable provenance
- **Phase 9:** authenticated backend API, tenant authorization, durable jobs, idempotency, approval/mutation gates
- **Phase 10:** durable worker leases, crash recovery, bounded retries, external-effect fencing, real queued sync/analysis/mutation runners


## Phase 16 — Customer-facing SaaS dashboard

Phase 16 adds a Next.js 16.4 / React 19.3 server-rendered dashboard on top of the existing FastAPI boundary. The browser never talks directly to Recovery PostgreSQL tables and never receives backend/service-role credentials. Supabase cookie sessions are verified server-side before their access token is forwarded to FastAPI.

Accuracy rules remain visible in the UI:

- **Potentially avoidable observed spend** is shown separately from **verified recovery**.
- privacy-hidden/unobserved search spend is shown as a coverage limitation and is never extrapolated into waste.
- proposal approval, application and rollback states come from immutable backend events.
- the UI does not calculate financial truth from raw rows; the analysis worker persists an immutable `analysis_summaries` record and the workspace endpoint renders that server-authored result.
- findings, proposals and Recovery Ledger reads are account-scoped so one advertiser cannot be mixed with another account in the same tenant.

Frontend directory:

```text
web/
  app/
  components/
  lib/
  proxy.ts
```

Run the API first, then the dashboard:

```powershell
# terminal 1
$env:DATABASE_URL="postgresql://..."
$env:SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
python examples_phase9_api.py

# terminal 2
cd web
copy .env.example .env.local
# fill Supabase publishable URL/key and RECOVERY_API_BASE_URL
npm install
npm run dev
```

The Phase-16 migration is:

```text
0006_phase16_dashboard_summary.sql
```

## Phase 10 — Durable worker and orchestration runtime

Phase 10 turns the Phase-9 queue into executable work without pretending distributed side
effects are exactly-once. PostgreSQL is the durable job authority; Google Ads remains an
external system that cannot participate in the same transaction.

```text
api_jobs
   ↓
FOR UPDATE SKIP LOCKED claim
   ↓
run_token + expiring lease
   ↓
heartbeat / attempt history
   ↓
read-only sync or analysis ── bounded safe retry
   ↓
Google mutation:
prepared → in_flight → committed
              │
              └─ ambiguous crash/error → needs_reconciliation (NO blind replay)
```

### Worker guarantees

- Every claim gets a unique fencing `run_token`.
- Heartbeats and terminal writes require the exact current ownership token.
- Multiple workers can claim different jobs using PostgreSQL `SKIP LOCKED`.
- Read-only/idempotent sync and analysis work can retry bounded transient failures.
- The final safe-job attempt cannot remain stuck forever after lease expiry.
- A Google mutate is marked `in_flight` **before** the live remote call.
- Any ambiguous exception after that point is quarantined instead of retried.
- If an immutable mutation event was persisted before a worker crash, the sweeper can finish
  the local job from that durable proof without calling Google twice.
- Rollback uses the exact recorded Google resource name, not regenerated keyword text.

### Analysis accuracy policy

Analysis creation now requires an explicit `conversion_lag_days` value. There is deliberately
no universal hidden default because different advertiser conversion cycles mature at different
speeds. The current production worker still uses the conservative Phase-3 lexical interpreter;
unknown query meaning remains UNKNOWN until a semantic model is independently evaluated.

### Run the worker

Apply migrations first, then set a dedicated backend worker DSN:

```powershell
$env:RECOVERY_WORKER_DATABASE_URL="postgresql://WORKER_USER:PASSWORD@HOST:5432/postgres"
$env:GOOGLE_ADS_LOGIN_CUSTOMER_ID="1234567890"
$env:GOOGLE_ADS_SERVICE_ACCOUNT_JSON="C:\secure\google-service-account.json"
# Google Ads developer tokens were sunset on 2026-09-09; API access is attached to the service account's Google Cloud project.

python examples_phase10_worker.py --once
# or continuously:
python examples_phase10_worker.py
```

The worker DSN is intentionally separate from browser/API credentials because job polling is
cross-tenant. Never expose it to frontend code. Google credentials are only required when a
claimed job actually needs Google Ads; analysis work itself uses stored immutable sync data.

See:

```text
docs/PHASE10_RESEARCH_DECISIONS.md
docs/PHASE10_WORKER_CONTRACT.md
```

## Phase 9 — Backend application/API boundary

The frontend is not allowed to call the Phase 1–8 engines directly.

```text
Browser / future dashboard
        ↓
Supabase Auth access token
        ↓
JWT signature + issuer + audience + expiry validation
        ↓
Application user
        ↓
Database-backed tenant membership
        ↓
Role/permission policy
        ↓
FastAPI application service
        ↓
Durable job / immutable event
        ↓
Phase 1–8 domain + PostgreSQL
```

### Authentication truth

A valid JWT proves **who the user is**. It does not prove which advertiser/tenant they may
access. Tenant membership always comes from `recovery.tenant_memberships`.

Production verification intentionally accepts asymmetric Supabase signing keys only:

```text
ES256
RS256
```

Legacy/shared-secret HS256 is not accepted by this web API implementation.

The verifier checks:

```text
signature
issuer
JWT audience
expiration
subject UUID
role == authenticated
```

`anon` and `service_role` tokens are not accepted as user identities.

### Authorization roles

```text
viewer
  read accounts/findings/ledger/jobs

analyst
  viewer permissions
  + start read-only Google Ads syncs
  + start analyses

admin
  analyst permissions
  + write Business Truth
  + approve/reject proposals
  + enqueue apply/rollback mutations

owner
  same product permissions as admin in Phase 9
```

Membership administration is deliberately **not** exposed by the normal web API yet.
Bootstrap/invitation administration should use a separate privileged control path later.

### Dangerous actions are never performed inside HTTP requests

The API enqueues durable jobs:

```text
google_ads_sync
analysis_run
apply_negative
rollback_negative
```

The HTTP request returns `202 Accepted` and a `job_id`. Phase 10 workers claim and
execute those jobs under durable leases and retry/fencing rules. This avoids tying Google mutations to a browser connection/process lifetime.

### Idempotency

Every job-producing POST requires:

```text
Idempotency-Key: <client generated unique value>
```

The key is scoped to:

```text
tenant + authenticated user + exact endpoint + key
```

Idempotency records are append-only in V1; a side-effecting key is not silently recycled later.
Mutation jobs also carry a domain-level `operation_key`, so the same approved proposal cannot
be queued twice merely by choosing two different HTTP idempotency keys.

The canonical request payload is SHA-256 fingerprinted. Repeating the same key + same request
returns the original job. Reusing that key with different inputs is a hard `409 CONFLICT`.

### Business Truth provenance

Business Truth creation is now protected at the API layer:

- `created_by` is server-owned and comes from the verified user.
- `created_at` is server-owned; client backdating is ignored.
- nested Phase-2 truth validation still runs.
- every snapshot is bound to one exact Google Ads account; cross-account truth reuse is rejected.
- version history must be linear.

Example:

```text
v1 supersedes: none
v2 supersedes: 1
v3 supersedes: 2
```

A client cannot submit v7 when v2 is current or rewrite v1 with different facts.

### Proposal / mutation gates

```text
negative-keyword proposal
        ↓
admin/owner decision
        ↓
approved immutable fingerprint
        ↓
apply job may be queued once
```

An analyst cannot approve or execute a mutation.

A rollback is even stricter:

```text
proposal
↓
actual recorded mutation event = applied
↓
exact Google resource_name exists
↓
not already rolled back
↓
rollback job
```

The API does not manufacture rollback targets from keyword text.

### RLS additions

Phase 9 adds:

```text
recovery.app_users
recovery.tenant_memberships
recovery.api_jobs
recovery.api_idempotency_keys
```

`app_users` is self-scoped by `recovery.user_id`.

`tenant_memberships` is **read-only** to the normal web RLS policy; a web request cannot use
the normal application path to grant itself a membership.

Jobs/idempotency rows require both the active tenant context and current authenticated user.

Phase-8 tenant isolation remains on all evidence/financial tables.

## API routes

Public:

```text
GET /healthz
```

Authenticated:

```text
GET  /v1/me
GET  /v1/tenants/{tenant_id}/accounts
GET  /v1/tenants/{tenant_id}/jobs/{job_id}
GET  /v1/tenants/{tenant_id}/findings
GET  /v1/tenants/{tenant_id}/recovery-ledger
```

Authorized writes:

```text
POST /v1/tenants/{tenant_id}/accounts/{account_id}/syncs
POST /v1/tenants/{tenant_id}/accounts/{account_id}/business-truth
POST /v1/tenants/{tenant_id}/accounts/{account_id}/analyses
POST /v1/tenants/{tenant_id}/proposals/{proposal_id}/decision
POST /v1/tenants/{tenant_id}/proposals/{proposal_id}/execute
POST /v1/tenants/{tenant_id}/proposals/{proposal_id}/rollback
```

## Install and test

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest -q
```

Expected Phase-10 result:

```text
227 passed
```

## Environment

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/postgres"
$env:SUPABASE_URL="https://YOUR_PROJECT.supabase.co"
$env:API_ALLOWED_ORIGINS="https://app.example.com"
```

Never put a Supabase `service_role`/secret key in browser code. This API verifies normal
end-user access tokens via public JWKS keys.

## Apply database migrations

Phase 8's migration runner automatically discovers both migration files:

```powershell
python examples_phase8_database.py --migrate
```

That applies:

```text
0001_phase8_core.sql
0002_phase9_api_boundary.sql
```

## Run the API

After setting the environment and applying migrations:

```powershell
uvicorn recovery.api.app:create_app_from_env --factory --host 127.0.0.1 --port 8000
```

Health check:

```text
GET http://127.0.0.1:8000/healthz
```

The production JWT path requires a Supabase project using asymmetric JWT signing keys.

## Current external-validation boundary

Validated in this package:

```text
Python compilation                         PASS
Phases 1–9 unit/contract tests             196 / 196 PASS
FastAPI route authorization tests           PASS
Cross-tenant denial tests                   PASS
Idempotency replay/conflict tests           PASS
Business Truth parser/domain validation     PASS
Business Truth linear-version contract      PASS (code/schema contract)
Apply-before-approval prevention             PASS
Rollback-without-applied-resource denial     PASS
RLS/migration contract tests                PASS
```

Not claimed yet:

```text
Pinned FastAPI/PyJWT runtime install          package versions verified on PyPI; exact install blocked by this sandbox network
Live Supabase JWT verification              requires real Supabase project/JWKS
Live Phase-9 PostgreSQL migration            requires real PostgreSQL/Supabase database
Live API + RLS penetration validation        requires that database and API DB role
Durable job execution                       next worker phase
Real Google Ads sync through queued job      requires worker + credentials
Real Google mutation through queued job      requires worker + approved test account
```

Those are intentionally not labeled complete until tested against the actual external systems.

## Research/contracts

Read:

- `docs/PHASE9_RESEARCH_DECISIONS.md`
- `docs/PHASE9_API_SECURITY_CONTRACT.md`
- all earlier accuracy/security contracts under `docs/`

## Next phase

**Phase 10 — Durable Worker & Orchestration Runtime**

The next component should claim Phase-9 jobs safely and execute them exactly once/effectively
once:

```text
queued job
→ lease/heartbeat
→ bounded retry classification
→ Phase-7 Google sync or Phase-3/4/5 analysis pipeline
→ validate_only
→ mutation/read-back
→ immutable event/result
→ recovery follow-up scheduling
```

Only after this execution layer is reliable should the dashboard become the main focus.

---

## Phase 11 — AI Semantic Evaluation & Calibration

Phase 11 adds a provider-neutral safety harness **before** any LLM is allowed to influence financial findings.

Core capabilities:
- immutable Business-Truth-specific gold cases
- required multi-review for exclusion-critical labels
- calibration/test leakage detection
- explicit unsafe false-exclusion metric
- abstention/coverage measurement
- per-language slices
- Brier score and Expected Calibration Error
- risk/coverage curves across confidence thresholds
- Wilson uncertainty bound so tiny zero-error tests cannot masquerade as proof
- calibration-only threshold selection
- configurable release gate

Run the Phase-11 demonstration:

```bash
python examples_phase11_semantic_eval.py
```

The demo uses the conservative lexical baseline and deliberately has too little support to qualify a production AI model.

See:
- `docs/PHASE11_RESEARCH_DECISIONS.md`
- `docs/PHASE11_EVALUATION_CONTRACT.md`


---

## Phase 12 — Candidate AI Semantic Engine

Phase 12 adds a **candidate** LLM interpreter behind the existing Phase-3 semantic
contract. It does **not** replace the conservative production baseline automatically.

Current candidate transport:

```text
Google Gemini Interactions API
model: gemini-3.8-flash
SDK pin: google-genai==2.31.0
structured output: response_format JSON schema
thinking level: low by default
external tools/grounding: disabled
provider storage: store=false
```

Accuracy boundary:

```text
raw query + confirmed Business Truth
        ↓
CandidateSemanticAI
        ↓
strict schema / identity / business-ID validation
        ↓
SemanticAssessment
        ↓
BusinessFitEvaluator
        ↓
Phase 11 benchmark + calibration gate
```

The candidate prompt deliberately excludes advertising performance fields. It receives
no spend, clicks, impressions, conversions, conversion value, CPA, ROAS, revenue or
budget. It also receives no Google Search/tool access. Model-produced confidence is
recorded but treated as untrusted until Phase 11 calibrates it.

Run a live candidate call only after installing dependencies and setting a server-side key:

```bash
export GEMINI_API_KEY=...
python examples_phase12_candidate_ai.py
```

On Windows PowerShell:

```powershell
$env:GEMINI_API_KEY="..."
python examples_phase12_candidate_ai.py
```

A successful live response still means **candidate only**. It is not production-eligible
until `CandidateBenchmarkRunner` passes the Phase-11 release gate on the exact model,
prompt version, schema version and thinking configuration.

See:
- `docs/PHASE12_RESEARCH_DECISIONS.md`
- `docs/PHASE12_AI_SEMANTIC_CONTRACT.md`

---

## Phase 13 — Shadow Mode + AI Release Registry

Phase 13 allows the Phase-12 candidate semantic model to run against **real imported Search
queries without changing production financial findings or Google Ads**.

Safety path:

```text
real Search query + exact Business Truth
        ↓
Candidate AI (shadow only)
        ↓
dedicated append-only shadow prediction
        ↓
NO financial/action effect
        ↓
blinded independent human review
        ↓
immutable gold-case version
        ↓
immutable dataset snapshot
        ↓
Phase-11 calibration/test evaluation
        ↓
exact model/prompt/schema/provider-revision release definition
        ↓
explicit activation event
```

Production analysis remains on `ConservativeLexicalInterpreter`; Phase 13 does not silently
replace it.

Queue a real shadow run after Phase-13 migration, a completed Google Ads sync, Business Truth,
and server-side `GEMINI_API_KEY` are available:

```http
POST /v1/tenants/{tenant}/accounts/{account}/semantic-shadow-runs
Idempotency-Key: shadow-2026-10-15-001

{
  "sync_run_id": "...",
  "truth_snapshot_id": "..."
}
```

Run the offline contract demo:

```bash
python examples_phase13_shadow_release.py
```

See:
- `docs/PHASE13_RESEARCH_DECISIONS.md`
- `docs/PHASE13_SHADOW_RELEASE_CONTRACT.md`

---

## Phase 14 — Production Semantic Router + Continuous Drift Guard

Phase 14 is the controlled bridge from a Phase-13 promoted semantic release into real analysis.
Activation does **not** mean unconditional AI authority.

Production routing is fail-closed:

```text
active + healthy exact release
        ↓
local model/prompt/contract match
        ↓
provider revision match
        ↓
approved language
        ↓
calibrated confidence threshold
        ↓
deterministic business-fit accepts meaning
        ↓
released AI semantics

ANY GATE FAILS
        ↓
ConservativeLexicalInterpreter
```

Every routed decision persists the baseline, candidate (when called), selected result, release
fingerprint, provider revision, confidence, fallback reason and source scope. Phase 4/5 consume
only the selected routed result.

Post-deployment drift uses production decisions that are later linked to blinded,
release-eligible human gold labels. If a sufficiently supported monitoring window breaches the
unsafe false-exclusion policy, the release is permanently `tripped` and routing falls back to
the deterministic baseline. Provider revision/contract mismatches can trip immediately.

Run the offline routing demo:

```bash
python examples_phase14_production_router.py
```

See:
- `docs/PHASE14_RESEARCH_DECISIONS.md`
- `docs/PHASE14_PRODUCTION_ROUTER_CONTRACT.md`

---

## Phase 15 — Real staging integration validation harness

Phase 15 intentionally adds **no Google Ads mutation path**. It validates the external boundaries from
Phases 1–14 against your real staging infrastructure.

Prepare a user-confirmed canonical Business Truth JSON file, then set server-side environment variables:

```powershell
$env:RECOVERY_STAGING_DATABASE_URL="postgresql://..."
$env:RECOVERY_STAGING_APP_DATABASE_URL="postgresql://..."   # optional but recommended
$env:RECOVERY_STAGING_TENANT_ID="<uuid>"
$env:RECOVERY_STAGING_TENANT_SLUG="phase15-staging"
$env:RECOVERY_STAGING_TENANT_NAME="Phase 15 Staging"
$env:RECOVERY_STAGING_CUSTOMER_ID="1234567890"
$env:RECOVERY_PHASE15_READ_ONLY_ACK="READ_ONLY_ONLY"

$env:GOOGLE_ADS_LOGIN_CUSTOMER_ID="1234567890"              # if manager hierarchy is used
$env:GOOGLE_ADS_JSON_KEY_FILE_PATH="C:\secure\service-account.json"
# No developer token is required for new setups. The service account's Google Cloud project must have Explorer/Basic/Standard access for production advertiser accounts.
$env:GEMINI_API_KEY="..."
```

Run a short historical staging window first:

```powershell
recovery-staging-validate `
  --start 2026-10-01 `
  --end 2026-10-07 `
  --business-truth .\business-truth.json `
  --conversion-lag-days 14 `
  --apply-migrations `
  --report .\phase15-staging-report.json
```

or directly from an extracted checkout:

```powershell
python examples_phase15_staging.py `
  --start 2026-10-01 `
  --end 2026-10-07 `
  --business-truth .\business-truth.json `
  --conversion-lag-days 14 `
  --apply-migrations
```

If Business Truth has not yet been collected, validate infrastructure + real read-only sync only:

```powershell
python examples_phase15_staging.py --start 2026-10-01 --end 2026-10-07 --apply-migrations --skip-analysis --skip-gemini
```

See `docs/PHASE15_STAGING_VALIDATION_CONTRACT.md` before running live.

## Phase 15A — staging setup preflight

Before the live Phase-15 validation run, execute the fail-fast preflight. It validates the exact pinned runtime, database connection mode, staging IDs, Google Ads service-account file structure, Business Truth, Gemini credential selection, and (optionally) safe live connectivity.

```powershell
python examples_phase15_preflight.py `
  --business-truth .\business-truth.json `
  --conversion-lag-days 14 `
  --probe-services `
  --report .\phase15-preflight-report.json
```

Or after package installation:

```powershell
recovery-staging-preflight --business-truth .\business-truth.json --conversion-lag-days 14 --probe-services
```

The preflight has no Google Ads mutate path. Read `docs/PHASE15_PREFLIGHT_CONTRACT.md` for the exact guarantees and connection-mode rules.

A Windows PowerShell variable template is included as `phase15-env-template.ps1`. Keep any filled copy private and out of Git.

## Phase 15 live bootstrap

For the first real staging run, use the interactive fail-closed bootstrap instead of manually setting every environment variable:

```powershell
.\run-phase15-live.ps1 -Start "2026-10-01" -End "2026-10-07" -BusinessTruth ".\business-truth.json" -ConversionLagDays 14
```

It stores secrets only in the current process environment, runs live preflight first, and starts the read-only staging validator only if every preflight failure is cleared. See `docs/PHASE15_LIVE_BOOTSTRAP.md`.


# Phase 17 — Billing, plan enforcement & controlled onboarding

Phase 17 adds a server-authoritative Razorpay Subscriptions boundary. Signed webhooks are verified from the raw request body, then the backend re-fetches the subscription from Razorpay before changing entitlements. Browser checkout success is never sufficient. Historical findings remain readable if billing stops, and rollback remains available; new sync/analysis/approval/apply operations require an active reconciled subscription when `BILLING_ENABLED=true`.

New migration: `0007_phase17_billing_onboarding.sql`. New dashboard route: `/dashboard/billing`. Configure server-only `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, and `BILLING_PLANS_JSON`. Provider plan amount/currency are re-verified before plans are displayed or checkout is created.

See `docs/PHASE17_RESEARCH_DECISIONS.md` and `docs/PHASE17_BILLING_CONTRACT.md`.

---

# Phase 18 — Production deployment & operational readiness

Phase 18 adds the deployment boundary for the accuracy-first core.

## Recommended topology

- **API:** Google Cloud Run service.
- **Durable worker:** Google Cloud Run Worker Pool (1 fixed instance initially).
- **Database/Auth:** Supabase PostgreSQL + Supabase Auth.
- **Dashboard:** Vercel Next.js deployment.
- **Backend secrets:** Google Secret Manager.

The API and worker intentionally use one immutable backend container image. The Worker Pool overrides the image command to `recovery-worker`.

## New commands

```text
recovery-migrate
recovery-production-check
```

`recovery-migrate` applies the version-controlled PostgreSQL migrations and refuses migration-byte drift.

`recovery-production-check` validates production/staging configuration, exact migration integrity and worker-queue health without echoing secret values.

## Health endpoints

```text
GET /healthz
```

is process liveness only.

```text
GET /readyz
```

checks database connectivity and exact packaged migration hashes. It returns HTTP 503 without exposing the underlying SQL/DSN error when the database is not ready.

## Build backend image

Example with Cloud Build:

```powershell
gcloud builds submit `
  --config deploy/cloudbuild.backend.yaml `
  --substitutions _IMAGE=asia-south1-docker.pkg.dev/PROJECT/recovery/backend:VERSION
```

Prefer deploying by the immutable image digest after the build.

## Apply migrations

Run migrations from an approved administrative/migration environment before routing a new API/worker release:

```powershell
$env:DATABASE_URL="postgresql://..."
recovery-migrate
```

Never put the production database password in a checked-in script.

## Pre-deploy operational check

```powershell
$env:RECOVERY_ENVIRONMENT="production"
$env:RECOVERY_BACKUP_POLICY_ACK="PITR_OR_DAILY_BACKUP_VERIFIED"
recovery-production-check --report .\production-readiness.json
```

A production result containing any `fail` item is a deployment blocker.

## Deploy API / worker

Templates are in:

```text
deploy/gcloud-api.ps1
deploy/gcloud-worker.ps1
```

The worker deployment uses a **Cloud Run Worker Pool**, not an HTTP service. Start with one instance. The durable queue and lease model supports multiple worker instances later, but scale only after staging load tests prove the need.

## Dashboard

Deploy `web/` as the Vercel project root and configure only:

```text
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
RECOVERY_API_BASE_URL
```

No database, Google Ads, Gemini, Razorpay secret or Supabase service-role credential belongs in the dashboard environment.

## Rollout gate

Do not enable real customer traffic until all of these are true:

1. Phase-15 live staging validation passes.
2. Migrations 0001–0007 match the packaged hashes.
3. `/healthz` and `/readyz` pass on the deployed API.
4. Worker Pool is running and queue health shows no stale lease/reconciliation backlog.
5. Razorpay Test Mode checkout → webhook → provider reconciliation → entitlement passes in staging.
6. Supabase backup/PITR policy is verified.
7. One read-only Google Ads sync and one analysis complete through the deployed stack.

See `docs/PHASE18_DEPLOYMENT_CONTRACT.md` and `docs/PHASE18_RESEARCH_DECISIONS.md`.

## Phase 19 — deployment execution and staging acceptance

Phase 19 adds a zero-external-effect deployment probe, immutable release identity, digest-pinned API/Worker deployment orchestration, and `recovery-staging-accept`. A staging release is accepted only when the deployed API is ready, the dashboard is reachable, an authenticated staging admin/owner belongs to the tenant, the real Worker Pool completes the deployment probe, and the API/worker release IDs match. Razorpay Test Mode full entitlement can be made a required acceptance gate with `--require-billing-full`.

No Google Ads mutation is performed by the Phase 19 acceptance harness.

---

## Canonical product reset — v0.20.0 / Epic 1

The product is no longer planned as a sequence of small dashboard pages. The repository now treats the earlier Phase 1–19 work as the **engineering foundation** underneath the mature Recovery OS product specification.

The canonical planning source of truth is now:

- `docs/CANONICAL_PRODUCT_SPEC_V1.md`
- `docs/CANONICAL_SCREEN_WORKFLOW_REGISTRY_V1.md`
- `docs/CURRENT_CODE_GAP_MAP_V1.md`
- `docs/EPIC01_PRODUCT_SHELL_SPEC_V1.md`

### New canonical application entry

After authentication, use:

```text
/app
```

The legacy `/dashboard/*` pages remain temporarily so existing evidence/action/billing flows continue to work while their mature replacements are developed in later epics.

### Epic 1 database migration

```text
0009_epic01_product_shell.sql
```

adds first-class portfolios, account group membership, operational tasks, user notifications, and shell preferences.

### Development sequence from here

1. Epic 1 — Product Shell & Design System ✅
2. Epic 2 — Onboarding & Account Activation ✅
3. Epic 3 — Search Intelligence
4. Epic 4 — Waste Intelligence
5. Epic 5 — Measurement Integrity
6. Epic 6 — Recovery Cases + Action Center
7. Epic 7 — Recovery Center
8. Epic 8 — Monitoring & Alerts
9. Epic 9 — Reporting
10. Epic 10 — Organization / Agency Operations
11. Epic 11 — Complete Billing Lifecycle
12. Epic 12 — Internal Admin / Support
13. Pilot hardening
14. V1 launch

---

# Epic 2 — Guided Onboarding & Account Activation (v0.21.0)

Epic 2 replaces developer-operated customer setup with a guided activation journey:

`signup → organization → subscription → Google Ads OAuth → automatic account discovery → account selection → guided Business Truth → measurement maturity → first read-only sync → first analysis → first value`

## Google Ads authorization

Customer-facing onboarding uses Google's **multi-user OAuth** flow with the restricted `adwords` scope and offline refresh access. Customers do not type manager/customer IDs. Recovery OS calls `ListAccessibleCustomers` and `customer_client` hierarchy reporting to discover the accounts the authorized Google user can access, including nested manager descendants.

Refresh tokens are **not stored in PostgreSQL**. The database keeps only a Secret Manager version reference and SHA-256 fingerprint. The API creates/rotates the secret; the worker reads it only when it must build the customer's Google Ads client.

Legacy/internal service-account configuration remains only as a fallback for accounts that are not OAuth-backed. An OAuth-backed customer account never silently falls back to the founder/service account if its customer grant is missing or revoked.

### Required server configuration

- `GOOGLE_ADS_OAUTH_CLIENT_ID`
- `GOOGLE_ADS_OAUTH_CLIENT_SECRET`
- `GOOGLE_ADS_OAUTH_REDIRECT_URI` (for example `https://app.example.com/api/google-ads/oauth/callback`)
- `GOOGLE_OAUTH_SECRET_MANAGER_PROJECT`

The Google Cloud runtime identities need least-privilege Secret Manager access. The API needs permission to create/add/delete customer token secrets; the worker needs secret-version access. Do not expose these secrets or refresh tokens to Next.js/browser code.

### Production launch prerequisite

The Google Ads OAuth scope is restricted. Production self-serve onboarding must complete Google's required OAuth verification/security process for the configured Cloud project before public customer launch. Staging/test deployment does not remove that launch requirement.

## Billing and account limits

When billing is enabled, account selection requires a reconciled active subscription and is limited by the provider-verified plan's `max_google_ads_accounts`. Slot assignment and account materialization occur under the same database transaction/advisory lock so a concurrent selection cannot exceed the plan limit.

## Guided Business Truth

Customers enter normal product information—offers, explicit non-offers, service areas, intent policies and primary business outcomes. The server builds the canonical immutable Business Truth snapshot. Omitted intent rules remain `UNKNOWN`; they are never silently converted to `DENY`.

---

# Epic 3 — Search Intelligence (v0.22.0)

Search Intelligence is now a first-class Recovery OS product domain rather than a planned navigation item.

Implemented surfaces:

```text
/app/search-intelligence
/app/search-intelligence/terms
/app/search-intelligence/terms/detail
/app/search-intelligence/ngrams
/app/search-intelligence/breakdowns
/app/portfolios/:portfolioId/search
```

Accuracy rules:
- visible query rows come only from completed persisted Google Ads observations;
- privacy-hidden demand is not reconstructed into fabricated queries;
- custom date windows suppress analysis-window-specific financial finding money unless the windows exactly match;
- n-gram analysis is literal whitespace-token lexical aggregation, not semantic rewriting;
- portfolio cost remains grouped by currency.

Search Themes / Google Search Terms Insights category ingestion is intentionally reserved for the later V1.5 capability because provider category aggregates and visible query rows have different privacy/evidence semantics.

---

# Epic 4 — Waste Intelligence (v0.23.0)

Epic 4 turns Search Intelligence into an evidence-oriented leakage product without creating a generic "all non-converting spend is waste" score.

Implemented:

- Waste Intelligence overview
- mutually exclusive query leak families
- paginated query leakage explorer
- Search vs Search Partners evidence dimension
- device/daypart observed performance dimensions
- physical user-location evidence ingestion
- Business-Truth-aware geographic evaluation
- conversion-lag maturity handling
- immutable waste-dimension evidence storage
- tenant RLS and append-only protection
- explicit non-additive financial semantics

Canonical routes:

```text
/app/waste-intelligence
/app/waste-intelligence/queries
/app/waste-intelligence/dimensions
/app/waste-intelligence/geo
```

Critical boundary: device/daypart are diagnostic-only in Epic 4; geography uses actual user-location evidence, not campaign target configuration; geo and dimension lenses are never added onto query-family money as independent waste totals.

---

## Epic 5 — Measurement Integrity (v0.24.0)

Epic 5 makes conversion trust a first-class product domain. Recovery OS no longer assumes that a Google Ads conversion is automatically a valid business outcome.

### Canonical routes

```text
/app/measurement-integrity
/app/measurement-integrity/conversion-actions
/app/measurement-integrity/goals
/app/measurement-integrity/lag
```

### Evidence model

Migration:

```text
0013_epic05_measurement_integrity.sql
```

adds immutable provider evidence and append-only Business Truth mapping events for:

- conversion actions,
- customer conversion goals,
- campaign conversion goals,
- campaign goal configuration,
- conversion lag,
- conversion-action → Business Truth outcome mapping.

### Confidence contract

Recovery OS deliberately does not create a 0–100 tracking score. It returns one of:

```text
strong
constrained
blocked
unknown
```

with exact reasons and two backend-authoritative gates:

```text
conversion_dependent_claims_allowed
recovery_verification_allowed
```

### Provider-truth boundaries

- Uses current `primary_for_goal` semantics rather than deprecated include-in-conversions behavior.
- Separates customer-default and campaign-specific goal configuration.
- Compares observed conversion-lag buckets with the account maturity policy.
- Never infers enhanced-conversion health from the ConversionAction resource.
- Does not add a new offline-conversion writer against a 2026 ingestion path that is moving to the Data Manager API.

See:

- `docs/EPIC05_MEASUREMENT_INTEGRITY_CONTRACT.md`
- `docs/EPIC05_RESEARCH_DECISIONS.md`

---

## Epic 6 — Recovery Cases + Action Center (v0.25.0)

Epic 6 replaces the legacy proposal-list experience with the canonical Action Center.

New canonical surfaces:

```text
/app/action-center
/app/action-center/approvals
/app/action-center/history
/app/action-center/cases/:caseId
```

A Recovery Case projects immutable evidence, decision events, durable job/external-effect state, Google mutation events, case-specific Recovery Ledger evidence, and append-only collaboration events into one operational lifecycle.

Safety additions include:

- stale Business Truth blocks approval and new execution,
- newer completed analysis blocks approval and new execution,
- Measurement Integrity actively gates money-bearing approvals/mutations,
- worker rechecks freshness and measurement state after queueing,
- ambiguous/in-flight external effects become `needs_reconciliation`,
- automatic replay of ambiguous effects remains forbidden,
- case verification only consumes ledger entries linked to that case's own mutation,
- rollback remains available even after new evidence or case closure,
- rollback is exact-resource and read-back verified.

Migration:

```text
0014_epic06_recovery_cases.sql
```

adds append-only `recovery_case_events` for assignment, comments, review requests, close and reopen events. Approval/mutation/recovery truth stays in its existing authoritative event tables.

See:

- `docs/EPIC06_RECOVERY_CASE_ACTION_CENTER_CONTRACT.md`
- `docs/EPIC06_RESEARCH_DECISIONS.md`

---

## Epic 7 — Recovery Center (v0.26.0)

The canonical product now includes `/app/recovery-center` with account, portfolio and organization scopes.

Implemented:

- strict separation of current observed candidate, historical acted-on exposure, projection, post-action observed spend and verified recovery;
- latest-ledger-per-mutation de-duplication;
- currency-safe portfolio/organization aggregation;
- case proof, account/campaign/leak breakdowns and de-duplicated financial timeline;
- case-specific ledger persistence bound to exact mutation-event identity;
- immediate historical-baseline + eligible run-rate-projection bootstrap after exact read-back-verified Google mutation;
- no automatic verified-recovery claim on apply;
- unlinked legacy evidence excluded from recovery headlines;
- unobserved Search spend remains a coverage limitation only.

See `docs/EPIC07_RECOVERY_CENTER_CONTRACT.md`.

---

## Epic 8 — Monitoring & Alerts (v0.27.0)

The canonical product now includes `/app/monitoring` with a persistent, event-sourced incident model.

Implemented:

- immutable campaign serving-health snapshots from Google provider evidence;
- durable post-sync `monitoring_evaluation` jobs;
- data freshness, Measurement Integrity, job failure, campaign serving and reconciliation monitors;
- explicit-policy spend-anomaly and conversion-drop monitors;
- conversion-drop maturity windows gated by Measurement Integrity;
- deterministic incident fingerprints and de-duplication;
- append-only acknowledgement, assignment, resolution, dismissal, reopen and comment events;
- recurrence generations only after an evaluator-observed clear;
- account/org monitoring policy events;
- Alert Inbox, incident detail/history and policy UI;
- diagnostic-only truth boundary: alerts do not become waste/recovery money automatically.

Query recurrence remains deliberately no-signal until an exact action/query recurrence join is implemented. Landing-page HTTP monitoring and outbound notification connectors are also deferred rather than represented as completed.

See `docs/EPIC08_MONITORING_ALERTS_CONTRACT.md`.

---

## Epic 8 — Monitoring & Alerts v0.27.0

Epic 8 turns monitoring into an event-sourced operations product rather than a notification list.

Canonical routes:

- `/app/monitoring`
- `/app/monitoring/alerts`
- `/app/monitoring/alerts/:alertId`
- `/app/monitoring/policies`
- `/app/monitoring/history`

Implemented monitor families include structural data-freshness, measurement-integrity, job-health, campaign-serving and reconciliation incidents. Spend-anomaly and conversion-drop policies are opt-in and expose their thresholds/minimum evidence gates. Query recurrence remains deliberately disabled until exact intervention-linked recurrence evidence is implemented.

Monitoring does not create waste or recovery money. Alerts are diagnostic evidence and remain separate from Waste Intelligence and Recovery Center financial truth.

Next canonical epic: **Epic 9 — Reporting**.

---

## Epic 9 — Reporting (v0.28.0)

The canonical product now includes `/app/reports` as an immutable evidence-export system.

Implemented:

- eight prebuilt audited report families;
- durable `report_generation` worker jobs;
- immutable JSON snapshots with SHA-256 identity;
- static Unicode-safe PDF and complete CSV artifacts with SHA-256 identity;
- secure expiring/revocable share links with hash-only token storage;
- daily/weekly/monthly timezone-aware schedules;
- optional scheduled SMTP delivery with per-recipient privacy, job-id idempotency and ambiguous-outcome protection;
- append-only report/share/schedule/delivery provenance;
- organization/portfolio/account scopes according to report type;
- financial classes remain non-additive and projections never become verified recovery through reporting.

Canonical routes:

- `/app/reports`
- `/app/reports/new`
- `/app/reports/schedules`
- `/app/reports/:generationId`
- `/shared/reports/:token`

Migration: `0017_epic09_reporting.sql`.

See `docs/EPIC09_REPORTING_CONTRACT.md` and `docs/EPIC09_RESEARCH_DECISIONS.md`.

Next canonical epic: **Epic 10 — Organization / Agency Operations**.

---

## v0.29.1 — Epic 10: Organization / Agency Operations

Epic 10 adds production-oriented Recovery OS team and client isolation:

- organization invitations with hash-only, single-use capability tokens,
- member role/status/access administration,
- all-accounts vs selected-accounts authorization,
- direct advertiser-account grants,
- client workspaces and client-linked account access,
- account responsibilities/ownership,
- immutable organization activity history,
- server-side account filtering across customer product surfaces,
- last-active-Owner protection.

Important: these are **Recovery OS permissions only**. They do not create, modify or revoke Google Ads provider users or roles.

See:

- `docs/EPIC10_AGENCY_OPERATIONS_RESEARCH_DECISIONS.md`
- `docs/EPIC10_AGENCY_OPERATIONS_CONTRACT.md`

Next canonical epic: **Epic 11 — Complete Billing Lifecycle**.

Epic-10 resumed hardening in v0.29.1 adds concurrency-safe last-Owner protection at both API and PostgreSQL boundaries, serialized invitation lifecycle transitions, Owner-only management of Owner invitations, and matching frontend controls. This closes the interrupted management-API safety work without changing the Recovery OS vs Google Ads provider-access boundary.

---

## Epic 11 — Complete Billing Lifecycle (v0.30.0)

Epic 11 extends the existing Razorpay-authoritative Phase-17 foundation into a customer-worthy post-checkout lifecycle.

Implemented:

- provider-reconciled subscription lifecycle and entitlement history;
- bounded Recovery OS grace policy (`BILLING_GRACE_HOURS`, default `0`);
- cycle-end plan-change preview and execution;
- card-only automated plan changes in V1; unsupported payment methods fail closed;
- cancel scheduled plan change;
- cycle-end subscription cancellation only;
- immutable/fenced billing mutation operations with idempotent replay;
- provider invoice/payment-history import;
- append-only local billing contact/tax profile;
- releasable, event-sourced account-capacity slots;
- downgrade capacity-impact preview;
- canonical `/app/billing` UI for Admin/Owner only;
- deployment/readiness validation of billing grace policy;
- immutable lifecycle/pending-change/invoice/profile/slot evidence.

Important boundaries:

- browser checkout success never grants entitlement;
- webhooks trigger provider reconciliation rather than becoming truth themselves;
- V1 never performs immediate prorated plan changes;
- V1 never performs immediate cancellation;
- local billing profile does not update Razorpay customer or historical invoice identity;
- cycle-end cancellation audit means provider acceptance plus non-contradictory identity/cycle read-back, not a fabricated provider pending-cancellation flag;
- `grace` is Recovery OS policy, not a Razorpay subscription status.

Migration:

```text
0019_epic11_billing_lifecycle.sql
```

See:

- `docs/EPIC11_BILLING_LIFECYCLE_CONTRACT.md`
- `docs/EPIC11_RESEARCH_DECISIONS.md`

Next canonical epic: **Epic 12 — Internal Admin & Support Operations**.

---

## Epic 12 — Internal Admin & Support Operations (v0.31.0)

Epic 12 adds a separate privileged operator plane for production support without turning customer Owner/Admin roles into platform superusers.

Implemented:

- separate platform roles and permissions;
- minimal cross-tenant directory followed by explicit tenant RLS context;
- tenant/account/member/job/billing/sync/analysis diagnostics;
- reconciliation queue visibility without blind replay;
- safe retry allow-list for read/recompute jobs only;
- append-only support cases and operator notes;
- tenant operational kill switches for Google Ads applies, Razorpay mutations and scheduled report email;
- platform incident history;
- existing semantic AI release diagnostics;
- deployment-probe-derived release observations;
- privileged operator bootstrap CLI requiring a migration/maintenance DB role;
- no customer impersonation, no arbitrary SQL remediation, and no destructive data editor.

Internal routes:

- `/internal`
- `/internal/tenants`
- `/internal/tenants/:tenantId`
- `/internal/jobs?tenant=:tenantId`
- `/internal/support?tenant=:tenantId`
- `/internal/incidents`

Migration: `0020_epic12_internal_admin.sql`.

See `docs/EPIC12_INTERNAL_ADMIN_CONTRACT.md` and `docs/EPIC12_RESEARCH_DECISIONS.md`.

Next canonical milestone: **Epic 13 — Pilot Hardening**.

---

## Epic 13 — Pilot Hardening (v0.32.0)

Epic 13 is a launch-safety milestone rather than a customer feature expansion.

Implemented locally:

- dedicated deployed read-only Google Ads account probe using the production credential resolver;
- staging acceptance support for requiring Google provider read success and `test_account=true`;
- Worker Pool `/startup` and `/health` endpoints;
- validate-first Worker Pool startup/liveness probe configuration helper;
- Cloud SQL backup/PITR and Cloud Monitoring observability evidence helpers;
- fail-closed `recovery-pilot-gate` requiring fresh deployed acceptance plus external drill/review evidence;
- pending evidence templates for backup, restore, access, security, observability, incident response, reconciliation/rollback and pilot-tenant setup;
- pilot runbook, first-real-advertiser read-only procedure and Razorpay Test Mode boundary;
- pilot SLO/alerting contract separating infrastructure health from advertiser/product monitoring.

A green v0.32.0 package does **not** itself mean the product is pilot-qualified. Real staging/provider/infrastructure exercises—including an actual database restore drill—must still produce passing evidence.

Migration: `0021_epic13_pilot_hardening.sql`.

Next canonical milestone after real pilot qualification: **Epic 14 — V1 Launch**.

---

## Epic 14 — V1 Launch (v0.33.0)

Epic 14 adds a fail-closed public-launch control plane rather than equating a successful build with launch approval.

Implemented:

- append-only launch modes: closed, pilot-only, invite-only and public;
- exact-release V1 launch qualification import and 24-hour freshness enforcement;
- hashed/expiring pre-public workspace access grants;
- public workspace creation blocked by launch state;
- backend-authoritative Terms/Privacy URLs and version identities;
- explicit legal-acceptance confirmation and exact version matching;
- immutable legal acceptance recorded in the same transaction as workspace creation;
- production readiness checks for legal policy versions;
- external launch evidence for Google Ads production access/OAuth verification, Razorpay live readiness, TLS/legal/deletion/support/observability/security/restore/rollback/signup-abuse controls;
- internal `/internal/launch` operator surface;
- emergency launch close without deleting existing tenants.

A green v0.33.0 package is launch-capable code. It is **not** evidence that public launch has occurred. `public` mode remains a privileged exact-release promotion after the real external launch gate passes.

See `docs/EPIC14_V1_LAUNCH_CONTRACT.md`, `docs/EPIC14_RESEARCH_DECISIONS.md`, and `docs/V1_LAUNCH_RUNBOOK.md`.

---

## Launch Execution Qualification (v0.34.0)

The V1 feature sequence is complete; this release hardens the actual public-launch execution path.

Added:

- server-side Cloudflare Turnstile Siteverify enforcement for `public` workspace creation;
- exact action/hostname/freshness validation and safe Siteverify retry identity;
- PostgreSQL-serialized per-user rolling 24-hour workspace-creation limit;
- append-only/RLS challenge-verification evidence without raw tokens/secrets;
- public launch status exposes only the non-secret site key/readiness/rate boundary;
- production readiness/deployment requires anti-abuse configuration;
- `recovery-launch-public-surface` generates machine evidence for production TLS/domain reachability, published legal/privacy/deletion pages and deployed signup-abuse controls.

Actual public launch remains blocked until all independent external launch-gate evidence passes for the exact deployed release.

---

## V1 Build Completion (v0.35.0)

The canonical V1 code scope is complete. This release closes the final in-scope product-surface gaps without promoting V1.5/V2 roadmap work into V1.

Added:

- first-class `/app/business-truth` with current truth, readiness, guided versioning, protected queries and immutable lineage;
- confirmed Business Truth protected queries now feed the negative-keyword collision engine and can block unsafe exclusions;
- `/app/security-data` with access/connection/legal/retention visibility, safe configuration export and controlled data/disconnect/deletion requests;
- upgraded `/app/help` with setup/system context, product-rule explanations, append-only customer support cases and changelog;
- migration `0024_v1_customer_security_support.sql` for customer support and controlled data-request evidence;
- V1 completion authorization and frontend contracts.

Important boundary: V1 build completion is **not public-launch qualification**. The exact release must still pass the existing external pilot/launch gates for Google Ads production access, Razorpay live validation, restore/security/observability/rollback/support and other real-world evidence.

See `docs/V1_BUILD_COMPLETION_CONTRACT.md`.
