# Production hardening release

Repository change record and operator handoff, finalized 22 October 2026. Local validation and provider observations below were collected on 21 October 2026.

This candidate improves startup, authentication failure handling, API communication and release verification. It has not been deployed to the supplied Render services as part of this work. Public launch still requires the actual provider setup and acceptance in the [full Render walkthrough](RENDER_DEPLOYMENT_STEP_BY_STEP.md). Passing local checks cannot guarantee that a deployment will never fail.

## What changed

| Area | Result |
| --- | --- |
| Production API factory | Adds the missing Turnstile imports that otherwise fail when signup abuse protection is configured. Factory regression tests exercise the actual startup path and both initial onboarding routes. |
| Backend identity | The Docker build embeds its release, revision label and source hash into the installed package. `/buildz` and the worker deployment probe expose that identity. Startup rejects conflicting runtime labels. Acceptance can require and compare the API/worker stamps. |
| Docker context | An allowlist in `.dockerignore` limits the backend context to its required source/build inputs, excluding local environment files, caches and frontend artifacts. The backend still runs as a non-root user with the PDF libraries. |
| Frontend API transport | A shared server-only helper validates the API origin, prevents redirects, bounds requests to 30 seconds, sanitizes upstream failures and makes no automatic retry. Download routes read successfully before sending a completed response. |
| Authentication | Login/signup failures return safe messages. Confirmation callbacks require a real successful session exchange, use the configured site origin and prevent caching/referrer leakage. Callback and download handlers report authentication outages safely; proxy refresh failures defer to mandatory downstream authorization. Failed provider operations do not emit successful signup/connection events. |
| Onboarding and recovery | Expected service failures are shown with useful next steps; the application error boundary offers recovery without exposing upstream response bodies. Next.js navigation exceptions continue to propagate correctly. Job refresh uses the API's actual job identifier. Business Truth shows an empty state only after a successful empty history response, rather than masking a service failure. |
| Public verification | A new standard-library HTTP diagnostic checks live public pages, readiness, build identity, deployed OpenAPI and the unauthenticated behavior of the two initial onboarding endpoints. |
| Release checks | The GitHub workflow runs Linux backend tests, an actual production Docker build/image smoke check, frontend runtime tests, a production build and type checking. Existing deployment scripts stop when native deployment commands fail. |

There are **no new SQL migrations** in this change. Do not edit or manually rerun `0007_phase17_billing_onboarding.sql` as part of applying this release to a database that already has the 24 matching migrations.

## Evidence and limits

The earlier read-only inspection of the supplied API returned `200` for `/healthz`, `/readyz`, `/buildz`, `/openapi.json` and `/v1/launch/status`. Both `/v1/me` and `/v1/launch/status/me` returned the expected `401` without a token and appeared in the deployed OpenAPI document. That inspection did **not** reproduce the reported historical `404`; its exact cause remains unproven. The changes above improve detection and recovery without claiming that a particular old commit or trailing slash caused that incident.

At that inspection, the public launch response was `closed`, with legal acceptance and signup abuse readiness both false. The runtime release label was `f6376babe5e047f8c764530cdb9150c14c621676`; the older response had no embedded build stamp. That label alone did not independently establish the Render deployment's active Git commit. Treat these observations as a dated diagnostic snapshot and rerun the checks before release.

On 21 October, the first new public sweep received `503` responses from both services. An immediate health/home recheck returned `200`, and a subsequent complete sweep returned `200` for the API health, readiness, build, OpenAPI and launch-status endpoints and frontend `/`, `/login`, `/signup` and `/demo`; both protected routes again returned `401` with `AUTHENTICATION_FAILED`. The cause of the transient failures was not established. The public-mode diagnostic failed exactly `public_launch`, `public_legal` and `public_abuse`; the deployed services therefore still need public launch configuration and qualification. A later targeted reread of build identity and launch status timed out without obtaining an HTTP status while the local test host was under load; its cause is also unproven. The successful sweep establishes that point-in-time result, not continuous service availability. These checks inspect the existing deployment, not a deployment of this uncommitted candidate.

| Verification | Result recorded for this candidate |
| --- | --- |
| Latest focused backend checks | 54 passed, covering startup, build identity, acceptance, the public diagnostic and frontend onboarding-route compatibility. |
| Public diagnostic regression checks | 16 passed, including strict embedded-stamp validation. Included in the focused result above. |
| Frontend source validation | Passed for 154 source files during implementation. |
| Frontend clean dependency install | `npm ci` passed in an isolated workspace cache using the current `package.json` and `package-lock.json`; 39 packages installed. |
| Frontend runtime checks | Marketing analytics and authentication flow suites passed, along with 15 transport, route, proxy and Business Truth rendering regression groups. |
| Full Windows backend suite before the last added tests | 678 passed; one PDF test failed because the Windows host lacked native GObject/Pango. This is not a successful PDF validation. |
| Final frontend production build and type check | Passed: the combined source validation, runtime suites, `npm run build` and `npx tsc --noEmit --incremental false` command completed with exit code `0`. |
| Linux production image smoke check | Passed with UID `999`, all 24 packaged migrations, the actual Uvicorn factory returning health `200` and protected-route `401` responses, a real 18,951-byte PDF and 1,623-byte CSV, worker CLI startup and rejection of a conflicting release label. |
| Final full Linux backend test suite | **733 passed** in 56.04 seconds, with one upstream Starlette/httpx deprecation warning. Ran with network access disabled and the repository mounted read-only. |
| Tracked CI image smoke script | `deploy/smoke-backend.py` passed inside the built image: installed route table, embedded metadata and native PDF rendering. |
| GitHub Actions run for the committed candidate | Not performed by creating the workflow file; check the actual run after pushing. |
| Authenticated deployed onboarding, worker, Google Ads and billing | Not performed for this candidate. Requires the controlled live acceptance steps below. |

The source hash covers packaged Python/SQL files, `pyproject.toml`, the root `README.md` and `deploy/Dockerfile.backend`. It does not identify the container's OS libraries or resolved dependencies. Use the **same registry image digest** for API and worker to establish identical container bytes. The embedded Git revision is a build label, not a cryptographic provenance attestation.

The tested local `linux/amd64` image has image ID `sha256:18160d8a8ba42df2ee21db77faec2f1038f969ecf95fd06754c42fa559436051`. Its embedded source hash, `71b7bced29f7ca1c0699d928459e84383fdad3b3f11e7aab4a7410e4dd0ebaf3`, matched the current local backend inputs. It was built from the uncommitted working tree as `local-validation`, using the existing HEAD only as its revision label. This is local test evidence, not a registry digest or an approved release of that old commit. Commit the reviewed changes and build the named release from that new commit as described below.

The first local image smoke attempt exceeded its 12-second startup allowance while the host was under memory pressure. With a bounded 120-second test allowance after the competing build finished, it completed in 9.4 seconds. No production code was changed for that rerun. This is local image verification, not evidence of Render latency or live database/provider connectivity.

Before enabling public launch, investigate any recurring `503` in the affected Render service's **Events** and **Logs**. Record the time and deployment ID, inspect the first relevant startup/runtime error, correct its cause and repeat the full HTTP diagnostic. Do not infer a free-tier limitation or cold start from the status code alone. A later successful response does not explain an earlier failure.

## Update the existing Render services

The supplied service origins are:

| Service | Origin |
| --- | --- |
| API | `https://recovery-api-9efn.onrender.com` |
| Website/dashboard | `https://recovery-web-7nnv.onrender.com` |

Verify the corresponding service names in your Render workspace. Use the exact assigned URLs if the services have changed.

### 1. Prepare the exact candidate

1. Open this project in VS Code.
2. Review the changed files, including `web/package-lock.json`, and commit the reviewed candidate. Do not commit `.env` files, credentials, generated `.next`/`node_modules` directories or private release evidence.
3. Push the commit to the intended GitHub deployment branch.
4. Open **Terminal → New Terminal** at the repository root and run:

```powershell
git status --short
git rev-parse HEAD
```

5. Confirm no unreviewed changes remain and record the full SHA returned by the second command. Use that value as `RECOVERY_RELEASE_ID`; do not reuse the old `f6376...` value for changed code.
6. Open GitHub → repository → **Actions → Production checks**. Wait for both jobs for that exact commit to pass. Resolve failures before deploying it.
7. In Render, record the current API, worker and frontend deployment IDs and the previous backend image digest where applicable. Keep the previous approved artifact available for rollback.

### 2. Set the frontend's connected origins

1. Open [Render Dashboard](https://dashboard.render.com).
2. Select the workspace containing the supplied services.
3. Open the `recovery-web` service that owns `recovery-web-7nnv.onrender.com`.
4. Click **Environment**.
5. Set `RECOVERY_API_BASE_URL` to `https://recovery-api-9efn.onrender.com`.
6. Set `NEXT_PUBLIC_SITE_URL` to `https://recovery-web-7nnv.onrender.com`.
7. Confirm the two public Supabase values refer to the same Supabase project as the API's `SUPABASE_URL`.
8. Set `NODE_VERSION=24.14.0` to match the release workflow; keep `NODE_ENV=production`.
9. Open **Settings** and confirm Root Directory is `web`, Build Command is `npm ci && npm run build`, and Start Command is `npm run start -- --hostname 0.0.0.0 --port $PORT`.
10. Save settings. Deploy this frontend from the reviewed candidate when the matching backend is available in step 4.

### 3. Build the matching backend

For the strongest production identity, follow section 19 of the full guide: build `deploy/Dockerfile.backend` once with both non-secret arguments below, push it, record the image digest, then use that digest for both API and worker:

```text
RECOVERY_RELEASE_ID=FULL-REVIEWED-COMMIT-SHA
RECOVERY_BUILD_REVISION=FULL-REVIEWED-COMMIT-SHA
```

If retaining the existing Git-based Render services:

1. Open the API service → **Environment**.
2. Set `RECOVERY_RELEASE_ID` to the full reviewed commit SHA before its new image build.
3. Leave `RECOVERY_BUILD_REVISION` unset so the Docker build uses Render's actual `RENDER_GIT_COMMIT`. Do not set a manual value for `RENDER_GIT_COMMIT`.
4. Confirm Root Directory is empty, Dockerfile Path is `deploy/Dockerfile.backend`, Docker Command is empty and Health Check Path is `/readyz`.
5. Repeat the release setting on the worker, using the identical commit. Keep its Docker Command `recovery-worker`.
6. Preserve each service's correct role-specific database credentials and provider settings. The worker DSN must not be copied onto the frontend.
7. Use **Manual Deploy** to select the reviewed commit for both services. Verify the selected commit before starting each deployment.

Render translates environment settings into Docker build arguments; its Git commit variable is available at build and runtime. These mechanics were rechecked on 21 October 2026. [Render Docker settings](https://render.com/docs/docker), [Render environment variables](https://render.com/docs/environment-variables)

### 4. Deploy and inspect the candidate

1. Deploy the API and worker from the matching reviewed code/image, then deploy the matching frontend commit. Coordinate the rollout and keep new workspace creation restricted while validating it.
2. Open each service's **Events** and verify deployment succeeded. If one fails, open its failed event and correct the first relevant error.
3. Open API `/healthz`, then `/readyz`. Both must return `200`; readiness must show the database ready.
4. Open `https://recovery-api-9efn.onrender.com/buildz`.
5. Confirm `release_id` and `build_release_id` equal the reviewed SHA, `build_identity` is `embedded`, `build_revision` equals the intended SHA, and `build_source_sha256` is present.
6. Compare `build_revision` with the API's active Render deployment commit when using Git deployment. Record the registry digest too when using a prebuilt image.
7. Confirm the worker remains running without a repeating startup traceback. Its identity is checked through the worker probe in authenticated acceptance, not through a public worker URL.
8. A build-identity startup error means runtime labels and the selected artifact disagree. Choose or rebuild the matching artifact; changing labels cannot turn older code into the candidate.

### 5. Run the public diagnostic

1. Return to the local repository terminal.
2. Replace `FULL-REVIEWED-COMMIT-SHA` below with the new SHA, then run:

```powershell
python .\src\recovery\deployment_contract.py --api-url https://recovery-api-9efn.onrender.com --dashboard-url https://recovery-web-7nnv.onrender.com --expected-release-id FULL-REVIEWED-COMMIT-SHA --require-build-identity
```

3. Require `passed: true` and exit code `0`. The script uses no credentials, SQL or mutation requests.
4. Confirm both protected onboarding routes produce `401`, not `404`, and both appear in OpenAPI.
5. Check the public homepage, `/login`, `/signup` and `/demo` in a browser too. Confirm the recovery links and navigation work.

The diagnostic establishes only its listed public HTTP contract. It does not prove sign-in, worker processing, tenant isolation, paid entitlement or provider consent.

### 6. Prove the signed-in path and worker

1. Open a fresh private browser window at `https://recovery-web-7nnv.onrender.com/login`.
2. Sign in using a controlled test user. Visit `/onboarding` and verify the page renders for a user with no workspace as well as an existing controlled workspace user.
3. Test a new signup and the actual Supabase confirmation email flow. Verify confirmation reaches the correct origin and an expired/reused link gives a recoverable sign-in message.
4. Follow sections 15–16 of the full guide for controlled pilot access, real legal document acceptance, test billing, Google consent, discovery, read-only sync and analysis.
5. Verify a second controlled tenant cannot read the first tenant's jobs/accounts.
6. Run section 17's authenticated acceptance with `--require-build-identity`, then its full Google test-account/billing variant. The worker round trip must succeed and report the same embedded identity as the API.
7. If reports are enabled, generate and download an actual deployed PDF and CSV, then verify any configured report email delivery.

If a request times out, refresh the operation's state before retrying it. The server may have completed a mutation even when its response did not reach the browser. The frontend intentionally does not replay mutations automatically.

### 7. Qualify public launch

1. Complete the real provider verification/access, live billing, published policies, monitored support, Turnstile, backup restore, access review and operational evidence in sections 18–20 of the full guide.
2. Run the production readiness and authenticated production acceptance commands using the exact candidate release and `--require-build-identity`.
3. Generate and import a fresh qualified launch report through `/internal/launch` as the authorized platform administrator.
4. Complete the controlled canary flow before changing launch mode to **Public**.
5. After that deliberate transition, repeat the public diagnostic with `--require-public` appended. Require legal readiness, abuse readiness and public workspace creation to pass.
6. Monitor the actual deployment and retain all acceptance/release evidence. A local test suite or green Render build does not fill in missing external evidence.

## Rollback

Use section 21 of the full guide. Keep API, worker and frontend versions coordinated, select the previous approved artifact, and restore its matching runtime release label. Confirm schema compatibility first; application rollback does not undo migrations. This candidate adds no schema migration. Close new workspace creation if necessary while investigating, then repeat readiness and worker acceptance on the restored release.
