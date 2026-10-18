# V1 Build Completion Contract

Version: 0.35.0

## Purpose

This release closes the final code-level gaps inside the canonical Recovery OS V1 scope. It does not expand V1 by pulling V1.5/V2 roadmap items forward, and it does not claim that external staging/production launch qualification has passed.

## V1 completion surfaces

### Business Truth

Business Truth is now a first-class account product surface rather than only onboarding state.

Implemented:

- current immutable Business Truth version and fingerprint;
- readiness by supported claim type;
- guided version creation for offers, explicit non-offers, intent rules, audiences, geography and business outcomes;
- confirmed protected queries / brand traffic;
- immutable version history and version detail;
- semantic section-change visibility;
- backend read permissions for Viewer/Analyst and write permission for Admin/Owner.

Action-safety consequence: confirmed protected queries are translated into `ProtectedQuery` facts and passed to the negative-keyword safety engine. A negative candidate that would block a protected query is blocked rather than merely displayed as a UI warning.

### Security & Data

Security & Data is now a customer-facing control surface with a bounded scope.

Implemented:

- membership/access posture;
- safe Google Ads connection metadata without provider credential references;
- current legal-acceptance visibility;
- recent access/security activity;
- documented retention/product-security boundaries;
- bounded configuration/audit JSON export;
- controlled requests for full data export, Google Ads disconnect and organization deletion;
- append-only request lifecycle evidence.

Destructive organization deletion is intentionally **not** an immediate browser operation. An Owner can create a controlled deletion request; operational execution remains outside the customer browser and must retain audit/retention/legal safeguards.

The configuration/audit export intentionally excludes OAuth refresh tokens/secret references, provider credentials, raw report-share capability tokens, billing secrets and other authentication material.

### Help & Support basics

Help is now an operating V1 surface rather than a static explanation page.

Implemented:

- API/release context;
- selected-account setup and monitoring status;
- onboarding/readiness checklist;
- product truth-rule explanations;
- customer support case creation;
- append-only support conversation/state history;
- close/reopen workflow;
- V1 changelog.

## V1 scope boundary

The following remain deliberately outside V1 build completion:

- Budget & Bidding Intelligence;
- Automation Studio;
- Experiment Center;
- full Lead & Revenue Intelligence / deeper CRM outcome integration;
- arbitrary report builder / advanced white-label designer;
- broad integration marketplace;
- enterprise SSO;
- public API/webhooks;
- Microsoft Ads / cross-channel recovery.

These are V1.5/V2 roadmap capabilities, not defects in the V1 completion claim.

## Completion definition

`V1 build complete` means:

1. all canonical V1 product surfaces have implemented backend + authorization + customer UI contracts;
2. consequential Google Ads and billing actions remain governed by their existing approval/provider/reconciliation safety contracts;
3. Business Truth protection affects real action safety;
4. customer security/data/support workflows have append-only evidence and do not expose secrets/destructive shortcuts;
5. cumulative regression, frontend contract and parser gates pass on the exact packaged artifact.

It does **not** mean:

- Google Ads production access has been approved;
- Razorpay live lifecycle has been exercised;
- a production restore drill has passed;
- production observability/on-call/security review has passed;
- the exact release has passed the external pilot/launch gate;
- public launch has occurred.

Those are external Launch Execution Qualification requirements and remain fail-closed independently of code completion.
