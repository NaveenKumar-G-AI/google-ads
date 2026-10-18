# Launch Execution Qualification Contract

Version: 0.34.0

This milestone follows the V1 feature/launch-control sequence. It does not add another product feature epic. Its purpose is to make the remaining public-launch evidence executable and fail-closed.

## Public workspace abuse boundary

`public` launch mode now requires two independent controls:

1. Cloudflare Turnstile completed in the browser **and validated on the Recovery OS backend** through Siteverify;
2. a PostgreSQL-serialized per-user successful workspace-creation limit over a rolling 24-hour window.

The backend validates `success`, the exact `workspace-create` action, an explicit allowed hostname, and the challenge timestamp. Raw Turnstile tokens and the secret key are never stored in Recovery OS evidence tables.

Invite/pilot launch modes retain their separate hashed-email grant boundary and do not require a public Turnstile challenge. If launch mode changes to `public` between pre-check and commit, the transaction independently requires verified challenge evidence and fails closed.

## Idempotency

A successful organization request remains replayable through the existing workspace idempotency record. Siteverify receives a deterministic UUID idempotency key for safe validation retries. A public workspace request cannot bypass the database rate boundary by using multiple concurrent request keys because a separate user-level advisory transaction lock serializes the count check.

## Evidence

Migration `0023_launch_execution_signup_abuse.sql` stores only successful server-verification metadata tied to the exact workspace-creation request hash:

- user / tenant;
- request SHA-256;
- provider = `cloudflare_turnstile`;
- hostname;
- action;
- optional challenge timestamp;
- server occurrence time.

The history is append-only and FORCE-RLS protected. The token and secret never enter this table.

## Machine public-surface evidence

`recovery-launch-public-surface` makes three V1 launch evidence files from the deployed release:

- `production_domain_tls.json`
- `legal_privacy_publication.json`
- `public_signup_abuse_controls.json`

It requires HTTPS, validates the deployed `/buildz` release identity, reads `/v1/launch/status`, fetches the published Terms/Privacy/Data Deletion pages using normal certificate validation, and confirms that the deployed API reports a Turnstile site key plus an explicit 1–20 per-user 24-hour limit.

It never reads or prints the Turnstile secret.

## What this still does not prove

Machine public-surface evidence does not prove Google production access, OAuth verification, Razorpay live activation/webhook behavior, restore drills, incident/on-call exercises, or rollback rehearsals. Those remain independent external launch-gate inputs.
