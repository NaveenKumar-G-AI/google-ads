# Recovery OS — Epic 1 Specification
## Product Shell, Design System & Canonical Information Architecture

**Status:** Implementation-ready specification  
**Depends on:** Canonical Product Specification v1.0  
**Purpose:** Create the mature application shell every future domain will inherit. This epic replaces the current prototype dashboard structure.

---

# 1. Epic outcome

Epic 1 is complete only when a user can enter Recovery OS and immediately understand:

- which organization/workspace/account they are operating in,
- what needs attention,
- what data is fresh/stale,
- what permissions they have,
- where each major product domain lives,
- how to switch account/portfolio context,
- how to find work,
- how to recover from degraded/error states,
- how to navigate a dense PPC product without losing context.

This epic does **not** implement full Search Intelligence, Waste Intelligence, Recovery Center, or Reporting logic. It builds the product shell and reusable interaction system those modules need.

---

# 2. Benchmark-derived requirements

Mature PPC products demonstrate several expectations that Recovery OS must meet from the beginning:

1. **Multi-account / portfolio context**
   - Users managing many ad accounts need account and portfolio views, not a single-account dashboard.

2. **Actionable account dashboards**
   - Account views combine metrics, alerts, optimization/recovery opportunities, tasks, budgets, and health.

3. **Reusable workflows / tasks**
   - Mature agency tooling standardizes recurring work and ownership across accounts.

4. **In-context operations**
   - Users should be able to inspect and act without repeatedly losing the current account context.

5. **User/account access continuity**
   - Organizations need user roles and account-level access that survive staff changes.

6. **Customizable views**
   - Dense operational SaaS needs saved filters, column control, account search, and configurable views.

Recovery OS must match these expectations while differentiating around recovery, measurement confidence, and business outcome quality.

---

# 3. Canonical application hierarchy

```
Recovery OS
│
├── Organization
│   ├── Portfolio(s)
│   │   └── Account(s)
│   └── Standalone Account(s)
│
├── Work
│   ├── Alerts
│   ├── Tasks
│   ├── Action approvals
│   └── Recovery cases
│
├── Intelligence
│   ├── Search
│   ├── Waste
│   ├── Measurement
│   ├── Budget/Bidding
│   └── Revenue
│
├── Control
│   ├── Actions
│   ├── Automation
│   ├── Experiments
│   └── AI Control
│
├── Proof
│   ├── Recovery
│   └── Reports
│
└── Administration
    ├── Integrations
    ├── Business Truth
    ├── Organization
    ├── Billing
    ├── Security/Data
    └── Support
```

---

# 4. Global navigation model

## 4.1 Primary left navigation

### OVERVIEW
- Command Center
- Accounts
- Portfolios

### INTELLIGENCE
- Search Intelligence
- Waste Intelligence
- Measurement
- Budget & Bidding
- Revenue Intelligence

### OPERATIONS
- Action Center
- Automation
- Experiments
- Monitoring & Alerts

### PROOF
- Recovery Center
- Reports

### ORGANIZATION
- Business Truth
- Integrations
- Team & Access
- Billing
- Security & Data

### SUPPORT
- Help Center
- System Status

Navigation visibility is role- and plan-aware, but hidden navigation must never be the security boundary.

---

## 4.2 Persistent top bar

Required elements:

1. Organization selector
2. Portfolio/account context selector
3. Global date range
4. Data freshness indicator
5. Global search / command palette
6. Notifications
7. Help
8. User menu

### Context selector behavior
A user can work in:
- organization scope,
- portfolio scope,
- account scope.

Every module must declare whether it supports each scope.

Example:
- Search Intelligence: account + portfolio
- Business Truth: account
- Billing: organization
- Recovery Center: organization + portfolio + account.

---

# 5. Context model

Every page receives a first-class `ProductContext`:

```text
organization_id
workspace_id?
portfolio_id?
account_id?
currency_context
timezone_context
date_range
comparison_range?
user_role
account_permissions
data_freshness
billing_entitlement
integration_health
```

Rules:

- No page may infer account scope from a previous URL accidentally.
- Cross-account aggregation must explicitly state currency/timezone normalization.
- Account-scoped actions cannot be initiated while the UI is in ambiguous organization scope.
- If selected context becomes inaccessible, the user is redirected to a safe available context.

---

# 6. Main shell layouts

## 6.1 Command Center layout
```
[Global status strip]
[Recovery headline] [Spend at risk] [Measurement confidence] [Alerts]

[What needs attention now]
- critical alerts
- high-value recovery cases
- overdue tasks
- stale data

[Account / portfolio health distribution]

[Recent changes] [Recent verified recovery]
```

## 6.2 Explorer layout
Used by Search Intelligence, Waste Intelligence, Measurement, Alerts.

```
Page header
Scope / date controls
KPI strip

Filter bar
Saved views
Column selector
Export

Data table / explorer
Detail side panel
```

Important behavior:
- opening detail does not lose filters/scroll position,
- URL contains shareable filter state where safe,
- batch selection survives side-panel inspection.

## 6.3 Case / proposal detail layout
```
Breadcrumb
Status + severity
Owner + timestamps
Economic summary

Evidence tabs
Diagnosis
Proposed action
Risk / conflicts
Approval
Execution
Verification
History / comments
```

## 6.4 Settings layout
```
Settings sidebar
Section heading
Current state
Editable form
Validation
Save / cancel
Version/history
```

---

# 7. Design system foundations

## 7.1 Visual density
Recovery OS is a professional data/workflow product, not a consumer landing page.

Three density modes:
- Comfortable
- Standard
- Compact

Tables default to Standard.

## 7.2 Typography hierarchy
Must distinguish:
- money,
- status,
- entity names,
- evidence,
- supporting metadata.

Financial numbers need tabular numerals.

## 7.3 Status language
Canonical statuses only.

### Data
- Fresh
- Delayed
- Stale
- Incomplete
- Unavailable

### Evidence
- Supported
- Review Required
- Insufficient Evidence
- Conflicting Evidence

### Risk
- Low
- Medium
- High
- Blocked

### Actions
- Draft
- Ready for Review
- Approved
- Rejected
- Queued
- Validating
- Applying
- Applied
- Failed
- Needs Reconciliation
- Rolled Back

### Recovery
- Candidate
- Projected
- Observed
- Verification Pending
- Verified
- Inconclusive

Do not create synonyms per page.

---

# 8. Money presentation contract

Four canonical money components:

### Potentially avoidable observed spend
Label must contain "observed" or equivalent.

### Projected prevented spend
Must visually say projection/estimate.

### Post-action observed impact
Must not be labeled recovered.

### Verified recovery
May be presented as recovered only when backend says verified.

Never combine all four into a single total.

---

# 9. Core reusable components

## Navigation
- AppSidebar
- ContextSwitcher
- AccountSwitcher
- PortfolioSwitcher
- Breadcrumbs
- CommandPalette

## Data / intelligence
- MetricCard
- MetricDelta
- EvidenceBadge
- ConfidenceBadge
- DataFreshnessBadge
- MoneyClassificationCard
- TrendChart
- BreakdownChart
- DistributionChart
- DataTable
- FilterBuilder
- SavedViewMenu
- ColumnSelector
- EntityLink
- Pagination
- BulkSelectionBar

## Action / governance
- RiskBadge
- ProposalCard
- ActionPreview
- CollisionWarning
- ApprovalPanel
- ExecutionTimeline
- RollbackPanel
- AuditTrail
- CommentThread
- AssigneePicker

## States
- EmptyState
- LoadingSkeleton
- ErrorState
- PermissionState
- BillingRestrictedState
- IntegrationDisconnectedState
- DataStaleBanner
- InsufficientEvidenceState
- ProviderIncidentBanner
- AIBaseLineFallbackBanner

## Forms
- ValidatedForm
- UnsavedChangesGuard
- VersionDiff
- ConfirmationDialog
- DestructiveActionDialog

---

# 10. Tables — production standard

Every serious explorer table must support, where meaningful:

- server-side sorting,
- server-side filtering,
- search,
- date range,
- pagination / virtualization,
- column selection,
- pinned columns,
- saved views,
- CSV export,
- row detail,
- bulk selection,
- permission-aware actions,
- loading,
- no-results,
- partial-data states.

The product must not ship static HTML tables that fail with real account volume.

---

# 11. Global search / command palette

Search targets:
- accounts,
- portfolios,
- campaigns,
- search terms,
- Recovery Cases,
- proposals,
- reports,
- alerts,
- settings pages.

Commands:
- switch account,
- start sync,
- open Action Center,
- create report,
- open Business Truth,
- invite user (authorized roles),
- contact support.

The command palette must respect user permissions.

---

# 12. Notifications center

Notification classes:
- urgent system alert,
- PPC alert,
- action approval,
- action result,
- report ready,
- sync/analysis failure,
- integration disconnected,
- billing,
- team mention/assignment,
- product/system announcement.

Capabilities:
- read/unread,
- filter,
- mark all read,
- deep link,
- notification preferences,
- email/Slack mirroring later.

---

# 13. Task system shell

Even before full Automation Studio, V1 needs operational tasks.

Task sources:
- alert,
- Recovery Case,
- manual task,
- onboarding,
- recurring workflow later.

Fields:
- title,
- organization/account,
- linked entity,
- assignee,
- due date,
- priority,
- status,
- created by,
- source,
- comments.

Views:
- My Tasks,
- Team Tasks,
- Account Tasks.

---

# 14. Role-aware shell behavior

Canonical V1 roles:

### Owner
All organization rights, billing, deletion, security, users.

### Admin
Operational administration, integrations, account access, actions.

### Analyst
Analysis, syncs, findings, proposals; no billing/security/destructive org actions.

### Approver
Review/approve consequential account changes; may overlap Analyst.

### Viewer
Read-only.

### Client Viewer
Restricted client-facing reports/approved views.

### Internal Support
Separate internal admin identity, never customer role.

Role visibility in UI is convenience; server enforcement is mandatory.

---

# 15. Data freshness framework

Persistent global freshness indicator must report:

- Google Ads last successful sync,
- latest analysis,
- CRM/GA4 freshness when connected,
- known provider delays,
- whether the current date range is fully covered.

Freshness states:
- Current
- Delayed
- Stale
- Partial
- Failed

Clicking freshness opens a Data Status panel with:
- last successful sync,
- currently running jobs,
- failures,
- reconnect/resync actions if authorized.

---

# 16. Global degraded-mode framework

## Google Ads unavailable
- retain previous data,
- clearly show stale timestamp,
- disable actions requiring fresh readback,
- preserve historical reporting.

## Gemini/AI unavailable
- deterministic fallback,
- AI badge shows fallback,
- no page failure solely because semantic provider is down.

## PostgreSQL degraded
- fail readiness,
- no false success.

## Billing provider unavailable
- existing reconciled entitlement remains according to policy,
- no unverified plan upgrade.

## CRM unavailable
- downstream revenue quality marked stale/unknown,
- do not silently treat missing CRM outcomes as zero.

---

# 17. Required Epic-1 screens

## Shell / overview
- APP-001 App Shell
- APP-002 Command Center
- APP-003 Global Search / Command Palette
- APP-004 Notifications Center
- APP-005 Data Status Drawer
- APP-006 My Tasks
- APP-007 Team Tasks

## Account context
- APP-008 All Accounts
- APP-009 Account Detail Shell
- APP-010 Portfolios
- APP-011 Portfolio Detail Shell
- APP-012 Account / Portfolio Switcher

## Profile / support basics
- APP-013 User Profile
- APP-014 Notification Preferences
- APP-015 Help Entry
- APP-016 Permission Denied
- APP-017 Billing Restricted
- APP-018 Integration Disconnected
- APP-019 Global Error / Incident State

These are shell screens; future epic pages mount inside this system.

---

# 18. URL architecture

Example:

```text
/app
/app/accounts
/app/accounts/:accountId
/app/accounts/:accountId/search
/app/accounts/:accountId/waste
/app/accounts/:accountId/measurement
/app/accounts/:accountId/actions
/app/accounts/:accountId/recovery

/app/portfolios/:portfolioId
/app/alerts
/app/tasks
/app/reports

/app/settings/business-truth/:accountId
/app/settings/integrations
/app/settings/team
/app/settings/billing
/app/settings/security
```

Rules:
- entity IDs are stable backend IDs,
- filters may be URL-encoded,
- secrets/tokens never appear in URLs,
- page refresh must preserve meaningful state.

---

# 19. Accessibility requirements

Minimum:
- keyboard navigation,
- visible focus,
- semantic headings,
- ARIA labels where needed,
- chart alternatives / data tables,
- status not conveyed only by color,
- WCAG AA contrast targets,
- large-click targets for critical actions,
- screen-reader labels for money classification.

Accessibility is acceptance criteria, not post-launch polish.

---

# 20. Responsive strategy

Desktop is primary for deep PPC operations.

Required:
- 1440+ full density,
- 1024 laptop usable,
- tablet read/review flows,
- mobile command center, alerts, approvals, reports.

Do not attempt full dense query-table editing on phone if it damages usability; provide mobile-appropriate review/detail workflows.

---

# 21. Performance targets

Shell:
- first authenticated navigation should feel immediate after session verification,
- navigation transitions preserve shell,
- tables use server pagination/virtualization,
- heavy charts lazy-load,
- skeletons reflect final layout.

Initial production budgets:
- avoid loading full search-term datasets into browser memory,
- no 100k-row JSON responses,
- aggregations computed server-side.

---

# 22. Analytics / instrumentation

Events:
- page viewed,
- filter used,
- saved view created,
- account switched,
- finding opened,
- proposal reviewed,
- action approved/rejected,
- report generated,
- onboarding step completed,
- error/degraded state encountered.

Never send:
- raw sensitive query data to third-party analytics unless explicitly approved,
- API keys,
- CRM PII,
- billing secrets.

---

# 23. Epic-1 backend dependencies

Need APIs for:
- current user/org memberships,
- organizations,
- portfolios,
- accounts,
- account health summary,
- data freshness,
- notifications,
- tasks,
- permission matrix,
- global search,
- basic command-center summary.

Existing backend primitives may be reused, but page contracts must be designed against this mature shell.

---

# 24. Acceptance criteria

Epic 1 is complete only if:

1. user can switch organization/account/portfolio without context leaks,
2. permissions affect available operations,
3. account/portfolio views scale beyond a handful of accounts,
4. all required shell states are implemented,
5. money classifications use canonical language,
6. stale/partial data is always visible,
7. global search works across authorized entities,
8. notifications deep-link correctly,
9. tasks support assignee/due/status,
10. shell is keyboard-accessible,
11. critical screens work at laptop width,
12. role and context are enforced server-side,
13. E2E tests cover login → account switch → command center → alert/task navigation,
14. no customer secret is exposed client-side,
15. shell can host all future canonical modules without another navigation rewrite.

---

# 25. Implementation sequence

### 1. Design tokens + base components
Typography, spacing, status semantics, tables, forms, drawers.

### 2. Shell
Sidebar, topbar, context, breadcrumbs.

### 3. Account / portfolio management shell
Accounts table, portfolios, context switcher.

### 4. Command Center
Backend summary contracts + real data states.

### 5. Notifications + tasks
Operational workflow layer.

### 6. Global degraded states
Freshness, outage, permission, billing.

### 7. Command palette
Cross-product navigation.

### 8. Accessibility / responsive / E2E hardening

Only after this should Epic 2 (onboarding and account activation) be implemented.