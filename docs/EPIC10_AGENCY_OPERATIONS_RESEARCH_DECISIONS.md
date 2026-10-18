# Epic 10 — Organization / Agency Operations Research Decisions

Version: 0.29.1

## Product boundary

Epic 10 manages **Recovery OS access**, not Google Ads provider user access.

Google Ads has its own user-access model and manager-account hierarchy. Current provider roles include ADMIN, STANDARD, READ_ONLY and EMAIL_ONLY. Google Ads API user-access changes require ADMIN access and sensitive changes such as invitations, role changes and removals may require multi-party approval by another Google Ads administrator. Recovery OS therefore does not treat an internal Recovery OS invitation or account grant as permission inside Google Ads.

Provider access management remains a future, separately governed integration.

## Manager hierarchy

Google Ads manager accounts may contain advertiser accounts and sub-manager accounts. Recovery OS keeps its own organization/client-workspace model separate from that provider hierarchy. A Recovery OS client workspace is a product access boundary, not a Google manager-account relationship.

## Mature-agency benchmark

Mature PPC products support team users, account access, portfolios, ownership and repeatable workflows. Epic 10 implements the access/ownership foundation. Repeatable workflow blueprints remain later scope.

## Access model

Organization membership has two account scopes:

- `all_accounts`
- `selected_accounts`

Owner/Admin memberships must be `all_accounts`. Selected-account access may come from direct grants or active client-workspace membership. Responsibility assignment does not grant access.

## Client-facing access

`client_portal=true` is valid only for `viewer + selected_accounts`.

This prevents a client-facing identity from accidentally receiving organization-wide operational rights.

## Invitation security

Recovery OS invitation links are capability tokens:

- generated with high entropy,
- exact email binding,
- single-use,
- 1–30 day expiry,
- raw token disclosed only at creation,
- database stores SHA-256 only,
- accepted/revoked/expired state is event sourced.

V1 does not automatically email invitation links. The authorized operator copies the one-time link to the intended recipient using an appropriate secure channel.

## Ownership safety

- Admin cannot manage Owner access.
- Only an Owner can invite/promote/manage another Owner.
- The last active Owner cannot be disabled or demoted.
- Owner/Admin access cannot be narrowed to selected accounts.

## Audit model

The membership row remains the fast authorization projection. Administrative changes are also recorded as immutable events for roles, access mode, invitations, direct grants, client workspaces, account assignments and organization activity.

## Deferred

Not included in Epic 10:

- Google Ads `CustomerUserAccess` mutations,
- Google Ads user invitations,
- Google Ads multi-party approval orchestration,
- SSO/SAML/SCIM,
- custom enterprise roles,
- workflow blueprints/SOP automation,
- automatic invitation-email delivery.

## Resumed concurrency decision

Application-level `count(active owners)` checks are not sufficient by themselves: two concurrent Owner-removal transactions can both observe the other Owner and commit a zero-Owner state. The resumed build serializes tenant membership-administration transactions with a PostgreSQL transaction advisory lock and duplicates the last-Owner invariant in a database trigger. This is deliberately defense-in-depth rather than relying on frontend controls or one API code path.

Invitation create/accept/revoke paths are similarly serialized at their logical identity boundary so duplicate active invites and double acceptance cannot be produced by concurrent requests through the normal API path.
