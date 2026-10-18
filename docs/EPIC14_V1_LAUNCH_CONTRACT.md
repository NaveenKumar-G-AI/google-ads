# Epic 14 — V1 Launch Contract

Version: 0.33.0

## Core rule

Recovery OS can contain all V1 launch machinery while public launch remains closed. `public` is an append-only platform state transition, not a build-time boolean and not a frontend flag.

A public transition requires a fresh, imported, qualified `recovery-launch-gate.v1` report for the **exact release ID** being exposed. Closing launch later appends another event; it does not delete tenants or revoke existing customers.

## Launch modes

- `closed` — no new workspace creation.
- `pilot_only` — only users with a current hashed email access grant may create a workspace.
- `invite_only` — same fail-closed access-grant boundary for a controlled pre-public rollout.
- `public` — authenticated users may create workspaces, but only when current server-authoritative Terms and Privacy identities are configured and explicitly accepted.

Launch mode controls creation of new customer workspaces only. Google Ads mutations, billing provider writes and scheduled report email retain their separate operational kill switches.

## Qualification chain

The V1 launch gate requires all of the following to pass:

1. recent Epic-13 pilot qualification for the exact V1 release;
2. fresh production readiness report;
3. fresh deployed production acceptance for the exact release;
4. production Google Ads read-only evidence from a non-test advertiser;
5. Google Ads production API access evidence;
6. restricted Google OAuth verification evidence;
7. Razorpay live-account and live-webhook evidence;
8. production TLS/domain evidence;
9. published Terms/Privacy evidence;
10. data-deletion process evidence;
11. support/on-call evidence;
12. production observability evidence;
13. privileged-access/security review;
14. backup + real restore evidence;
15. rollback rehearsal evidence;
16. public-signup abuse-control evidence.

The final launch report itself must be no more than 24 hours old when imported and when a `public` launch event is written.

## Legal acceptance boundary

The backend is the sole authority for the active:

- Terms URL;
- Terms version;
- Privacy URL;
- Privacy version.

The authenticated launch-status API returns these exact identities to onboarding. The browser does not maintain a duplicate `NEXT_PUBLIC_*` version authority.

Workspace creation requires:

- an explicit `legal_acceptance_confirmed=true` request field;
- the submitted Terms version to exactly equal the backend-required Terms version;
- the submitted Privacy version to exactly equal the backend-required Privacy version.

The database records an append-only `user_legal_acceptance_events` row in the **same transaction** that creates the organization, storing the exact HTTPS policy URLs, versions, user, tenant and server acceptance time. Therefore no customer workspace can commit successfully while its required acceptance evidence fails to commit.

Idempotent replay of the original successful workspace-creation request returns the existing tenant and does not create duplicate acceptance evidence.

## Pre-public access grants

Pilot/invite access stores:

- SHA-256 of normalized email;
- masked email hint;
- grant/revoke event;
- optional expiry;
- platform-admin actor and reason.

The raw email is not stored in launch-access history. Grant state is derived from the latest append-only event and expiry.

## Platform authority

Only `platform_admin` can:

- import a qualified launch report;
- change launch mode;
- grant/revoke pre-public workspace access.

Customer Owner/Admin membership never inherits platform launch authority.

## Database defense in depth

Migration `0022_epic14_v1_launch.sql` validates imported qualification rows as well as public launch events. A stored qualification must have:

- schema `recovery-launch-gate.v1`;
- `qualified=true`;
- exact stored/report release match;
- at least one check;
- every check in `pass` state;
- matching `generated_at` / `report_generated_at`.

The public-launch trigger independently checks exact release, qualification state and 24-hour freshness.

All launch-control and legal-acceptance history is append-only.

## What code completion does not mean

A green Epic-14 package does **not** mean Recovery OS is publicly launched. Actual `public` mode must remain blocked until the external V1 launch gate genuinely passes against production systems and an authorized platform administrator deliberately promotes the exact release.
