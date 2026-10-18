# Epic 4 — Waste Intelligence Contract

Version: 0.23.0

## Purpose

Waste Intelligence classifies defensible paid-search leakage without treating weak performance, zero conversions, or campaign configuration as proof of waste.

## Financial truth model

### Query leak families

The V1 query taxonomy assigns each irrelevant normalized query exactly one primary financial family:

- wrong service/product
- employment
- free
- DIY
- support
- training
- competitor
- informational/research
- second-hand
- rental
- wholesale
- other denied intent
- generic irrelevant intent

The primary family prevents one query-level financial finding from being added to multiple business-reason totals.

### Dimensions are not extra money buckets

Network, device and daypart are evidence dimensions.

- Network may show the same supported query-mismatch money split by network. It must not be added to the query-family total.
- Device and daypart show observed metrics only in Epic 4. `financial_claim_supported=false` is authoritative. Zero conversions or weak ratios do not create a waste claim.

### Geography is separate and non-additive

Geographic leakage uses actual physical user-location observations plus confirmed Business Truth. It is a separate evidence lens that can overlap the same clicks/spend as query leakage and therefore must not be added to query-family money to create a grand waste total.

## Geography rules

- Campaign target settings are not proof of actual user location.
- Physical user location is comparable only when Business Truth says the **customer must be in** the service area.
- When Business Truth says the **job/destination must be in** the service area, physical user location cannot prove the destination is outside the service area; the result stays unknown/review-only.
- Country-only Google location rows are insufficient to prove a mismatch against a city/region/postal service area in the same country.
- Exact confirmed Google geo-target resource matches are preferred when available.
- Conversion lag controls maturity.
- A mature outside-area location with recorded conversion signals routes to review instead of being automatically classified as potentially avoidable.

## Data provenance

Epic 4 adds immutable evidence streams:

- `campaign_performance_segments`
- `user_location_observations`
- `waste_dimension_chunks`

They are tied to completed Google Ads sync runs, tenant isolated with PostgreSQL RLS and protected against update/delete mutation.

No derived `waste_total` is persisted.

## Product surfaces

- `/app/waste-intelligence`
- `/app/waste-intelligence/queries`
- `/app/waste-intelligence/dimensions`
- `/app/waste-intelligence/geo`

The overview intentionally presents query candidate/review and geo candidate/review separately.

## Not claimed in Epic 4

- device waste
- daypart waste
- bid/budget inefficiency
- low-quality lead waste from CRM outcomes
- causal verified recovery from waste findings
- PMax query leakage
- autonomous account changes

Those require additional evidence systems in later epics.
