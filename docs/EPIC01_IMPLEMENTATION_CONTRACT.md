# Epic 1 — Product Shell Implementation Contract

Version: 0.20.0

Epic 1 replaces the old six-page dashboard as the primary product entry point. The old `/dashboard/*` routes remain temporarily for backward compatibility and for mature backend workflows that later epics will redesign.

## Implemented in Epic 1

- `/app` is the canonical authenticated product entry.
- Organization → portfolio → account context switching.
- Mature grouped navigation that can host the canonical product domains without another shell rewrite.
- Currency-safe Command Center; monetary amounts are aggregated only inside a currency bucket.
- Account inventory and account workspace shell.
- First-class portfolios and account membership in PostgreSQL.
- Operational task queue with assignment-ready schema, priorities, due dates and lifecycle states.
- User-scoped notifications with read/unread lifecycle.
- Authorized global search across accounts, portfolios and tasks.
- Persistent data-freshness/status vocabulary.
- Canonical separation of observed candidate spend and verified recovery in the new shell.
- Responsive desktop/tablet/mobile shell foundation.
- RLS for all new shell entities.
- Backend authorization for portfolio/task/notification/search APIs; UI visibility is not the security boundary.

## Intentionally not claimed complete in Epic 1

- Deep Search Intelligence
- Waste Intelligence
- Measurement Integrity
- Recovery Case product
- Mature Action Center redesign
- Monitoring/alert generation engine
- Reporting engine
- Automation Studio
- CRM revenue intelligence
- Complete agency workflows
- Complete billing lifecycle redesign
- Internal support/admin console

These are separate canonical epics. Disabled navigation labels are structural placeholders only and are not counted as implemented product features.

## Financial language contract

The new shell must never merge:
1. potentially avoidable observed spend,
2. projected prevented spend,
3. post-action observed impact,
4. verified recovery.

Cross-account monetary aggregation is allowed only per currency. The UI must not sum USD + INR + other currencies into one headline.

## Product-state contract

The shell recognizes data-health states such as current, delayed, stale and unavailable. A stale or unavailable account must not visually appear equivalent to a freshly synchronized account.

## Security contract

- Browser never accesses the Recovery PostgreSQL service role.
- Supabase JWT remains server-verified before FastAPI access.
- RLS applies to portfolios/tasks; notifications are tenant + user scoped.
- Portfolio management requires admin/owner permissions.
- Analysts may manage operational tasks but cannot gain portfolio administration rights through the UI.

## Acceptance gate

Epic 1 is accepted only when:
- all legacy regression tests pass,
- Epic-1 migration/API/frontend contract tests pass,
- `node web/scripts/validate.mjs` passes,
- Python compiles cleanly,
- exact packaged ZIP re-extracts and passes the same tests,
- no server credential is present in frontend source or packaged runtime files.
