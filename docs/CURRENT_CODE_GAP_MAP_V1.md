# Recovery OS — Current Code Keep / Replace / Build Map v1.0

**Reference baseline:** the cumulative engineering codebase built through the deployment/acceptance work before this canonical reset.

The purpose of this document is to prevent sunk-cost thinking. Existing code is kept only where it supports the mature target.

---

## 1. Executive assessment

Against the mature product specification, the current system should be classified as:

**Engineering foundation / internal platform v0.x — approximately 3–5% of the mature customer product experience.**

That percentage is intentionally based on the complete SaaS benchmark, not code volume.

---

## 2. Keep / Expand / Replace / Build matrix

| Area | Decision | Current usefulness | What must happen |
|---|---|---:|---|
| Google Ads Search ingestion | KEEP + EXPAND | High | Add broader campaign/account inventory, insights, recommendations, budget/bid/creative/measurement data. |
| Search-term normalization | KEEP | High | Integrate with richer Search Intelligence UX and clustering. |
| Business Truth core | KEEP + HEAVILY EXPAND | Very high | Replace raw JSON UX with complete guided editor, provenance, completeness and review workflows. |
| Semantic safety / UNKNOWN behavior | KEEP | Very high | Add production-grade multilingual evaluation and richer domain taxonomy. |
| Financial evidence primitives | KEEP | Very high | Expand into all leak families and measurement-confidence dependencies. |
| Negative keyword safety | KEEP | High | Generalize Action Center beyond negatives. |
| Approval/fingerprint model | KEEP | High | Become generic change-governance engine for all action types. |
| Recovery Ledger primitives | KEEP | Very high | Build complete Recovery Center and Recovery Case UX around it. |
| Experiment verification concepts | KEEP | High | Integrate with full Experiment Center. |
| PostgreSQL append-only evidence | KEEP | Very high | Extend schema to mature product domains. |
| Multi-tenant authorization | KEEP | High | Expand organization/workspace/client/account permission model. |
| Durable worker | KEEP | High | Add observability, scheduling, more job types, operator tools. |
| AI release/shadow/drift concepts | KEEP | High | Move most complexity to internal AI Control Center. |
| Billing provider integration | KEEP CONCEPT | Medium | Add real lifecycle: invoices, plan change, cancellation, dunning, contacts. |
| Deployment scripts | KEEP | Medium-high | Add full observability, backup validation, SLOs, CI/CD and environment promotion. |
| Current dashboard IA | REPLACE | Low | Rebuild according to canonical product IA. |
| Current six-page UI | REPLACE | Low | Use only as throwaway reference/prototype. |
| Current onboarding | REPLACE | Low | Build guided first-run product activation. |
| Current raw Business Truth submission | REPLACE | Low | Build structured business setup and review. |
| Current reporting | BUILD | Minimal | Create reporting system from scratch. |
| Monitoring UX | BUILD | Minimal | Create monitoring/alert system. |
| Automation Studio | BUILD | None | Create strategy/rules/schedule platform. |
| Budget/Bidding Intelligence | BUILD | None | Add data, models, workflows, screens. |
| Measurement Integrity product | BUILD | Low primitives only | Build full tracking/measurement product. |
| Lead & Revenue Intelligence | BUILD | None | CRM integrations, outcome model and revenue paths. |
| Agency operations | BUILD | Low auth primitives only | Portfolios, clients, assignments, continuity. |
| Help center / support | BUILD | None | Customer support surfaces and internal support tools. |
| Internal admin console | BUILD | Minimal backend pieces | Build operator UX and workflows. |
| Data export/delete | BUILD | None | Privacy/operations workflows. |
| White-label reporting | BUILD | None | Agency/client reporting. |
| Public API / webhooks | BUILD LATER | None | V2. |
| Microsoft Ads | BUILD LATER | None | V2. |

---

## 3. What the current code is allowed to be

The existing code may serve as:

- core domain library,
- data ingestion/adapters,
- evidence store,
- safe-action primitives,
- worker/runtime foundation,
- AI evaluation infrastructure,
- billing provider adapter,
- deployment reference.

It must **not** dictate:
- navigation,
- screen count,
- module boundaries,
- product terminology,
- onboarding sequence,
- commercial packaging,
- reporting architecture,
- admin UX.

---

## 4. Immediate replacement targets

### 4.1 Information architecture
Replace the current small dashboard structure with the canonical domain model.

### 4.2 Design system
Create a mature SaaS design system:
- navigation,
- page templates,
- data tables,
- filter bars,
- side panels,
- evidence cards,
- status/risk chips,
- charts,
- approval components,
- empty/error/stale states,
- mobile behavior,
- accessibility.

### 4.3 Onboarding
Current technical setup must become:
1. organization,
2. billing,
3. Google connection,
4. account selection,
5. business setup,
6. measurement check,
7. first analysis,
8. first value moment.

### 4.4 Business Truth
Raw structured payload entry must disappear from normal customer UX.

### 4.5 Recovery Case
Introduce a first-class case object that unifies finding, action, verification and economic result.

---

## 5. New engineering epics required for serious V1

### Epic A — Canonical frontend shell
Navigation, account/portfolio context, responsive layout, permissions, global search, notifications.

### Epic B — Onboarding & account activation
Complete customer activation journey.

### Epic C — Search Intelligence
Deep query explorer, clustering, n-grams, emerging demand, saved views.

### Epic D — Waste Intelligence
Leak families, evidence, trends, drilldowns.

### Epic E — Measurement Integrity
Conversion inventory, mapping, tag/tracking confidence.

### Epic F — Action Center
Generic action governance beyond negative keywords.

### Epic G — Recovery Cases & Recovery Center
Signature evidence-to-value workflow.

### Epic H — Monitoring & Alerts
Always-on operating reliability.

### Epic I — Reporting
Saved/scheduled/custom reports.

### Epic J — Organization / agency operations
Portfolio/client/team workflows.

### Epic K — Billing lifecycle
Complete commercial lifecycle.

### Epic L — Internal admin/support
Operate the SaaS safely.

---

## 6. Mature V1 acceptance threshold

Do not call V1 commercially mature until:

- 35–50 serious primary screens exist,
- all V1 workflows are connected end to end,
- all major empty/error/stale/permission states exist,
- onboarding reaches first value without developer assistance,
- Search Intelligence and Waste Intelligence are genuinely deep,
- Measurement Integrity can tell users whether outcome data is trustworthy,
- actions are governable and reversible,
- Recovery Center can prove value,
- alerts operate continuously,
- reports can be scheduled/shared,
- organization/team/billing flows are complete,
- internal admin can support customers,
- E2E tests cover critical flows,
- real pilot advertisers have used the product successfully.

---

## 7. Development sequencing from this point

Do not resume arbitrary phase numbering.

Use product epics in this order:

1. **Product shell + design system + canonical IA**
2. **Onboarding + account activation**
3. **Search Intelligence**
4. **Waste Intelligence**
5. **Measurement Integrity**
6. **Recovery Cases + Action Center**
7. **Recovery Center**
8. **Monitoring & Alerts**
9. **Reporting**
10. **Organization/Agency operations**
11. **Billing lifecycle**
12. **Admin/support**
13. **Pilot hardening**
14. **V1 launch**

Every epic follows:
research → specification → data contract → UX flows → failure states → acceptance tests → implementation → pilot validation.