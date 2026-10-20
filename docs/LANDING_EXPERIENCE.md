# Recovery OS public experience

The public website is implemented in the existing Next.js app. `/` now opens the marketing homepage; the authenticated product remains at `/app`. No hosted site generator, new product backend, real advertiser connection, account change or deployment was used to build the experience.

## Routes and ownership

| Route | Purpose |
| --- | --- |
| `/` | Full evidence → business context → control → proof story |
| `/product` | Operating model, Search, measurement, Business Truth, actions and monitoring |
| `/for-agencies` | Prioritization, client context, account access and reporting |
| `/for-brands` | Shared business definitions and accountable performance interpretation |
| `/reporting` | Frozen evidence snapshots, presets, exports and sharing boundaries |
| `/security` | Authorization, roles, approval, reconciliation and data controls |
| `/pricing` | Four early-access scope discussions; no invented price or package entitlement |
| `/demo` | Nine-step interactive synthetic advertiser journey |
| `/connect` | Existing session → onboarding; otherwise → signup |
| `/recovery-review` | Configured booking page or support email; honest unavailable state otherwise |
| `/terms`, `/privacy` | Bridges to authoritative legal documents identified by the launch API |
| `/data-deletion` | Controlled data request instructions and existing Security & Data entry |
| `/status` | Configured public service-status destination or honest unavailable state |

Shared composition lives in `web/components/marketing`. Only the public shell imports `marketing.css`; selectors use the `m-` namespace. Existing authenticated styles, routes, roles and data workflows remain in place. The public route group does not fetch a session. The proxy bypass is explicit rather than treating unknown application paths as public.

The design uses warm ivory, graphite and olive with amber review and muted-red blocked states. It uses system fonts and HTML product compositions, with no remote font download, image-generation dependency or autoplay media. The small client boundary supports navigation, the tour and aggregate event collection. Main content remains server-rendered. Reduced motion disables transitions and animation.

## Product truth and synthetic data

Read [the pre-implementation inventory](LANDING_PRODUCT_TRUTH_INVENTORY.md) before changing claims. Public scenes use the existing `StatusBadge` and the actual Search Intelligence, Business Truth, Measurement Integrity, Action Center, Recovery Center, Monitoring and Reports concepts. They are labeled HTML illustrations of those workflows, not screenshots from a connected live account.

`web/components/marketing/demo-data.ts` is the canonical fictional account. Northstar Roofing sells residential roof repair/replacement in Austin; it excludes training, jobs and DIY materials. Its training query has $428 of illustrative candidate exposure in the 1–30 September 2026 baseline. A simulated exact-negative action is applied on 1 October. The apply worker's projection starts after that mixed application day and lasts the 30-day baseline length: **$428 projected for 2–31 October**.

The **$428 current candidate** remains in the latest completed analysis until a newer analysis is completed. A separate **$428 historical acted-on exposure** records the intervention's baseline. **Post-action observation is pending/not collected**, and **verified recovery stays $0**. These five financial classes are non-additive, even when their amounts happen to match. No observation window or measured zero is invented. The apply worker initializes its ledger without post-change observation evidence, and no production caller currently collects that evidence; the public tour does not imply an automatic observation refresh.

The measurement example is constrained because a contact page view is marked primary in Google while mapped as a supporting signal. A confirmed primary enquiry mapping and no blockers let the action pass the implemented measurement gate; this is explained before simulated approval. Downstream qualification remains unknown. The report composition is an account-scoped **Change Impact Report** containing one sample intervention, not an invented per-case report type. Reporting copy also discloses that Agency Portfolio monitoring context can include accounts outside a selected portfolio, and Monthly Client recovery evidence is current/cumulative rather than month-only.

The tour changes React state only. It cannot connect an advertiser, approve a real proposal or call the Google Ads mutation backend. The protected `roofing company` example is a separate blocked proposal; it is not the query ultimately applied.

Google authorization has the management-capable `adwords` scope. “Read-only first sync” describes the initial operation, not the OAuth permission. V1 execution supports exact ad-group negatives only. Downstream lead quality/revenue, automatic bids/budgets, enterprise SSO, causal experiment orchestration and cross-channel support are not represented as available.

## Local preview

From PowerShell in the repository:

```powershell
Set-Location G:\google-ads-v1\web
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:3000`. Public marketing pages, the synthetic tour, legal/contact unavailable states, signup display and connection entry can be reviewed without live provider credentials. Signup and authenticated app operations require their existing configuration. Missing Supabase configuration makes signup return an honest unavailable message; it does not create a mock account.

## Render configuration

Follow [the detailed Render guide](RENDER_DEPLOYMENT_STEP_BY_STEP.md) for the existing frontend, API, worker and database. This change adds the public website to the same **frontend web service**; do not create a separate static site or move the authenticated application.

In Render, open the frontend service → **Environment**. Keep the existing Supabase/API settings and set the actual values below when they are ready. Use **Save, rebuild, and deploy** after changing public build-time variables.

| Frontend environment variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_SITE_URL` | Real HTTPS origin for this frontend, e.g. the actual Render/custom domain; also used by the sitemap |
| `RECOVERY_API_BASE_URL` | Existing API origin; legal bridges query `/v1/launch/status` |
| `RECOVERY_REVIEW_BOOKING_URL` | Optional HTTPS booking destination owned by your team |
| `RECOVERY_SUPPORT_EMAIL` | Optional real support inbox; fallback for review and legal requests |
| `RECOVERY_STATUS_URL` | Optional HTTPS public service-status page; not the API health endpoint |
| `RECOVERY_DATA_DELETION_URL` | Optional HTTPS published data-request instructions |

These optional values are server settings, never invented defaults. Only HTTPS destinations without embedded credentials are accepted. The booking page does not claim an appointment was made; it sends the visitor to the real configured destination. An email link opens the visitor’s email client; it does not send automatically.

The API remains the authority for `RECOVERY_TERMS_URL`, `RECOVERY_TERMS_VERSION`, `RECOVERY_PRIVACY_URL` and `RECOVERY_PRIVACY_VERSION`. Publish the real documents and configure those on the **API service**, as described in the deployment guide. Do not point those variables back at this app’s availability bridge pages. The legal lookup times out after 1.8 seconds and displays a clear unavailable state if the API/document is not ready. Workspace legal/launch gates remain unchanged.

The sitemap only contains the eight core public routes and requires an HTTPS `NEXT_PUBLIC_SITE_URL`. No preview hostname or fabricated canonical URL is emitted. Robots guidance excludes application/auth/API/shared-report paths; robots rules are not access control.

## Conversion measurement

Browser events POST to the same-origin `/api/marketing/events`. The endpoint validates the event/source allowlists, origin, optional fetch-site metadata, UTF-8 JSON and a streamed 512-byte size limit. Accepted events become structured `recovery_marketing` records in the frontend service logs. No external analytics account is required. The implementation does not promise an analytics dashboard.

| Event | Actual trigger |
| --- | --- |
| `hero_cta_click` | Homepage primary CTA click |
| `secondary_hero_cta_click` | Hero product-tour link click |
| `connect_google_ads_click` | Public connect link click, including the homepage primary CTA |
| `product_tour_open` | First interaction that advances a tour run |
| `product_tour_complete` | Reaching the final classification step once per tour run |
| `agency_cta_click`, `brand_cta_click` | Audience entry link click |
| `pricing_open`, `security_page_open` | Relevant public page mounted in the browser |
| `book_review_click` | Public Recovery Review entry link click |
| `signup_started` | Server receives a signup submission passing the password-length prerequisite |
| `signup_completed` | Successful Supabase response identifies a new auth identity; not email confirmation or workspace activation |
| `oauth_connection_started` | Backend successfully creates the Google authorization URL |
| `oauth_connected` | Backend successfully completes callback processing, before local onboarding redirect |

Signup/OAuth confirmation events are server-only and cannot be submitted through the browser event endpoint. A query parameter or clicked CTA is never treated as successful connection. Tour replay can create a new run; these are aggregate event counts, not unique-person conversion rates.

Payloads contain fixed event/source labels, schema version and timestamp. They contain no visitor identifiers, cookies, form values, account IDs, full URLs, OAuth codes/state or arbitrary properties. Client requests omit cookies and referrer; DNT/GPC opt-outs are respected. Telemetry failures do not interrupt navigation or authentication. Operators remain responsible for hosting access logs, access permissions, retention and their published privacy disclosures.

## Verification commands

```powershell
Set-Location G:\google-ads-v1\web
npm.cmd run validate
npx.cmd tsc --noEmit --incremental false
node scripts/test-marketing-analytics.mjs
npm.cmd run build
```

There is no ESLint configuration/script in this repository; the existing `validate` contract script plus TypeScript are the static checks. `validate` uses `fileURLToPath` for Windows support and now checks the intentional public homepage plus preserved authenticated `/app` entry. Existing source-scan tests exclude installed dependencies and build output.

The browser harness `web/scripts/test-marketing-browser.mjs` accepts `MARKETING_TEST_URL`, `PLAYWRIGHT_MODULE_PATH`, `BROWSER_EXECUTABLE` and `MARKETING_SCREENSHOTS`. Point it at the running app and an installed Playwright/Chrome. Set `AXE_SCRIPT` to the absolute path of an installed axe-core `axe.min.js` to enable the automated accessibility scans; those scans are skipped when this input is absent. It checks public routes, internal destinations, responsive home/demo views, mobile navigation, complete tour progression, accepted telemetry and browser errors. Screenshots are local QA artifacts under `.cache/marketing-qa` by default, not shipped product assets.

Test signed-in activation and the real Google callback in the established pilot environment with approved credentials before external launch. Local public-page verification is not evidence that production Google authorization, billing, API connectivity or live mutations have been externally qualified.

## Completed local verification — 20 October 2026

The final production build and TypeScript check passed. `npm run validate` checked 151 source files, the marketing analytics contract script passed, and 36 Python tests across nine frontend contract suites passed with Python UTF-8 mode enabled on Windows.

The production preview was checked at `http://127.0.0.1:3001`, with no live Supabase credentials. All 13 public content routes were checked at widths of 1440, 1024, 768 and 390 pixels. The browser run recorded:

- 26 axe accessibility scans with zero reported violations. This is automated coverage, not a full accessibility certification.
- No uncaught JavaScript errors or unsolicited requests to protected `/app` or `/internal` routes.
- 23 local links/anchors checked and 11 actual telemetry requests accepted with HTTP 204.
- Working signed-out connection entry, login/signup labels and noindex metadata.
- Mobile menu dismissal by Escape with focus returned to its toggle.
- Hero tour navigation, all nine demo steps, the protected-query collision and replay.
- A final scene retaining $0 verified recovery and pending post-action observation.

The run saved `results.json` and 42 screenshots under `.cache/marketing-qa`. Desktop, tablet and mobile compositions were visually reviewed, including pricing and the completed tour. These artifacts are local review evidence; they are ignored by Git. The preview URL is available only while the local server is running. No Render deployment or live provider acceptance was performed by this verification.
