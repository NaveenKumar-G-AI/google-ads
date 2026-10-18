# Phase 2 — Business Truth Model

## Purpose

The Search Intent Engine must never decide that a query is irrelevant merely because an LLM thinks it "looks wrong". It needs a versioned, operator-confirmed statement of what the business actually sells, does not sell, serves, wants, and counts as a valuable outcome.

This model is intentionally separate from current Google Ads configuration. Current targeting, keywords, locations, and conversions are *observed account state* and may themselves be wrong.

## Accuracy invariants

1. **Missing means unknown, not false.** An unlisted service is not automatically a service the business does not provide.
2. **Catalog completeness is explicit.** Absence is meaningful only when the operator confirms the catalog is complete.
3. **Explicit non-offers are first-class facts.** A partial catalog can still safely say specific services are not offered.
4. **No universal intent defaults.** Employment, free, informational, competitor, support, DIY, etc. are not assumed bad. A confirmed business policy is required.
5. **Conditional stays conditional.** It cannot become an automatic exclusion without later context.
6. **Geo truth is business truth, not Google targeting.** The model distinguishes the customer's physical presence from the destination/job/service location.
7. **Conversion truth is business outcome truth.** A tracked Google conversion is not automatically a valuable business outcome.
8. **Provisional AI/site extraction cannot authorize write actions.** High-confidence actions require confirmed facts.
9. **Contradictions fail closed.** Confirmed active offers cannot simultaneously be confirmed non-offers; conflicting confirmed intent policies are rejected.
10. **Every snapshot is immutable and fingerprinted.** Downstream decisions can store the exact SHA-256 of the truth snapshot used at decision time.

## Why catalog completeness exists

If the operator lists:

- Roof replacement
- Roof repair

that does **not** prove "gutter installation" is irrelevant unless either:

- the operator marks the service catalog COMPLETE, or
- "gutter installation" is recorded as an explicit confirmed non-offer.

This prevents a common AI failure: treating missing information as negative information.

## Intent policy examples

- EMPLOYMENT -> DENY: acquisition account does not recruit.
- FREE -> ALLOW for one offer: free inspections are genuinely offered.
- COMPETITOR -> CONDITIONAL: comparison intent can sometimes produce customers.
- INFORMATIONAL -> CONDITIONAL: educational queries may belong in an upper-funnel campaign.

No category receives a built-in allow/deny default.

## Geographic truth

The model supports different business realities:

- plumber: customer/job must be inside service area;
- hotel: searcher can be elsewhere while destination is inside the service area;
- SaaS: no geographic restriction;
- complex businesses: conditional.

This is deliberately different from Google Ads' configured geo targeting.

## Snapshot fingerprint

`BusinessTruthSnapshot.fingerprint_sha256` is deterministic. Collection order does not change it, while a semantic/versioned business-truth change does.

Future findings should persist at minimum:

- business truth version;
- business truth SHA-256;
- Google Ads data window;
- model/rules version;
- finding evidence;
- action approval identity/time.

That is the basis for reproducibility and auditability.
