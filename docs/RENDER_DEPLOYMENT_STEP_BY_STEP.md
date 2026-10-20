# Google Ads Recovery OS deployment on Render

Detailed operator guide for this repository. Provider instructions researched 18 October 2026; repository-specific instructions updated 20 October 2026 for the public landing experience.

This guide takes you from the project on your Windows computer to a working Render deployment, then through controlled customer onboarding and public-launch checks. Follow the sections in order. Each checkpoint tells you what must work before continuing.

The provider instructions were checked against documentation on the research date above. They have not been executed against your Render, Supabase, Google, or Razorpay accounts. Dashboard wording can vary slightly by account and UI version. A completed Render build is infrastructure success; public launch also requires the application checks described below.

To read comfortably, open this file in VS Code and press **Ctrl+Shift+V** for Markdown Preview. Follow sections 1–10 for the first working login, 11–16 for connected pilot use, and 17–23 for validation and production operations.

## Contents

1. [Deployment architecture](#1-understand-what-you-will-deploy)
2. [Private worksheet](#2-prepare-a-private-deployment-worksheet)
3. [GitHub preparation](#3-put-the-correct-project-in-github)
4. [Supabase setup](#4-create-or-identify-the-supabase-project)
5. [Database migrations](#5-apply-every-database-migration-locally)
6. [Database roles](#6-create-separate-database-runtime-roles)
7. [Render account](#7-create-your-render-account-and-connect-github)
8. [API deployment](#8-deploy-the-api)
9. [Dashboard deployment](#9-deploy-the-dashboard)
10. [Login and URL connections](#10-connect-the-deployed-urls-and-supabase-login)
11. [Google Cloud and OAuth](#11-configure-google-cloud-and-oauth)
12. [Worker deployment](#12-deploy-the-worker)
13. [Policy links and email](#13-configure-legal-links-and-optional-report-delivery)
14. [Razorpay billing](#14-add-razorpay-test-billing)
15. [Platform administrator and pilot access](#15-bootstrap-your-platform-administrator-and-enable-pilot-access)
16. [App walkthrough](#16-walk-through-the-app-and-prove-it-works)
17. [Readiness and acceptance](#17-run-readiness-and-deployed-acceptance)
18. [Custom domain](#18-add-your-custom-domain)
19. [Production configuration](#19-prepare-the-production-configuration)
20. [Launch qualification](#20-complete-the-applications-pilot-and-public-launch-gates)
21. [Updates and rollback](#21-deploy-future-updates)
22. [Troubleshooting](#22-troubleshooting-by-symptom)
23. [Final checklist](#23-final-operator-checklist)

## 1. Understand what you will deploy

You will create these three services in Render:

| Name used in this guide | Render type | Purpose |
| --- | --- | --- |
| `recovery-api` | Web Service, Docker | FastAPI backend, authorization, webhooks, job submission |
| `recovery-worker` | Background Worker, Docker | Google account discovery, sync, analysis, reports and queued work |
| `recovery-web` | Web Service, Node | Public website, authenticated dashboard, login and Next.js server routes |

The same GitHub repository supplies all three. The dashboard root is `web`. The API and worker build from the repository root using `deploy/Dockerfile.backend`.

The frontend now serves the public landing page at `/` and the signed-in product at `/app`. Product, audience, reporting, security, pricing and demo pages use the same frontend service. You do not need a separate static site. See [the landing experience setup and verification record](LANDING_EXPERIENCE.md) for its routes, optional settings and product-claim boundaries.

Other services remain external:

| Provider | Used for |
| --- | --- |
| Supabase | PostgreSQL database and user authentication |
| Google Cloud | Google Ads OAuth client, API access and Secret Manager token storage |
| Gemini | Semantic AI credential used by the backend worker |
| Razorpay | Subscription billing when enabled |
| Cloudflare Turnstile | Public workspace creation abuse protection |
| Your email provider | Production authentication email and optional report delivery |

The flow is browser → Next.js → FastAPI → PostgreSQL. The worker reads the PostgreSQL queue. There is no Redis requirement in the inspected code. Do not create a second empty Render database and assume it contains your Supabase data.

Use a Node Web Service for this dashboard because it contains server-side routes and cookie authentication. Render distinguishes this from a static export. [Render Next.js deployment](https://render.com/docs/deploy-nextjs-app)

Use a Background Worker for the long-running worker process. It has no customer-facing URL. [Render background workers](https://render.com/docs/background-workers)

### What the words mean

- **Repository:** the project stored in GitHub.
- **Branch:** the version line Render deploys, often `main`.
- **Build:** installing dependencies and preparing runnable application files.
- **Deploy:** starting that build on Render.
- **Environment variable:** a named configuration setting, such as `SUPABASE_URL`.
- **DSN:** a PostgreSQL connection URL containing a database username and password.
- **Migration:** a versioned SQL change that creates or updates database structures.
- **Origin:** `https://hostname`, without a page path or trailing slash.
- **Release ID:** a shared identifier for the exact code version deployed to API and worker.

### Choose the first deployment mode

Start with `RECOVERY_ENVIRONMENT=staging` and `BILLING_ENABLED=false`. Complete the infrastructure and pilot walkthrough. Add test billing before billing acceptance. Create a separate production environment for real customers; do not mix customer evidence with staging test data.

Use paid, continuously running instances for production. Check the current price displayed before creating each resource. This document does not promise a fixed monthly cost or that a free account supports every required feature. Budget for all three services plus external providers.

## 2. Prepare a private deployment worksheet

1. Open a password manager or a private operator note outside the Git repository.
2. Create a note named `Recovery Render deployment`.
3. Record the non-secret items below. Keep passwords and keys in the password manager.
4. Replace example values throughout this guide with your own values. Never paste the angle brackets around a placeholder.

| Worksheet field | Example or source |
| --- | --- |
| GitHub repository | `YOUR-ACCOUNT/google-ads-v1` |
| Branch | Your actual branch, not automatically `main` |
| Release ID | Full Git commit SHA from `git rev-parse HEAD` |
| Supabase project URL | `https://YOUR-PROJECT.supabase.co` |
| Supabase project reference | From the project dashboard |
| Migration database DSN | Privileged connection, local maintenance only |
| API database DSN | Dedicated `recovery_api` role |
| Worker database DSN | Dedicated `recovery_worker` role |
| Actual API URL | Copy from Render after creation |
| Actual dashboard URL | Copy from Render after creation |
| Google Cloud project ID | Project ID, not project display name |
| Google OAuth client ID | Ends in `.apps.googleusercontent.com` |
| Operator user UUID | From Supabase Authentication Users |

`https://recovery-web.onrender.com` is an example, not a reserved address. Render can assign a suffix. Always copy the URL displayed in your own service.

## 3. Put the correct project in GitHub

### If the repository is already in GitHub

1. Open your browser.
2. Open [GitHub](https://github.com).
3. Sign in.
4. Open your project repository.
5. Use the branch selector above the file list to select the branch you intend to deploy.
6. Confirm you can see `pyproject.toml`, `src`, `deploy` and `web` at the top level.
7. Open `deploy` and confirm `Dockerfile.backend` exists.
8. Open `web` and confirm `package.json` exists.
9. Confirm the latest intended changes have been pushed. Files only on your computer are not visible to Render.

### If the project is only on your Windows computer

1. Open GitHub Desktop and sign in to GitHub.
2. Choose **File → Add local repository**.
3. Select `G:\google-ads-v1`.
4. If it is not already a Git repository, use the displayed **create a repository here** option and keep the existing project directory.
5. Review the changed-file list before committing.
6. Exclude real `.env` files, database passwords, Google JSON private keys, customer exports, `.venv`, `node_modules` and `.next`.
7. The current `.gitignore` excludes `node_modules/`, `.next/`, `.cache/` and `*.tsbuildinfo`. Confirm those generated files are absent from the commit; ignore rules do not remove files already tracked by Git. Keep `web/package-lock.json` in the commit because Render needs it for the reproducible dependency install.
8. If a secret was already committed, removing it from the latest commit is insufficient: rotate the exposed credential and clean the repository history before publishing.
9. Enter a commit summary, such as `Prepare Render deployment`.
10. Click **Commit to** your selected branch.
11. Click **Publish repository**.
12. Keep the repository private unless you intentionally want the source public.
13. Publish it, then click **View on GitHub** and perform the file checks above.

### Record the release

1. Open VS Code.
2. Choose **File → Open Folder** and select `G:\google-ads-v1`.
3. Choose **Terminal → New Terminal**.
4. Run:

```powershell
git branch --show-current
git rev-parse HEAD
```

5. Save the branch and full commit SHA in your worksheet.
6. Ensure that exact commit is pushed to GitHub.

**Checkpoint:** GitHub contains the intended code and you know its branch and commit SHA.

## 4. Create or identify the Supabase project

Skip project creation if you already have the intended staging project. Do not create a second project accidentally.

1. Open [Supabase](https://supabase.com/dashboard).
2. Sign in.
3. Click **New project**.
4. Select your organization.
5. Enter a clear project name, such as `recovery-staging`.
6. Generate and save a strong database password.
7. Select a region close to your intended Render region.
8. Create the project and wait until provisioning finishes.
9. Open the project settings/API area.
10. Copy the project URL.
11. Copy the **publishable key**. This goes into the dashboard later.
12. Do not substitute a Supabase secret key or `service_role` key for the publishable key.

### Obtain a usable database connection

1. Click **Connect** in the Supabase project.
2. Select the PostgreSQL URI connection option.
3. Prefer the direct connection for migrations when your computer can reach it.
4. If the direct host is IPv6-only and your network cannot reach it, select **Session pooler**. Copy the exact host, port and username shown.
5. Use session mode, typically port `5432`, for this application's runtime connections. Do not select transaction mode/port `6543` for this guide.
6. Replace the password placeholder with the database password. URL-encode special characters in the password when building a URI.
7. Preserve the connection string's options and require TLS, for example `?sslmode=require` if there are no existing query options.
8. Save this privileged DSN as the migration connection. Do not put it into the dashboard or use it as the API runtime connection.

Supabase documents direct connections and IPv4-compatible session pooling separately. Copy the connection details from the project instead of inventing the hostname. [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres)

### Check authentication signing keys

1. Open **Authentication**.
2. Find **Signing Keys** in the authentication settings.
3. Confirm the active signing algorithm is asymmetric: **ES256** or **RS256**.
4. This repository rejects legacy HS256 user tokens.
5. If migrating an existing project's keys, follow Supabase's rotation procedure and test new sign-ins before retiring old keys. Do not abruptly revoke a key used by active users.

[Supabase signing key guidance](https://supabase.com/docs/guides/auth/signing-keys)

## 5. Apply every database migration locally

The current repository contains **24 SQL migrations**, from `0001_phase8_core.sql` through `0024_v1_customer_security_support.sql`. Some older README sections mention only two or six; use the migration runner, which discovers the complete packaged set.

Run these commands in your Windows terminal, not in the Render build-command field.

1. Open VS Code's terminal in `G:\google-ads-v1`.
2. Check Python is available:

```powershell
python --version
```

3. Use a supported Python version: this package declares Python 3.11 through 3.14; its Docker image uses 3.13.
4. Create a deployment virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .
```

5. Wait for installation to finish successfully. If a pinned dependency cannot be downloaded, stop and resolve that exact package/version error. Do not silently replace pinned versions with unrelated versions.
6. Run this command. It prompts for the privileged DSN without putting its value into your shell history:

```powershell
.\.venv\Scripts\python.exe -c "import os,getpass; os.environ['DATABASE_URL']=getpass.getpass('Migration database URL: '); from recovery.deployment import migration_main; migration_main()"
```

7. At the prompt, paste the migration DSN and press Enter. Characters will not be shown.
8. Wait for the JSON result.
9. Expected result: `"status": "ok"` and the newly applied migration filenames.
10. A rerun on an unchanged database can show an empty `applied` list; that is normal.
11. In Supabase, open **SQL Editor → New query**.
12. Run this read-only query:

```sql
SELECT version FROM recovery.schema_migrations ORDER BY version;
```

13. Confirm all 24 filenames are present for this code version.
14. Do not edit historical SQL migration files to bypass a checksum error.

**Checkpoint:** migrations finished successfully on the intended database.

## 6. Create separate database runtime roles

This is a privileged database setup step. Perform it in the intended Supabase project's SQL Editor as its database administrator, after migrations. The SQL below is a starting runtime grant configuration for the inspected schema; validate tenant isolation before public launch. Do not use it as a claim that a complete security review has been performed.

1. Generate two different strong passwords in your password manager.
2. Open **SQL Editor → New query**.
3. Replace the two password placeholders below locally in the editor. Use passwords without a single quote, or escape single quotes correctly for SQL.
4. Run the SQL once for a fresh database. If the roles already exist, inspect and reuse them instead of dropping them.

```sql
CREATE ROLE recovery_api LOGIN PASSWORD 'REPLACE_API_PASSWORD'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE recovery_worker LOGIN PASSWORD 'REPLACE_WORKER_PASSWORD'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;

GRANT CONNECT ON DATABASE postgres TO recovery_api, recovery_worker;
GRANT USAGE ON SCHEMA recovery, recovery_private TO recovery_api, recovery_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA recovery
  TO recovery_api, recovery_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA recovery
  TO recovery_api, recovery_worker;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA recovery_private
  TO recovery_api, recovery_worker;

-- Migration history and operator grants are maintenance-owned.
REVOKE INSERT, UPDATE, DELETE ON recovery.schema_migrations
  FROM recovery_api, recovery_worker;
REVOKE INSERT, UPDATE, DELETE ON recovery.platform_operator_events
  FROM recovery_api, recovery_worker;
```

5. If your database name is not `postgres`, change the `GRANT CONNECT` database name.
6. If your managed database administrator cannot create a BYPASSRLS worker role, have the database administrator provision an approved cross-tenant worker role. Do not bypass the error by giving the API a privileged database owner connection.
7. Verify the roles:

```sql
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole
FROM pg_roles
WHERE rolname IN ('recovery_api', 'recovery_worker');
```

8. The API must show `rolsuper=false`, `rolbypassrls=false`, `rolcreaterole=false`.
9. The worker needs cross-tenant queue access; its privileged credentials belong only in the worker/maintenance environment.
10. Build an API DSN using the new API username and password.
11. Build a worker DSN using the new worker username and password.
12. With a Supabase session pooler, the username generally includes the project reference, such as `recovery_api.PROJECT_REF`. Use your pooler's documented format. Direct connections use the role name itself.
13. Test both connections before continuing. A correct password with the wrong pooler username still fails.
14. Keep `recovery` and `recovery_private` out of Supabase's browser-exposed Data API schemas. Do not grant these schemas to `anon` or `authenticated`.
15. After future migrations, reapply the runtime grants to new objects and the maintenance-table revocations. Audit new tables and functions rather than assuming old grants cover them.

RLS policies and immutable-data triggers remain active; the broad table DML grants above do not remove them. The worker intentionally operates across tenants, so its credential must remain separate.

## 7. Create your Render account and connect GitHub

1. Open [Render Dashboard](https://dashboard.render.com).
2. Sign up or sign in.
3. Select the workspace in which you want the services to live.
4. Add billing information if required for your selected instance types.
5. Click **New + → Web Service**.
6. Choose the Git repository deployment option.
7. Connect GitHub when prompted.
8. On GitHub's authorization screen, grant Render access to the intended repository.
9. Return to Render.
10. Locate the project repository and click **Connect**.
11. If it does not appear, open the GitHub app's repository access settings and allow that repository, then refresh Render.

Render supports linked Git repositories and build configuration on the new service form. [Render web services](https://render.com/docs/web-services)

## 8. Deploy the API

Use the Web Service creation form opened in the previous section.

### Fill the service fields

| Field | Enter or select |
| --- | --- |
| Name | `recovery-api` or a unique variation |
| Branch | Your recorded deployment branch |
| Region | A region near your database; use the same region for all three services |
| Language or Runtime | `Docker` |
| Root Directory | Leave empty |
| Dockerfile Path | `deploy/Dockerfile.backend` |
| Docker Build Context Directory, if shown | `.` |
| Docker Command | Leave empty; use the Dockerfile's default API command |
| Instance Type | An appropriate paid instance for production; monitor memory usage |
| Health Check Path | `/readyz` |
| Pre-Deploy Command | Leave empty for this walkthrough; section 5 already ran migrations |
| Auto-Deploy | Disable initially so you can coordinate API and worker releases |

Do not set the root to `deploy`. The Dockerfile copies `pyproject.toml`, `README.md` and `src` from the repository root. It also installs native PDF-rendering dependencies, which is why this guide uses the existing Dockerfile.

Render exposes the Dockerfile path and optional Docker Command override in Docker service configuration. [Render Docker configuration](https://render.com/docs/docker)

### Add the initial API environment variables

1. Find **Environment Variables** on the creation form, expanding **Advanced** if needed.
2. Add one row per variable below.
3. The left box is the name/key. The right box is the value.
4. Paste values without surrounding quotation marks.
5. For the initial origin, use the intended dashboard origin if known, otherwise `https://example.invalid` temporarily. Replace it with the actual Render dashboard origin in section 10 before testing login.

| Key | Value |
| --- | --- |
| `DATABASE_URL` | API role DSN from section 6 |
| `SUPABASE_URL` | Your Supabase project URL |
| `API_ALLOWED_ORIGINS` | Temporary intended dashboard origin, then actual dashboard origin |
| `RECOVERY_ENVIRONMENT` | `staging` |
| `RECOVERY_RELEASE_ID` | Recorded full Git commit SHA |
| `BILLING_ENABLED` | `false` |
| `BILLING_GRACE_HOURS` | `0` |

The Dockerfile supplies `PORT=8080`, and its command listens on `0.0.0.0` using `PORT`. There is no need to hard-code a localhost listener or add a Windows start command.

### Start and verify the API deployment

1. Click **Deploy Web Service** or the equivalent creation button.
2. Open **Events** to watch build/deploy progress.
3. Open **Logs** if a build or startup step fails.
4. Wait for the service to become live.
5. Copy its full HTTPS URL into the worksheet.
6. Open a new browser tab at `YOUR_API_URL/healthz`.
7. Confirm an HTTP 200 response and JSON.
8. Open `YOUR_API_URL/readyz`.
9. Confirm HTTP 200 and database/migration readiness.
10. If `/healthz` works but `/readyz` fails, check the API DSN, database grants and migration version. Do not declare deployment complete based on `/healthz` alone.

**Checkpoint:** both health endpoints work with the intended database.

## 9. Deploy the dashboard

1. Return to the Render workspace overview.
2. Click **New + → Web Service**.
3. Select the same GitHub repository.
4. Fill the fields below.

| Field | Value |
| --- | --- |
| Name | `recovery-web` or a unique variation |
| Branch | Same recorded branch |
| Region | Same chosen region |
| Language or Runtime | `Node` |
| Root Directory | `web` |
| Build Command | `npm ci && npm run build` |
| Start Command | `npm run start -- --hostname 0.0.0.0 --port $PORT` |
| Auto-Deploy | Disable initially |
| Health Check Path, if needed | `/login` |

The repository now includes `web/package-lock.json`. Commit and push it together with `web/package.json`; `npm ci` installs that locked dependency set. If Render reports a missing or mismatched lockfile, check the selected branch, commit and `web` Root Directory. Resolve dependency changes locally and commit the updated lockfile before retrying.

5. Add these environment variables before the build:

| Key | Value |
| --- | --- |
| `NODE_VERSION` | `24.21.0`, the current Render-documented default; validate it with this project's build |
| `NODE_ENV` | `production` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key |
| `RECOVERY_API_BASE_URL` | Actual HTTPS API URL from section 8, without trailing slash |
| `NEXT_PUBLIC_SITE_URL` | Intended dashboard URL; correct to assigned URL immediately after creation |

6. If the dashboard URL is not yet known, use `https://example.invalid` for `NEXT_PUBLIC_SITE_URL` only for the first build, then correct and rebuild before signup.
7. Click **Deploy Web Service**.
8. Wait for a successful build and live service.
9. Copy its assigned HTTPS URL from Render.
10. Open that URL with `/login` appended.
11. Confirm the login page displays.
12. Open the service's **Environment** page.
13. Replace `NEXT_PUBLIC_SITE_URL` with its actual HTTPS origin.
14. Choose **Save, rebuild, and deploy**.

Public Next.js values can be embedded during build, so rebuild after changing them. [Next.js environment handling](https://nextjs.org/docs/app/guides/self-hosting)

Render supports selecting the runtime with `NODE_VERSION`; pinning it avoids a new service silently choosing a different default. [Render Node version selection](https://render.com/docs/node-version)

Do not add `DATABASE_URL`, the worker DSN, Google private keys, Razorpay secrets or a Supabase secret/service-role key to this frontend service. `RECOVERY_API_BASE_URL` is read by its server-side code and does not need a `NEXT_PUBLIC_` prefix.

### Configure the public website's contact and service links

These optional settings belong on `recovery-web`. Setting a value on the API does not automatically copy it to the frontend.

1. Open Render's workspace overview.
2. Click your `recovery-web` service.
3. Click **Environment**.
4. Click **Add Environment Variable**.
5. Enter a key from the table below in the name box.
6. Enter your actual destination in the value box, without quotation marks.
7. Repeat for each destination you have ready. Leave unavailable optional settings unset; do not publish example addresses.

| Key on `recovery-web` | What to enter |
| --- | --- |
| `RECOVERY_REVIEW_BOOKING_URL` | Your real HTTPS appointment-booking page |
| `RECOVERY_SUPPORT_EMAIL` | Your monitored support email address |
| `RECOVERY_STATUS_URL` | Your real HTTPS public service-status page, not `/healthz` |
| `RECOVERY_DATA_DELETION_URL` | Your real HTTPS published data-request instructions |

8. Choose **Save, rebuild, and deploy**.
9. Wait for the deployment to become live.
10. Open the frontend's exact HTTPS origin with no page path. Confirm the public homepage appears.
11. Open `/product`, `/for-agencies`, `/for-brands`, `/reporting`, `/security` and `/pricing`. Confirm each page loads and navigation works.
12. Open `/demo`. Advance through all nine steps and try replay. The tour uses fictional data; it does not change an advertiser account.
13. Open `/recovery-review`. Confirm its booking link opens your configured booking page, or its email link opens a message to your actual support address. A link click is not a completed booking.
14. Open `/status` and `/data-deletion`. Confirm configured external destinations are correct. When a setting is absent, the page explains the unavailable contact/status information.
15. Open `/terms` and `/privacy`. These are availability pages that link to your real policy documents after section 13 is configured; they do not supply reviewed policies themselves.
16. In a signed-out browser, use the homepage connection action. Confirm it reaches signup. A signed-in user continues through onboarding; Google authorization happens in that workflow.
17. Check the homepage and navigation on a phone or a narrow browser window.

**Checkpoint:** the public website and synthetic tour work on the same service as login. Real signup, Google authorization and worker jobs still require the following setup and acceptance steps.

## 10. Connect the deployed URLs and Supabase login

### Correct the API origin

1. Open Render → `recovery-api` → **Environment**.
2. Edit `API_ALLOWED_ORIGINS`.
3. Paste the actual dashboard origin, for example `https://recovery-web-abc.onrender.com`.
4. Do not append `/login`, `/onboarding` or a trailing slash.
5. Save and deploy.

To change an existing service's variables, use **Environment → Add Environment Variable**, then save with a deploy or rebuild. **Save only** does not change the running process until deployment. [Render environment settings](https://render.com/docs/configure-environment-variables)

### Configure the authentication redirect

1. Open your Supabase project.
2. Open **Authentication → URL Configuration**.
3. Set **Site URL** to the actual dashboard origin.
4. Under redirect URLs, add exactly:

```text
https://YOUR-DASHBOARD-HOST/api/auth/callback
```

5. Save the settings.
6. Under authentication providers, confirm Email authentication is enabled.
7. Configure an approved SMTP sender for production email delivery. Use the provider's real SMTP settings; test delivery before inviting customers.
8. Open the deployed dashboard `/signup` page.
9. Enter your operator email and a password of at least 10 characters.
10. Submit.
11. If confirmation is enabled, open the confirmation email in the same browser used for signup and follow the link.
12. Sign in at `/login`.
13. Open `/onboarding` once so the backend registers the application user.

Supabase's Site URL and allowed redirect URLs control post-authentication destinations. [Supabase redirect configuration](https://supabase.com/docs/guides/auth/redirect-urls)

**Expected:** the user can sign in. Workspace creation may say it is closed. That is the application's launch control, not a broken deployment. Section 15 enables controlled pilot access.

## 11. Configure Google Cloud and OAuth

The frontend's Google Ads callback is different from the Supabase callback:

| Purpose | Exact route on the dashboard |
| --- | --- |
| Supabase email/login confirmation | `/api/auth/callback` |
| Connect a Google Ads account | `/api/google-ads/oauth/callback` |

### Prepare the Google project

1. Open [Google Cloud Console](https://console.cloud.google.com).
2. Select the intended project in the top project selector, or create a dedicated project.
3. Record its project ID.
4. Open **APIs & Services → Library**.
5. Search for **Google Ads API**, open it and enable it.
6. Search for **Secret Manager API**, open it and enable it.
7. Attach billing if Google requires it for the resources you use.
8. Check Google Ads API access for this Cloud project. Test access and production access are different.

Google's current documentation places API access on the Cloud project; legacy developer-token instructions from before September 2026 are not the configuration path for this repository. [Google project setup](https://developers.google.com/google-ads/api/docs/oauth/cloud-project), [developer-token transition](https://developers.google.com/google-ads/api/docs/api-policy/developer-token)

### Create the OAuth web client

1. In Google Cloud, open **Google Auth Platform**, or **APIs & Services → OAuth consent screen** if that is the displayed navigation.
2. Configure the app name, support email, audience and developer contact.
3. For staging, keep the app in testing and add your actual testing Google account under test users.
4. Configure the Google Ads scope required by the application: `https://www.googleapis.com/auth/adwords`.
5. Complete the required branding/domain details. Production verification can require your own verified domain and published policies.
6. Open **Clients** or **Credentials**.
7. Choose **Create client → Web application**.
8. Name it `Recovery Render staging`.
9. Add this exact **Authorized redirect URI**:

```text
https://YOUR-DASHBOARD-HOST/api/google-ads/oauth/callback
```

10. If entering an authorized JavaScript origin, use only the dashboard origin.
11. Save the client.
12. Store the client ID and client secret privately.
13. For production, complete Google's required verification and API access process before setting acknowledgement variables. Saving a client is not verification approval.

### Give Render access to Secret Manager

The code uses Google Application Default Credentials to store per-customer refresh tokens. Render does not automatically have a Google Cloud service identity.

1. In Google Cloud, open **IAM & Admin → Service Accounts**.
2. Create `recovery-render-api`.
3. Create a separate `recovery-render-worker`.
4. Give the API identity a project custom role with these required vault operations: `secretmanager.secrets.get`, `secretmanager.secrets.create`, `secretmanager.secrets.delete`, `secretmanager.versions.add`, `secretmanager.versions.access`.
5. To create that role, open **IAM & Admin → Roles → Create role**, enter a descriptive name, add those permissions, and create it. Then grant it to the API service account through **IAM → Grant access**.
6. Give the worker **Secret Manager Secret Accessor** in the dedicated project or the appropriate secret scope. It must read the secrets the API creates.
7. Avoid Project Owner/Editor as a shortcut. The permission list above comes from the repository's token-vault operations; validate it with an actual connect/reconnect/disconnect test.
8. Open each service account → **Keys → Add key → Create new key → JSON**, if organizational policy permits key creation.
9. Save each JSON securely outside the Git repository.
10. If keys are prohibited, have your Google administrator configure an approved workload identity solution. Do not disable an organizational policy just to continue the walkthrough.

[Secret Manager permissions](https://docs.cloud.google.com/secret-manager/docs/access-control), [service account key creation](https://docs.cloud.google.com/iam/docs/keys-create-delete)

### Add the API secret file

1. Open Render → `recovery-api` → **Environment**.
2. Under **Secret Files**, click **Add Secret File**.
3. Filename: `gcp-api.json`.
4. Paste the API service account JSON into Contents.
5. Save.
6. Add `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/gcp-api.json` as an environment variable.
7. Add all four OAuth variables together:

| Variable | Value |
| --- | --- |
| `GOOGLE_ADS_OAUTH_CLIENT_ID` | Your web OAuth client ID |
| `GOOGLE_ADS_OAUTH_CLIENT_SECRET` | Its secret |
| `GOOGLE_ADS_OAUTH_REDIRECT_URI` | Exact dashboard Google Ads callback URL |
| `GOOGLE_OAUTH_SECRET_MANAGER_PROJECT` | Google Cloud project ID containing token secrets |

8. Save and deploy the API.
9. Do not confuse `GOOGLE_APPLICATION_CREDENTIALS` with `GOOGLE_ADS_SERVICE_ACCOUNT_JSON`. The first authenticates the token vault; the second is an optional direct Google Ads fallback, which this customer OAuth walkthrough does not use.

Render mounts secret files at `/etc/secrets/FILENAME`. Keep them out of Docker COPY instructions and Git. The existing backend Dockerfile copies only named project paths, not the repository root wholesale. [Render secret files](https://render.com/docs/configure-environment-variables)

## 12. Deploy the worker

1. Open Render's workspace overview.
2. Click **New + → Background Worker**.
3. Connect the same GitHub repository.
4. Fill these fields:

| Field | Value |
| --- | --- |
| Name | `recovery-worker` |
| Branch | Same branch/commit as API |
| Runtime | `Docker` |
| Root Directory | Empty |
| Dockerfile Path | `deploy/Dockerfile.backend` |
| Docker Build Context, if shown | `.` |
| Docker Command | `recovery-worker` |
| Region | Same as API |
| Instances | Start with one |
| Auto-Deploy | Disabled initially |

5. Add these variables:

| Key | Value |
| --- | --- |
| `RECOVERY_WORKER_DATABASE_URL` | Dedicated worker DSN |
| `RECOVERY_ENVIRONMENT` | `staging` |
| `RECOVERY_RELEASE_ID` | Same full commit SHA as API |
| `GEMINI_API_KEY` | Real server-side Gemini API key for your project |
| `GOOGLE_ADS_OAUTH_CLIENT_ID` | Same OAuth client as API |
| `GOOGLE_ADS_OAUTH_CLIENT_SECRET` | Same OAuth client secret |
| `GOOGLE_ADS_OAUTH_REDIRECT_URI` | Same Google Ads callback URL |
| `GOOGLE_OAUTH_SECRET_MANAGER_PROJECT` | Same token-vault project ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/gcp-worker.json` |

6. Obtain the Gemini key through your authorized Google AI project/key console. Keep it server-side. The worker constructs a lazy semantic transport at startup; the credential is needed when AI calls run and by the full readiness check.
7. Leave `RECOVERY_WORKER_ID` unset initially; the CLI generates a process-specific ID. A single fixed ID reused across replicas is not necessary.
8. Add Secret File `gcp-worker.json` containing the worker service account JSON. If the creation screen does not expose Secret Files, add it immediately on the created service's Environment page and redeploy; the first startup can fail until credentials exist.
9. Click **Create/Deploy Background Worker**.
10. Open its logs and confirm it stays running without a repeating traceback.
11. Do not use `recovery-worker --once` as the Render start command; it exits after one attempt.
12. Do not leave Docker Command empty: the image's default starts the API, not the worker.
13. A quiet idle worker can be normal. Prove it processes a job in section 16.

The worker's optional health server is not a public Render Web Service. Do not wait for an `onrender.com` worker URL or create a public HTTP endpoint just to make it appear live.

**Checkpoint:** API, dashboard and worker are running; API and worker share the same release ID.

## 13. Configure legal links and optional report delivery

Workspace creation requires current Terms and Privacy identities even when you are doing a controlled pilot.

1. Publish your actual Terms and Privacy pages at HTTPS URLs you control.
2. Publish the data-deletion instructions for the production service.
3. Verify those pages open without signing in.
4. The frontend includes `/terms` and `/privacy` availability pages. They read the authoritative policy URLs and versions from the API's `/v1/launch/status` response and link to those documents. They are not legal documents themselves: do not set `RECOVERY_TERMS_URL` or `RECOVERY_PRIVACY_URL` back to these bridge pages.
5. On the API add:

| Key | Value |
| --- | --- |
| `RECOVERY_TERMS_URL` | Real published Terms URL |
| `RECOVERY_TERMS_VERSION` | Your reviewed version identifier, such as a publication date |
| `RECOVERY_PRIVACY_URL` | Real published Privacy URL |
| `RECOVERY_PRIVACY_VERSION` | Matching reviewed policy version identifier |
| `RECOVERY_DATA_DELETION_URL` | Published deletion instructions |
| `RECOVERY_SUPPORT_EMAIL` | Monitored support mailbox |
| `RECOVERY_STATUS_URL` | Optional real HTTPS status page |

6. Save and deploy. Open the frontend's `/terms` and `/privacy` pages, then follow each document link and confirm the intended published policy and version. If a page says the document is unavailable, check the API settings and the frontend's `RECOVERY_API_BASE_URL`.
7. If scheduled-report email is part of your rollout, configure these worker-only settings using your SMTP provider's values:

```text
REPORT_SMTP_HOST
REPORT_SMTP_PORT
REPORT_SMTP_TLS_MODE
REPORT_SMTP_FROM
REPORT_SMTP_USERNAME
REPORT_SMTP_PASSWORD
```

8. For example, port `587` with TLS mode `starttls` is a common combination; use the combination supported by your provider.
9. Send a controlled report delivery test and check recipient delivery and job status. Supabase authentication SMTP and worker report SMTP are separate configurations.

## 14. Add Razorpay test billing

You can leave billing disabled for the first infrastructure check. Complete this section before claiming billing acceptance.

1. Open the Razorpay Dashboard and sign in to the merchant account.
2. Switch to **Test Mode**.
3. Open the API Keys area in account settings.
4. Generate or retrieve the test key ID and secret. Store them privately.
5. Open **Subscriptions → Plans**, if enabled for your account.
6. Create the intended recurring plan using your chosen currency, amount and interval.
7. Copy its `plan_...` ID.
8. If Subscriptions is unavailable, complete the merchant/product activation process before continuing.
9. Open the dashboard's **Webhooks** settings and add an endpoint.
10. Endpoint URL:

```text
https://YOUR-API-HOST/v1/billing/webhooks/razorpay
```

11. Generate a webhook signing secret. This is separate from the API key secret.
12. Select the relevant subscription lifecycle events offered by Razorpay: activation/authentication, charged, pending, halted, paused/resumed, cancelled and completed.
13. Save the webhook.
14. In Render API Environment add:

```text
BILLING_ENABLED=true
RAZORPAY_KEY_ID=YOUR_TEST_KEY_ID
RAZORPAY_KEY_SECRET=YOUR_TEST_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET
BILLING_GRACE_HOURS=0
```

15. Add `BILLING_PLANS_JSON` as a single JSON array. Example structure only:

```json
[{"key":"starter","display_name":"Starter","provider_plan_id":"plan_REPLACE","currency":"INR","amount_subunits":499900,"total_count":12,"max_google_ads_accounts":1,"max_sync_range_days":90}]
```

16. Replace the plan ID, amount, term and product limits with your actual plan. `499900` paise means INR 4,999; it is an illustration, not a recommended price. `total_count` is a commercial billing-cycle count, not a deployment setting.
17. Save and deploy the API.
18. During onboarding, complete a test subscription.
19. Confirm the webhook is delivered successfully and the app reconciles entitlement to `full`.
20. Do not treat the browser returning from checkout as proof of successful payment. The repository checks provider state on the backend.

The application-specific endpoint and required plan fields are documented in `docs/PHASE17_SETUP.md` and implemented by its billing service. Provider dashboard labels can differ; use the current Subscriptions and Webhooks settings in your merchant account.

## 15. Bootstrap your platform administrator and enable pilot access

A customer `owner` is not automatically a `platform_admin`. The first platform administrator must be granted through the maintenance CLI.

1. Complete signup and sign in once, then visit `/onboarding` as described in section 10.
2. Open Supabase → **Authentication → Users**.
3. Select your operator email.
4. Copy the user's UUID, not their email address.
5. In the local Windows project terminal, run the following command. Replace `YOUR-USER-UUID` first:

```powershell
.\.venv\Scripts\python.exe -c "import os,getpass,sys; os.environ['RECOVERY_MIGRATION_DATABASE_URL']=getpass.getpass('Maintenance database URL: '); sys.argv=['recovery-platform-operator','YOUR-USER-UUID','platform_admin','--reason','Initial authorized platform administrator']; from recovery.internal_admin_bootstrap import main; main()"
```

6. Paste the privileged maintenance DSN at the hidden prompt.
7. Expected: `platform operator granted for ...`.
8. If it says the application user does not exist, sign in and load the backend-backed onboarding page, then retry.
9. Open `https://YOUR-DASHBOARD-HOST/internal/launch` while signed in as that user.
10. Expand **Change launch mode**.
11. Select **Pilot only** or **Invite only**.
12. Enter the exact release ID.
13. Enter a meaningful reason of at least eight characters.
14. Click **Append launch event**.
15. In the pre-public access section, grant your testing email access and enter the requested reason.
16. Return to `/onboarding` and refresh.
17. Confirm the closed-access message is replaced by the organization creation form.

Use this controlled access mode during testing. The application rejects a public transition without a fresh qualified launch report; section 20 covers that workflow.

## 16. Walk through the app and prove it works

Perform this first with a controlled Google Ads test account. Successful login alone does not prove worker or provider integration.

1. Open `/onboarding`.
2. Enter your organization/company name.
3. Enter a valid workspace slug, or leave it empty if the UI permits automatic generation.
4. Read the linked policies and select the acceptance checkbox.
5. Click **Create secure workspace**.
6. If billing is enabled, choose the configured test plan and complete the test checkout.
7. Confirm billing reconciles before moving on.
8. Click the Google Ads connect action.
9. Choose the intended Google account and complete consent.
10. Confirm the browser returns to the dashboard callback and then onboarding.
11. Wait for account discovery to finish; refresh its displayed job status if needed.
12. Select the intended Ads account. Avoid accidentally selecting an unrelated live customer account.
13. Fill out Business Truth using actual products/services, customer intent and conversion outcomes.
14. Click **Confirm Business Truth**.
15. Enter the validated conversion-lag policy in days.
16. Click **Save measurement maturity policy**.
17. Choose a modest first sync date range that is allowed by your plan.
18. Click **Queue read-only sync**.
19. Check the job moves from queued to running and then succeeds. Inspect worker logs if it remains queued.
20. Once sync completes, click **Run evidence analysis**.
21. Wait for analysis completion.
22. Click **Open Recovery OS**.
23. Confirm the dashboard shows the selected account and stored evidence.
24. An empty opportunity list is valid when evidence does not justify a finding. Do not treat it as permission to invent results.
25. Test signing out and signing back in.
26. Test with a second controlled user/tenant and verify they cannot view the first tenant's accounts or jobs.
27. If reports are in scope, generate one and check the PDF/download and optional email delivery.

Do not click apply/execute/rollback controls merely to test hosting on a real advertiser. Those actions can change Google Ads. Use the project's approved test-account mutation rehearsal and approval workflow separately.

**Checkpoint:** a real queued task was processed by the deployed worker, and a tenant-scoped dashboard can read its result.

## 17. Run readiness and deployed acceptance

### Configuration and database readiness

The CLI `recovery-production-check` checks a combined API/worker configuration. It needs both DSNs, Supabase, origins, Gemini, and any enabled provider settings. It is not an instruction to put the worker's privileged DSN permanently on the API.

1. Use a private operator environment with the installed package and the combined intended deployment settings.
2. Load secrets through your approved password manager or hidden prompts, without committing an environment file.
3. Set `RECOVERY_ENVIRONMENT=staging` for the first run.
4. Run:

```powershell
.\.venv\Scripts\recovery-production-check.exe --report staging-readiness.json
```

5. Open the JSON report.
6. Resolve every `fail`. A `ready: true` report checks configuration/database state; it does not replace external acceptance or access review.
7. `--no-database` is a configuration-only diagnostic. Do not present that as proof the real database works.

### Prepare the operator environment without writing secret values into commands

For a single temporary command, Python can prompt privately for values. This is an example for the readiness checker; enter the same real settings used in Render:

```powershell
.\.venv\Scripts\python.exe -c "import os,getpass,sys; names=['DATABASE_URL','RECOVERY_WORKER_DATABASE_URL','SUPABASE_URL','API_ALLOWED_ORIGINS','GEMINI_API_KEY']; [os.environ.__setitem__(n,getpass.getpass(n+': ')) for n in names]; os.environ['RECOVERY_ENVIRONMENT']='staging'; os.environ['BILLING_ENABLED']='false'; sys.argv=['recovery-production-check','--report','staging-readiness.json']; from recovery.deployment import main; main()"
```

This limited command tests the initial billing-disabled staging configuration. For an OAuth/billing-enabled or production report, include all corresponding real settings from sections 11, 14 and 19. Omitting a feature from the check does not validate that feature.

### Deployed acceptance

1. Record the workspace tenant UUID and Recovery account UUID from the application URL/data. The Recovery account UUID is not the ten-digit Google customer ID.
2. Obtain a current access token for your signed-in test administrator through your approved authenticated test harness/session tooling. Use the Supabase user access token, not the publishable key or service-role key.
3. Keep the token private and short-lived. Do not paste it into chat, commit it or put it directly in the command line.
4. In the operator environment set these inputs:

```text
RECOVERY_ACCEPTANCE_API_URL
RECOVERY_ACCEPTANCE_DASHBOARD_URL
RECOVERY_ACCEPTANCE_TENANT_ID
RECOVERY_ACCEPTANCE_GOOGLE_ADS_ACCOUNT_ID
RECOVERY_ACCEPTANCE_BEARER_TOKEN
RECOVERY_RELEASE_ID
```

5. Run the initial acceptance command:

```powershell
.\.venv\Scripts\recovery-staging-accept.exe --report staging-acceptance.json
```

6. For the full staging rehearsal with test billing and a Google test account, run:

```powershell
.\.venv\Scripts\recovery-staging-accept.exe --require-billing-full --require-google-ads-read --require-google-test-account --report staging-acceptance.json
```

7. Confirm API liveness/readiness, release identity, authenticated API, dashboard and worker round trip pass. The full run must also prove Google read access and billing entitlement.
8. Keep the report in private release evidence storage. Reports can contain operational identifiers even when secrets are excluded.

## 18. Add your custom domain

1. Open the Render dashboard service → **Settings → Custom Domains**.
2. Click **Add Custom Domain**.
3. Enter your actual dashboard hostname, such as `app.yourdomain.com`.
4. Render displays the required DNS record.
5. Open the account where your DNS is managed.
6. Add exactly the record Render specifies. Do not copy a CNAME target from an example project.
7. Return to Render and verify the domain.
8. Wait for DNS and HTTPS certificate provisioning.
9. Open `https://app.yourdomain.com/login` and confirm HTTPS works.
10. Optionally repeat on the API using `api.yourdomain.com`.

[Render custom domains](https://render.com/docs/custom-domains)

After the dashboard domain changes, update all of these before retesting:

| Location | Update |
| --- | --- |
| Render dashboard environment | `NEXT_PUBLIC_SITE_URL`, then rebuild |
| Render dashboard environment | `RECOVERY_API_BASE_URL` if API domain changed |
| Render API environment | `API_ALLOWED_ORIGINS` |
| Render API and worker environment | `GOOGLE_ADS_OAUTH_REDIRECT_URI` |
| Supabase Authentication | Site URL and `/api/auth/callback` allowlist |
| Google OAuth web client | Exact `/api/google-ads/oauth/callback` redirect URI |
| Razorpay | Webhook URL if API domain changed |
| Turnstile | Allowed dashboard hostname |
| Published policy settings | Real URLs if policy hosting changed |

For a staged domain cutover, temporarily allow both known dashboard origins as a comma-separated CORS list, then remove the old origin after testing. Do not use `*`.

## 19. Prepare the production configuration

Create separate production services and a production database/auth project, repeating the validated setup. Use real production credentials and the intended production domain. Keep launch closed or invite-only during validation.

### API production additions

| Variable | Required meaning |
| --- | --- |
| `RECOVERY_ENVIRONMENT` | `production` |
| `RECOVERY_RELEASE_ID` | Exact production candidate release ID, same on worker |
| `RECOVERY_BACKUP_POLICY_ACK` | `PITR_OR_DAILY_BACKUP_VERIFIED` only after verifying backup policy |
| `GOOGLE_ADS_OAUTH_VERIFICATION_ACK` | `RESTRICTED_SCOPE_VERIFIED` only after the required Google approval |
| `GOOGLE_ADS_PRODUCTION_ACCESS_ACK` | `EXPLORER_OR_HIGHER` only after verifying production API access |
| `RAZORPAY_KEY_ID` | Real `rzp_live_...` key when billing is enabled |
| `RAZORPAY_KEY_SECRET` | Matching live secret |
| `RAZORPAY_WEBHOOK_SECRET` | Live webhook signing secret |
| `BILLING_PLANS_JSON` | Live plan IDs and matching commercial terms |
| `RAZORPAY_LIVE_ACTIVATION_ACK` | `LIVE_ACCOUNT_ACTIVATED` after actual merchant activation |
| `RAZORPAY_LIVE_WEBHOOK_ACK` | `LIVE_WEBHOOK_VERIFIED` after real live delivery/reconciliation verification |
| Terms/Privacy/Deletion/Support settings | Actual reviewed and published production values |

These acknowledgement strings are application gates, not actions that activate provider accounts. Do not set them as a shortcut around unfinished work. The worker also uses production database/provider values; the frontend uses the production Supabase URL/publishable key and production API URL.

### Configure Turnstile for public workspace creation

1. Open the Cloudflare dashboard.
2. Open **Turnstile** and choose **Add widget**.
3. Name it for this production application.
4. Add the exact production dashboard hostname, without `https://` or a path.
5. Select the intended widget mode and create it.
6. Store the returned site key and secret key.
7. In the Render API add all four settings:

```text
RECOVERY_TURNSTILE_SITE_KEY=YOUR_REAL_SITE_KEY
RECOVERY_TURNSTILE_SECRET=YOUR_REAL_SECRET_KEY
RECOVERY_TURNSTILE_HOSTNAMES=app.yourdomain.com
RECOVERY_PUBLIC_WORKSPACE_MAX_PER_USER_24H=1
```

8. Save and deploy.
9. Test the challenge and server-side workspace creation rejection/acceptance before public release. Do not use testing keys in production.
10. The app supplies the public site key through its launch-status response; do not invent a new `NEXT_PUBLIC_TURNSTILE_...` variable.

[Cloudflare widget setup](https://developers.cloudflare.com/turnstile/get-started/widget-management/dashboard/)

### Preserve the exact backend artifact

The repository's existing release contract uses one immutable backend image for API and worker. Separate Git-based Render builds from one commit share source identity but are not proof of identical image bytes, particularly because base images and transitive dependencies can change.

For the strongest production release identity, have your release pipeline build `deploy/Dockerfile.backend` once, push it to a private container registry, record its SHA-256 image digest, and create the production API and worker from that same `registry/repository@sha256:...` image. Keep API Docker Command empty and override the worker with `recovery-worker`. Configure the registry credentials in Render. Use the same environment settings and health checks from this guide.

For an operator-managed build using Docker Hub:

1. Install/open Docker Desktop with Linux containers enabled and wait for its engine to start.
2. Sign into Docker Hub, create a private repository named `recovery-backend`, and record your namespace.
3. In the project terminal, verify you are on the reviewed commit with no unreviewed tracked changes.
4. Authenticate Docker using its interactive login; do not include a password/token in the command text:

```powershell
docker login
```

5. Replace `YOUR-NAMESPACE` and `YOUR-RELEASE-ID`, then build and push once:

```powershell
docker buildx build --platform linux/amd64 -f deploy/Dockerfile.backend -t docker.io/YOUR-NAMESPACE/recovery-backend:YOUR-RELEASE-ID --push .
docker buildx imagetools inspect docker.io/YOUR-NAMESPACE/recovery-backend:YOUR-RELEASE-ID
```

6. Copy the reported top-level digest. Record the complete reference `docker.io/YOUR-NAMESPACE/recovery-backend@sha256:ACTUAL_DIGEST` in private release notes.
7. Create a read-only registry token for Render; keep the publishing credential separate.
8. In Render, choose **New → Web Service → Existing Image**.
9. Enter the recorded digest reference, add the registry pull credential, and connect.
10. Apply section 8's API environment/health settings. A prebuilt image does not need a Git root or Dockerfile field.
11. Create **New → Background Worker → Existing Image** using the identical digest.
12. Apply section 12's settings and override Docker Command with `recovery-worker`.
13. Keep that image available in the registry for restarts and rollback. Do not delete the previous approved release image.

Render requires `linux/amd64` images and accepts digest references for prebuilt services. [Render prebuilt image deployment](https://render.com/docs/deploying-an-image)

If you retain Git-based builds, record that limitation and do not claim the existing single-immutable-image release contract was fully reproduced. Both approaches still require the exact matching `RECOVERY_RELEASE_ID` and deployed acceptance.

### Backups and operational checks

1. Enable your selected Supabase backup/PITR capability.
2. Check its retention and the actual available restore points.
3. Perform a restore drill into an isolated database and verify the restored application data.
4. Monitor API errors/readiness, worker failures and queue age, provider errors and database capacity.
5. Test alert delivery to the real on-call recipient.
6. Perform access review, incident and rollback rehearsals.
7. Keep evidence of the actual results for section 20. A configured backup is not evidence of a successful restore drill.

## 20. Complete the application's pilot and public launch gates

The app includes its own release evidence gates. Render's green status does not override them.

### Pilot qualification

1. Complete the full staging acceptance in section 17.
2. Prepare private evidence JSON files for these eight pilot items:

```text
backup_configuration
restore_drill
access_review
security_review
observability_alerts
incident_response_drill
reconciliation_rollback_drill
pilot_tenant_setup
```

3. Use the example files under `deploy/pilot-evidence` as structural references. Keep `pending` for work not actually completed.
4. Run, using your real paths and release ID:

```powershell
.\.venv\Scripts\recovery-pilot-gate.exe --readiness-report staging-readiness.json --acceptance-report staging-acceptance.json --evidence-dir PRIVATE-PILOT-EVIDENCE-DIRECTORY --expected-release-id YOUR-RELEASE-ID --report pilot-gate-report.json
```

5. Resolve failures. The expected result is `qualified: true` based on actual evidence, not hand-edited statuses.

### Production qualification

1. Run the readiness checker with the full production configuration and save `production-readiness.json`.
2. Run production acceptance against the production URLs, a controlled production tenant, and a real non-test advertiser authorized for the read-only probe:

```powershell
.\.venv\Scripts\recovery-staging-accept.exe --require-billing-full --require-google-ads-read --require-google-production-account --report production-acceptance.json
```

The command retains its historical `staging` name, but these flags and environment inputs select production acceptance. The Google probe is read-only. Do not leave `--require-google-test-account` on this production command.

3. Prepare production evidence files for all required items:

```text
google_ads_production_access
google_oauth_verification
razorpay_live_activation
razorpay_live_webhook
production_domain_tls
legal_privacy_publication
data_deletion_process
support_oncall
production_observability
production_security_access_review
production_backup_restore
release_rollback_rehearsal
public_signup_abuse_controls
```

4. Each file is named `ITEM_NAME.json`. The schema has this structure; replace every value with real evidence:

```json
{
  "schema_version": "recovery-launch-evidence.v1",
  "kind": "production_domain_tls",
  "status": "pending",
  "performed_at": "REPLACE_WITH_ACTUAL_ISO_8601_TIME_WITH_TIMEZONE",
  "detail": "Describe the actual verification and outcome",
  "operator": "Responsible operator identity",
  "evidence_refs": ["Private reference to the actual evidence"],
  "release_id": "YOUR-RELEASE-ID"
}
```

5. Change `pending` to `pass` only when the named verification was performed and passed.
6. Run:

```powershell
.\.venv\Scripts\recovery-launch-gate.exe --pilot-gate-report pilot-gate-report.json --readiness-report production-readiness.json --acceptance-report production-acceptance.json --evidence-dir PRIVATE-LAUNCH-EVIDENCE-DIRECTORY --expected-release-id YOUR-RELEASE-ID --report launch-gate-report.json
```

7. Confirm the report is qualified. Current code requires deployed reports no older than 24 hours and a matching pilot qualification no older than seven days; individual evidence items also have freshness limits.
8. Sign into the dashboard as `platform_admin`.
9. Open `/internal/launch`.
10. Expand **Import qualified launch report**.
11. Paste the generated report JSON into the report field and submit.
12. Confirm import succeeds for the exact release.
13. Complete your final controlled canary signup/onboarding.
14. Expand **Change launch mode**.
15. Choose **Public**.
16. Enter the qualified release ID and an operator reason.
17. Click **Append launch event**.
18. Verify new public workspace creation and Turnstile protection using a separate controlled account.

See also the repository's `docs/V1_LAUNCH_RUNBOOK.md`. If a gate fails, keep launch restricted and resolve its listed failure rather than bypassing the gate.

## 21. Deploy future updates

1. Test the change locally and in staging.
2. Commit and push the reviewed code.
3. Record the new commit/release ID.
4. Check whether the change contains new SQL migrations.
5. Back up and verify recovery options before a schema change.
6. Review compatibility: if old API/worker code cannot run against the new schema, use a coordinated maintenance window.
7. Run migrations once through the maintenance path against the correct database. Do not run them independently on both API and worker startup.
8. Reapply/audit grants for newly created database objects.
9. Update `RECOVERY_RELEASE_ID` on API and worker to the same new value.
10. Deploy the matching backend artifacts. With Git services, use **Manual Deploy** and select the intended commit where available; do not accidentally deploy a newer branch head on one service.
11. Deploy the matching dashboard version.
12. Confirm `/readyz` and authenticated dashboard operation.
13. Repeat worker round-trip/provider acceptance appropriate to the change.
14. Requalify launch evidence when the exact release requirement demands it.

Render supports manual deployment, pre-deploy steps and rollback operations. This guide deliberately uses a separate migration operator so runtime services do not need migration-owner credentials. [Render deployment lifecycle](https://render.com/docs/deploys)

### Roll back an application release

1. If new customer onboarding must stop, set launch mode to **Closed** in `/internal/launch`.
2. If consequential provider actions are unsafe, use the separate tenant feature controls to stop them as described by the application's incident runbook.
3. Inspect whether the previous application image supports the current database schema.
4. If compatible, use Render's service Events/deployment history to roll API, worker and dashboard back to the matching previous release.
5. Restore the matching release configuration and verify both services agree on release identity.
6. Check `/readyz`, sign-in and a worker round trip.
7. If the schema is incompatible, follow the tested database recovery/forward-fix plan. A Render rollback does not undo SQL migrations.
8. Do not blindly replay ambiguous Google mutation jobs; the application's reconciliation path exists for that case.

## 22. Troubleshooting by symptom

| Symptom | Exact first checks and next action |
| --- | --- |
| Repository missing in Render | Open GitHub Render app permissions, allow this repository, refresh Render |
| Docker build cannot find `src` or `pyproject.toml` | API/worker Root Directory must be empty; context `.`; Dockerfile `deploy/Dockerfile.backend` |
| Python/Node package version not found | Read the first package/version error; verify registry availability; fix the release pins deliberately before redeploying |
| `npm ci` says lockfile missing or out of date | Confirm `web/package-lock.json` is pushed on the selected commit and Root Directory is `web`; resolve a package/lock mismatch locally, commit both and redeploy |
| Next build lacks Supabase settings | Add both public Supabase variables before build, then rebuild |
| Render reports no open port for API | Restore Dockerfile API command; it must bind `0.0.0.0` and `$PORT` |
| Dashboard port error | Use `npm run start -- --hostname 0.0.0.0 --port $PORT` with root `web` |
| API `/` returns 404 | Test `/healthz` and `/readyz`; the backend root is not the customer UI |
| Frontend `/` shows a landing page instead of the dashboard | Expected: use `/app` for the signed-in product |
| Booking, support or status link is unavailable | Add the real optional setting to `recovery-web` Environment as described in section 9, then deploy |
| `/terms` or `/privacy` says the document is unavailable | Publish real policy documents, set their URLs and versions on the API, and check frontend `RECOVERY_API_BASE_URL`; do not point legal URLs back to the bridge pages |
| `/readyz` returns 503 | Check network reachability, correct role DSN, grants and all migration checksums |
| Database host unreachable | Check IPv6 vs IPv4; use the project's session pooler when appropriate |
| Database authentication failed | Verify role password, pooler username/project suffix and URI password encoding |
| Permission denied for schema/table | Confirm role grants after migrations; do not replace API role with owner credentials |
| Login succeeds but backend returns 401 | Confirm API and frontend use the same Supabase project and current ES256/RS256 user tokens |
| Confirmation returns to localhost | Fix Supabase Site URL/redirect allowlist and rebuild dashboard with correct site URL |
| Signup email never arrives | Check spam, Supabase auth logs, SMTP sender/domain and provider rate limits |
| Workspace creation is closed | Bootstrap platform operator, choose pilot/invite mode and grant the tester's email |
| Legal acceptance not ready | Configure actual Terms/Privacy URLs and version IDs on API |
| Google `redirect_uri_mismatch` | Compare callback URL character-for-character in Google Console and both backend services |
| Google test user cannot authorize | Check OAuth audience/testing user list and selected Google account |
| `DefaultCredentialsError` | Verify the correct secret file exists and `GOOGLE_APPLICATION_CREDENTIALS` points to it |
| Secret Manager permission denied | Check service identity, project ID, API enablement and exact IAM operations |
| Account discovery/sync stays queued | Check worker is running with `recovery-worker`, worker DSN is correct and cross-tenant access works |
| Worker repeatedly exits | Inspect the first traceback; check Gemini key, OAuth completeness, secret file and DB connection |
| API works but dashboard cannot fetch it | Correct `RECOVERY_API_BASE_URL`; localhost refers to the frontend container, not your API |
| Billing startup fails | All key/secret/plan settings are required when billing is enabled |
| Webhook returns 401 | Check the webhook signing secret, live/test mode and exact endpoint |
| Checkout returns but access remains limited | Inspect webhook delivery and server reconciliation; a browser callback is not entitlement proof |
| PDF generation fails | Ensure worker uses the backend Dockerfile with Pango/fonts; inspect worker report error |
| Turnstile fails | Match hostname, site/secret pair and environment; all three Turnstile settings must be complete |
| Release identity mismatch | Deploy the intended commit/artifact and set the same release ID on both API and worker |
| Public transition is rejected | Import fresh qualified launch evidence for the exact release; inspect the returned gate error |

### How to inspect Render logs

1. Open the affected service, not a different service with a similar name.
2. Open **Events** for build/deploy failures.
3. Select the failed deployment and inspect the first relevant error.
4. Open **Logs** for runtime failures.
5. Note the time, operation and sanitized error text.
6. Correct the setting or code and redeploy.
7. Repeat the exact failed checkpoint.
8. Do not share unredacted DSNs, private keys, access tokens or webhook secrets when requesting help.

For an interactive service shell, paid compatible services expose **Shell** after a successful deploy. Use it for diagnosis without assuming local files written there survive redeployment. [Render shell access](https://render.com/docs/ssh)

## 23. Final operator checklist

- [ ] GitHub contains the reviewed release and no credentials.
- [ ] API and worker build from the root Dockerfile path; frontend root is `web`.
- [ ] All required migrations for this release are applied.
- [ ] API runtime role is not a superuser and does not bypass RLS.
- [ ] Worker has its separate cross-tenant database credential.
- [ ] API `/healthz` and `/readyz` pass.
- [ ] Public homepage, supporting pages and the nine-step synthetic tour work on desktop and mobile.
- [ ] Public connection and review actions lead to the intended signup/onboarding and configured contact destinations.
- [ ] Dashboard login and email confirmation work on the actual HTTPS domain.
- [ ] API and worker have matching release IDs; image identity limitations are recorded or resolved.
- [ ] Google OAuth, token storage and account discovery work.
- [ ] A read-only sync and analysis complete through the deployed worker.
- [ ] Tenant access isolation has been tested.
- [ ] Billing test/live modes and webhook secrets match their environments.
- [ ] Real Terms, Privacy, deletion and support settings are published; the frontend legal pages link to the authoritative documents.
- [ ] Backup restore, monitoring and incident/rollback procedures have been exercised.
- [ ] Production Turnstile verification works before public signup is enabled.
- [ ] Readiness, acceptance, pilot and public-launch gates pass where required.
- [ ] Public launch was enabled deliberately by a platform administrator for the qualified release.

Keep this worksheet, the actual provider configuration and the release reports together in private operator storage. A later domain, credential, database, or release change must update the corresponding connected settings and be reverified.
