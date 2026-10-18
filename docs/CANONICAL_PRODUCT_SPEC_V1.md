# Recovery OS — Canonical Product Specification v1.0

**Status:** Canonical target specification  
**Product category:** Paid Search Revenue Recovery OS  
**Working product name:** Recovery OS  
**Primary platform:** Google Ads first; paid-search expansion later  
**Purpose of this document:** This is the source of truth for all future product planning and implementation. Existing code is an engineering foundation, not the product specification.

---

## 1. Product thesis

Recovery OS exists to answer five questions continuously:

1. **Detect** — Where is paid-search value leaking?
2. **Diagnose** — Why is it leaking?
3. **Decide** — What should change?
4. **Control** — How can the change be made safely?
5. **Prove** — Did the intervention actually improve business outcomes?

The product must not be positioned as another generic “Google Ads optimizer.” Google Ads and mature PPC tools already provide recommendations, reporting, experiments, alerts, rules, budgets, and direct account actions. Recovery OS must differentiate by combining:

- advertiser-specific Business Truth,
- paid-search demand intelligence,
- conversion/measurement integrity,
- lead and revenue quality,
- safe change control,
- causal verification,
- auditable recovery economics.

The signature product object is **not a recommendation**. It is a **Recovery Case**: a complete evidence chain from observed leak → diagnosis → proposed action → approval → execution → verification → economic outcome.

---

## 2. Non-negotiable product principles

### 2.1 Accuracy before automation
No action may be generated from weak or incomplete evidence. UNKNOWN and REVIEW REQUIRED are first-class outputs.

### 2.2 Business truth outranks ad-platform assumptions
Google Ads configuration is evidence, not ground truth. The advertiser’s confirmed offerings, exclusions, locations, audiences, qualification rules, and revenue definitions form the Business Truth layer.

### 2.3 Financial categories must remain distinct
The product must never collapse these into one number:

- historical potentially avoidable observed spend,
- projected prevented spend,
- post-action observed change,
- causally verified recovery.

Only the final category can be presented as verified recovery.

### 2.4 Human control for consequential changes
Actions that can suppress traffic, change budget allocation, alter bidding, change conversion configuration, or materially affect delivery must have configurable approval policy and a reversible audit trail.

### 2.5 No hidden-query extrapolation presented as fact
Privacy-hidden or otherwise unobserved query spend is a coverage limitation, not invented waste.

### 2.6 Every consequential decision must be reproducible
A future auditor must be able to reconstruct:
- the exact data snapshot,
- Business Truth version,
- model/rule version,
- evidence,
- proposal,
- approval,
- external action,
- verification result.

### 2.7 Mature SaaS means complete workflows
A module is not “done” because a data table and one dashboard exist. Every production module requires:
- overview,
- detail/explorer,
- filters/search,
- history,
- empty/loading/error states,
- permissions,
- notifications,
- exports where appropriate,
- audit trail,
- supportability,
- failure recovery.

---

## 3. Primary customer segments

### 3.1 In-house paid search team
Needs cross-account visibility, measurement trust, safe automation, budget/revenue proof, reporting to leadership.

### 3.2 Performance marketing agency
Needs portfolios, client workspaces, user roles, reusable strategies, scheduled workflows, white-label reporting, collaboration, account continuity when staff change.

### 3.3 Owner-operated / SMB advertiser
Needs strong onboarding, clear money language, low-complexity recovery actions, guided approvals, simple reporting.

### 3.4 Finance / revenue leader
Needs economic proof: spend at risk, verified recovery, downstream lead/revenue quality, ROI of platform.

### 3.5 Internal support/admin operator
Needs tenant lookup, failed-job recovery, billing reconciliation, provider incident tools, release controls, auditability.

---

## 4. Canonical product domains

### Domain 01 — Command Center
**Goal:** Give the user one reliable operating picture of paid-search health.

Capabilities:
- executive recovery summary,
- spend-at-risk summary,
- verified recovery,
- measurement confidence,
- active alerts,
- urgent tasks,
- budget pacing,
- major changes,
- data freshness,
- AI/release health,
- account-health distribution,
- “what changed since last visit”.

Required views:
- organization command center,
- portfolio command center,
- single-account command center,
- executive compact mode.

---

### Domain 02 — Portfolio & Account Management
Capabilities:
- all accounts,
- account groups/portfolios,
- labels/tags,
- account lifecycle,
- owners,
- account health,
- data freshness,
- spend bands,
- client assignment,
- account comparison,
- account search/filter,
- multi-account bulk actions,
- account switcher.

---

### Domain 03 — Search Intelligence
Capabilities:
- search-term explorer,
- intent classification,
- query clustering,
- n-gram explorer,
- emerging queries,
- demand themes,
- search-term insights,
- match-source analysis,
- triggering keyword analysis,
- Search Partner analysis,
- business-fit analysis,
- conversion-quality overlay,
- revenue-quality overlay,
- query-history timeline,
- saved views,
- exports,
- alerts on new query patterns.

---

### Domain 04 — Waste Intelligence
Leak families:
- irrelevant intent,
- wrong service/product,
- employment intent,
- free/DIY intent,
- support intent,
- education/training intent,
- wrong geography,
- brand leakage,
- competitor leakage,
- Search Partner inefficiency,
- device inefficiency,
- schedule inefficiency,
- duplicate targeting,
- cannibalization,
- low-quality lead sources,
- campaign overlap,
- landing-page mismatch.

Every leak family requires:
- detection rule,
- evidence threshold,
- impact calculation,
- confidence,
- affected scope,
- recommended action,
- safety policy,
- history,
- verification method.

---

### Domain 05 — Measurement Integrity
Capabilities:
- conversion inventory,
- primary vs secondary actions,
- duplicate conversion detection,
- missing conversion detection,
- conversion-value quality,
- tag health,
- GA4 reconciliation,
- GTM status,
- enhanced conversions,
- call tracking,
- form tracking,
- WhatsApp/button tracking,
- attribution windows,
- conversion lag,
- consent/data-quality indicators,
- measurement-confidence score,
- business-outcome mapping.

---

### Domain 06 — Lead & Revenue Intelligence
Capabilities:
- lead-stage mapping,
- qualified lead rate,
- opportunity rate,
- closed-won rate,
- revenue attribution,
- search term → lead → opportunity → sale path,
- campaign/source quality,
- low-quality lead clusters,
- CRM outcome lag,
- offline conversion upload status,
- revenue-value confidence,
- source-quality cohorts.

Primary integrations:
- HubSpot,
- Salesforce,
- Zoho CRM,
- Pipedrive,
- optional CSV/manual import for early V1.5.

---

### Domain 07 — Campaign Health
Capabilities:
- campaign structure,
- ad-group health,
- keyword coverage,
- match-type distribution,
- negative coverage,
- Quality Score diagnostics,
- impression share,
- RSA asset coverage,
- asset strength trends,
- disapprovals,
- broken destination URLs,
- policy issues,
- location settings,
- network settings,
- device settings,
- schedule settings,
- optimization-score context without blindly trusting it.

---

### Domain 08 — Budget & Bidding Intelligence
Capabilities:
- account/campaign budgets,
- pacing,
- projected overspend/underspend,
- target CPA/ROAS health,
- bid-strategy learning status,
- budget-constrained campaigns,
- unused-budget detection,
- budget reallocation simulator,
- scenario forecast,
- seasonal annotations,
- month-end forecast,
- budget alerts.

---

### Domain 09 — Action Center
Capabilities:
- recommendation inbox,
- ranked impact,
- filters by risk/type/account,
- detail/evidence panel,
- exact change preview,
- collision detection,
- batch review,
- approve/reject,
- comments,
- stale-proposal detection,
- execution status,
- failed actions,
- rollback,
- action history,
- outcome verification,
- owner assignment.

---

### Domain 10 — Automation Studio
Core object:
**Strategy → Scope → Conditions → Evidence → Action → Risk → Approval Policy → Schedule → Verification → Notification**

Capabilities:
- prebuilt strategies,
- custom strategies,
- rule builder,
- dry run,
- preview affected entities,
- schedules,
- approval-required mode,
- auto-apply low-risk mode,
- exception lists,
- protected entities,
- notification destinations,
- run history,
- failures,
- rollback rules,
- strategy templates,
- copy strategy between accounts,
- agency-level strategy deployment.

---

### Domain 11 — Experiment Center
Capabilities:
- hypothesis builder,
- control/treatment setup,
- experiment eligibility,
- traffic split,
- schedule,
- monitoring,
- conversion-lag handling,
- statistical comparison,
- p-values/confidence intervals when supported,
- business-outcome validation,
- promote/reject decision,
- experiment history,
- experiment reports,
- action linkage to Recovery Cases.

---

### Domain 12 — Recovery Center
This is the signature module.

Capabilities:
- recovery overview,
- historical candidate spend,
- projected prevented spend,
- post-action observed impact,
- causally verified recovery,
- recovery by account,
- campaign,
- query cluster,
- leak family,
- action type,
- time period,
- verification status,
- disputed/reviewed cases,
- SaaS ROI,
- evidence chain,
- exportable executive proof.

---

### Domain 13 — Monitoring & Alerts
Monitoring families:
- serving outage,
- spend spike/drop,
- conversion drop,
- qualified-lead drop,
- revenue drop,
- tracking outage,
- tag/config drift,
- budget pacing,
- CPC/CPL/CPA anomaly,
- query anomaly,
- new bad-intent cluster,
- landing-page failure,
- ad disapproval,
- policy issue,
- AI release trip,
- worker failure,
- provider outage,
- stale data,
- previously-fixed leak recurrence.

Capabilities:
- alert policies,
- severity,
- deduplication,
- grouping,
- escalation,
- acknowledge/resolve,
- Slack/Teams/email,
- quiet hours,
- audit trail.

---

### Domain 14 — Reporting
Report families:
- Executive Recovery Report,
- Waste Report,
- Measurement Integrity Report,
- Search Demand Report,
- Account Health Report,
- Change Impact Report,
- Monthly Client Report,
- Audit Report,
- Agency Portfolio Report,
- Experiment Report.

Capabilities:
- report builder,
- saved templates,
- scheduled reports,
- PDF,
- CSV,
- shareable secure links,
- white label,
- client branding,
- commentary,
- comparison periods,
- account groups,
- recipient management.

---

### Domain 15 — Organization & Agency Operations
Capabilities:
- organizations,
- workspaces,
- clients,
- portfolios,
- users,
- invitations,
- roles,
- account permissions,
- account ownership,
- task assignment,
- activity log,
- user deactivation,
- workload view,
- agency/client view separation,
- handover continuity.

---

### Domain 16 — Integrations
Core:
- Google Ads,
- GA4,
- GTM,
- CRM,
- Slack,
- Microsoft Teams,
- email.

Later:
- Microsoft Ads,
- Meta Ads,
- Looker Studio,
- Google Sheets,
- Power BI,
- Tableau,
- webhooks,
- public API,
- warehouse exports.

Each integration requires:
- connection state,
- permissions,
- last sync,
- errors,
- data scope,
- reconnect,
- disconnect,
- audit log.

---

### Domain 17 — Business Truth
Capabilities:
- business profile,
- products/services,
- explicit non-offers,
- aliases,
- audiences,
- service areas,
- intent policies,
- competitor policy,
- employment policy,
- free/DIY policy,
- qualification rules,
- primary outcomes,
- supporting outcomes,
- invalid outcomes,
- protected queries,
- brand terms,
- seasonality/context,
- truth completeness,
- evidence/provenance,
- version history,
- approval workflow.

---

### Domain 18 — AI Control Center
Capabilities:
- current semantic release,
- model/provider,
- approved languages,
- confidence threshold,
- shadow mode,
- production mode,
- release health,
- drift evaluations,
- reviewer queue,
- corrected labels,
- model version history,
- release activation/revocation,
- AI audit trail,
- fallback status,
- cost/usage,
- prompt/schema fingerprints.

Customer-facing UI should be simplified; internal/admin UI can expose deeper details.

---

### Domain 19 — Billing & Usage
Capabilities:
- current plan,
- usage,
- account limits,
- sync limits,
- invoice history,
- payment method,
- subscription state,
- checkout,
- upgrade/downgrade,
- scheduled plan change,
- cancellation,
- grace period,
- payment failure,
- billing contacts,
- tax details,
- entitlement history.

---

### Domain 20 — Security & Data Control
Capabilities:
- sessions,
- MFA/SSO roadmap,
- audit logs,
- API credentials,
- integration permissions,
- data retention,
- export,
- account disconnect,
- organization deletion,
- data deletion requests,
- security events,
- access reviews,
- privacy controls,
- legal basis/consent surfaces where applicable.

---

### Domain 21 — Help, Education & Support
Capabilities:
- onboarding checklist,
- contextual help,
- guided tours,
- help center,
- search,
- support tickets,
- contact support,
- system status,
- incident banners,
- feature announcements,
- changelog,
- best-practice education,
- “why this finding exists” explainers.

---

### Domain 22 — Internal Admin & Operations
Capabilities:
- tenant lookup,
- account lookup,
- user lookup,
- billing reconciliation,
- failed webhooks,
- failed workers,
- queue health,
- needs-reconciliation queue,
- integration incidents,
- provider status,
- feature flags,
- release controls,
- semantic release management,
- support notes,
- controlled impersonation with audit trail,
- abuse/risk flags,
- data export/delete operations,
- system-wide announcements.

---

## 5. Product-wide object model

Canonical business objects:

- Organization
- Workspace
- Client
- Portfolio
- User
- Role
- Google Ads Account
- Integration
- Business Truth Snapshot
- Sync Run
- Data Snapshot
- Search Observation
- Conversion Observation
- Lead Outcome
- Revenue Outcome
- Finding
- Recovery Case
- Proposal
- Approval
- Mutation
- Rollback
- Experiment
- Automation Strategy
- Automation Run
- Alert
- Report
- Recovery Ledger Entry
- Billing Subscription
- Entitlement
- AI Release
- AI Decision
- Review
- Audit Event
- Support Incident

---

## 6. Recovery Case — signature workflow

A mature Recovery Case must contain:

1. **Trigger**
   - why the case exists,
   - source data,
   - date range,
   - affected scope.

2. **Diagnosis**
   - leak family,
   - semantic/business explanation,
   - measurement quality,
   - financial evidence.

3. **Risk**
   - confidence,
   - missing data,
   - possible false-positive conditions,
   - collision/protected-traffic analysis.

4. **Action**
   - exact proposed change,
   - scope,
   - expected effect,
   - approval policy.

5. **Execution**
   - approver,
   - validation result,
   - provider resource,
   - timestamp,
   - failure details.

6. **Verification**
   - post-action observation,
   - experiment/control evidence where available,
   - conversion maturity,
   - business-outcome quality.

7. **Economic result**
   - historical candidate,
   - projection,
   - observed change,
   - verified recovery.

8. **History**
   - comments,
   - assignments,
   - reopened case,
   - rollback,
   - recurrence.

---

## 7. Canonical user journeys

### Journey A — New advertiser
Landing → Signup → Organization → Plan → Connect Google Ads → Select accounts → Business Truth → Measurement check → First sync → First analysis → Recovery opportunities → Review action → Approve → Apply → Monitor → Verify → Recovery report.

### Journey B — Agency
Signup → Agency organization → Team invites → Create client workspaces → Connect MCC/manager → Assign accounts → Apply Business Truth templates → Configure portfolio alerts → Run multi-account audits → Assign actions → Client reports → Reusable automation strategies.

### Journey C — Executive
Login → Executive command center → Recovery trend → Spend at risk → Measurement confidence → Largest unresolved cases → Verified recovery → Download/share executive report.

### Journey D — Analyst
Account → Search Intelligence → Filter emerging bad-intent cluster → Open Recovery Case → Inspect evidence → refine proposal → request approval → monitor application → verify result.

### Journey E — Admin
Organization → members/roles → billing → integration health → audit log → failed jobs → support issue → controlled recovery.

---

## 8. Required system states

Every primary view must define at minimum:

- loading,
- empty/new account,
- partial data,
- stale data,
- insufficient evidence,
- permission denied,
- billing restricted,
- integration disconnected,
- provider outage,
- failed sync,
- analysis running,
- analysis failed,
- no findings,
- degraded measurement,
- AI unavailable/fallback,
- action pending approval,
- action stale,
- action failed,
- verification pending,
- verification inconclusive.

A screen is not production-complete until these states are specified and tested.

---

## 9. V1 product boundary — serious paid release

The first paid release should not attempt all 22 domains at full depth.

### V1 — must be mature
1. Command Center
2. Portfolio / Account workspace
3. Search Intelligence
4. Waste Intelligence
5. Measurement Integrity
6. Action Center
7. Recovery Center
8. Monitoring / Alerts
9. Reporting
10. Organization / Billing / Settings
11. Business Truth
12. Help / Support basics
13. Internal Admin essentials

### V1.5
- Budget & Bidding Intelligence
- Automation Studio
- deeper agency operations
- CRM lead-quality integration
- scheduled/white-label reporting
- stronger integration marketplace

### V2
- full Lead & Revenue Intelligence
- Experiment Center
- broader CRM coverage
- enterprise SSO/security
- public API/webhooks
- Microsoft Ads
- richer cross-channel intelligence

### Not V1
- Meta/TikTok/Amazon optimization,
- autonomous high-risk bid/budget changes,
- enterprise warehouse ecosystem,
- full cross-channel MMM/attribution.

---

## 10. V1 quality bar

V1 is not ready merely when the screens exist.

Each mature V1 domain must have:

- complete IA,
- overview + drilldown,
- search/filter/sort,
- saved views where useful,
- backend-authoritative calculations,
- permissions,
- audit events,
- loading/empty/error/degraded states,
- exports where economically relevant,
- notifications,
- instrumentation,
- support runbook,
- E2E tests,
- accessibility pass,
- responsive behavior,
- real pilot validation.

---

## 11. Commercial differentiation

Recovery OS must avoid competing on generic optimization breadth alone.

Primary differentiators:

1. **Business Truth**
2. **Measurement Confidence**
3. **Search Demand / Intent Intelligence**
4. **Downstream Lead & Revenue Quality**
5. **Safe Action Governance**
6. **Recovery Case evidence chain**
7. **Verified Recovery Economics**
8. **Independent monitoring of leaks recurring after fixes**

A mature competitor may tell the user what to optimize. Recovery OS should be able to explain:
- what business outcome was lost,
- why,
- what evidence proves it,
- what action was taken,
- whether the outcome improved,
- and what value was actually recovered.

---

## 12. Canonical implementation rule

From this specification onward:

**No new feature is implemented before its module specification exists.**

For each feature:
1. benchmark relevant mature products and official Google Ads capability,
2. define user problem,
3. define business truth,
4. define data sources,
5. define states,
6. define permissions,
7. define edge/failure cases,
8. define output claims,
9. define acceptance tests,
10. then implement.

This document supersedes phase-by-phase feature invention as the planning source of truth.