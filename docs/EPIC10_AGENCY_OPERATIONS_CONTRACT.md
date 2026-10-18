# Epic 10 — Organization / Agency Operations Contract

Version: 0.29.1

## Canonical surfaces

- `/app/organization`
- `/app/organization/team`
- `/app/organization/clients`
- `/app/organization/access`
- `/app/organization/activity`
- `/accept-invite/:token`

## Authorization invariants

1. Tenant membership is required before all tenant operations except accepting a valid invitation.
2. Owner/Admin are organization-wide operators and always use `all_accounts`.
3. Analyst/Viewer may use `selected_accounts`.
4. Client-facing access is `viewer + selected_accounts` only.
5. Restricted members may access only accounts in their projected accessible-account set.
6. Restricted members cannot enumerate internal portfolios or use organization/portfolio-wide evidence surfaces.
7. Account responsibility assignments never grant account visibility.
8. Backend/FastAPI authorization is authoritative; frontend navigation is not a security boundary.

## Access sources

A selected-account member may receive account access through:

- latest direct account-access event = grant; or
- active client-workspace membership + active workspace + linked account.

The access matrix must explain the source rather than returning only a boolean.

## Client workspaces

A client workspace is a Recovery OS access boundary for one client or customer group. It is distinct from:

- internal portfolios,
- Google Ads manager/sub-manager hierarchy,
- operational responsibilities.

Archiving a client workspace removes its transitive access contribution without deleting its event history.

## Invitations

Invitation token format includes the tenant identifier and a random secret. Only its SHA-256 is persisted. Acceptance requires:

- pending, unexpired invite,
- exact authenticated email match,
- token digest match,
- single-use transition,
- membership projection update and audit event in the same transaction.

## Ownership continuity

The organization must always retain at least one active Owner. An Admin cannot alter Owner access. This is enforced server-side.

## Information-leak controls

Restricted users must not infer unrelated clients through:

- account lists,
- command-center counts/money,
- portfolios,
- tasks,
- global search,
- Search/Waste/Measurement/Action/Recovery surfaces,
- Monitoring,
- Reporting.

Organization-wide evidence routes require unrestricted scope or explicit permitted account scope where supported.

## Provider boundary

Recovery OS access does not grant Google Ads access. Epic 10 does not call Google Ads user-access mutation services.

## Acceptance gate

Epic 10 requires:

- Python compilation,
- complete cumulative regression suite,
- Epic-10 API/domain/migration/frontend tests,
- frontend product contract,
- TypeScript parser validation,
- secret-sensitive scan,
- clean ZIP creation,
- exact-ZIP extraction and rerun of the same gates.

## Resumed hardening — ownership and invitation concurrency

The resumed Epic-10 release closes the transaction races that existed in the interrupted build:

- every membership-admin transition takes a tenant-scoped transaction advisory lock;
- the target membership row is selected `FOR UPDATE` before role/status changes;
- PostgreSQL independently enforces that an organization cannot lose its last active Owner, using the same tenant-scoped advisory lock to prevent write-skew across concurrent Owner demotions/disables;
- invitation creation is serialized per tenant + normalized email;
- invitation acceptance is serialized per token digest before the single-use state is evaluated;
- Owner invitations may be created or revoked only by an Owner;
- Admin UI does not expose Owner mutation controls even though backend authorization remains authoritative.

These controls follow deny-by-default / least-privilege principles and preserve immutable administrative audit events. They do not change Google Ads provider access.
