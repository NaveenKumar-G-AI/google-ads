# Epic 3 — Search Intelligence Implementation Contract

Version: 0.22.0

## Implemented backend

- server-authoritative search-intelligence APIs
- completed-sync-only visible query reads
- default date window bound to latest completed analysis source sync when possible
- exact-window financial evidence gating
- visible/comparable/unobserved spend coverage calculation
- server pagination and filtering
- latest semantic/business-fit overlay with conflict handling
- query detail by campaign/ad group/network/match source/triggering keyword
- daily query series
- 1–6 token lexical n-grams
- portfolio n-grams separated by currency
- user saved views with RLS
- migration indexes for explorer reads

## Implemented frontend

Canonical Search Intelligence navigation now opens real product surfaces:
- Overview
- Terms
- Term detail
- N-grams
- Breakdowns
- portfolio n-grams

The account workspace links directly into Search Intelligence.

## Non-negotiable financial behavior

If `selected_window != latest_analysis.source_sync_window`:
- `potentially_avoidable_observed_micros` from the analysis is suppressed
- `review_required_observed_micros` from the analysis is suppressed
- evidence status is suppressed
- semantic/business-fit labels may remain visible as latest-classification context

This prevents date-window drift from turning a valid historical finding into a false financial claim.

## Privacy behavior

The query explorer contains only search terms persisted from Google Ads query reporting. The coverage denominator may reveal that some Search spend is unobserved at query level; Recovery OS displays that as unobserved coverage only.

It does not infer individual hidden search terms.

## Authorization

- viewer: read Search Intelligence
- analyst: read + manage their own saved views
- admin/owner: all Search Intelligence permissions

Saved views are additionally user-scoped in PostgreSQL RLS.

## Acceptance gate

Epic 3 is accepted only when:
- all cumulative tests pass
- Epic-3 domain/migration/source/API/frontend contracts pass
- Python compiles
- frontend validator passes
- no TypeScript parser errors exist
- clean packaged ZIP re-extracts and passes the same checks
- no server secrets are included in browser source or packaged credential files
