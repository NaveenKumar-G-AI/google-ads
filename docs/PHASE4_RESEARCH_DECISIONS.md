# Phase 4 Research Decisions — Evidence & Waste Decision Engine

Verified against current Google documentation on 2026-10-15.

## Official facts that constrain the design

1. Search-term reporting is incomplete by design. Google omits some low-volume queries for privacy. Search-term insights may group this hidden traffic into categories/"other queries" without exposing the exact queries.
   - https://support.google.com/google-ads/answer/2472708
   - https://support.google.com/google-ads/answer/11386930

2. Conversion data can lag the original ad interaction. Recent rows can therefore make CPA/ROAS look worse before delayed conversions arrive.
   - https://support.google.com/google-ads/answer/9347141
   - https://support.google.com/google-ads/answer/9347065

3. `Conversions` and `All conversions` are not equivalent. Primary conversion actions generally populate `Conversions` and are used for bidding; secondary actions generally appear in `All conversions` for observation unless used through a custom goal.
   - https://support.google.com/google-ads/faq/10286469
   - https://support.google.com/google-ads/answer/3419678

4. Google Ads API v26 `search_term_view` reports search-term performance at ad-group level and exposes cost, conversions, conversion value, all conversions, and all-conversion value. It does not cover Performance Max search terms in this resource.
   - https://developers.google.com/google-ads/api/fields/v26/search_term_view

5. Search-term targeting status can be ADDED, ADDED_EXCLUDED, EXCLUDED, NONE, UNKNOWN, or UNSPECIFIED. It indicates whether the term is currently targeted or excluded.
   - https://developers.google.com/google-ads/api/reference/rpc/v26/SearchTermTargetingStatusEnum

## Accuracy decisions

### D1 — Never extrapolate hidden-query waste

The engine may report:

- visible search-term spend,
- unobserved search spend,
- potentially avoidable **observed** spend.

It must not estimate hidden-query waste by dividing by coverage or multiplying observed waste by an inverse coverage factor.

### D2 — Conversion maturity is configurable

There is no universal conversion-lag duration that is correct for every advertiser. Phase 4 uses an explicit `AccuracyPolicy.conversion_lag_days` supplied by account/operator policy. Spend inside that window cannot enter the potentially-avoidable amount.

### D3 — Conversion absence is never standalone waste proof

A zero-conversion query cannot become waste simply because it has cost. Phase 3 must first establish a business-truth-backed semantic mismatch.

### D4 — Any mature conversion signal blocks automatic financial classification for now

Until we validate individual Google conversion actions against the Business Truth outcome model, any non-zero mature `conversions`, `conversions_value`, `all_conversions`, or `all_conversions_value` sends the finding to REVIEW_REQUIRED.

This deliberately favors precision over recall.

### D5 — Current exclusions are not new recovery opportunities

If Google reports a term as currently EXCLUDED or ADDED_EXCLUDED, historical mismatch spend can be retained for audit/history, but Phase 4 labels it ALREADY_ADDRESSED rather than claiming a new recoverable amount.

### D6 — Scope must remain exact

Evidence is aggregated only inside one:

`customer × campaign × ad group × normalized query × network`

Cross-campaign/ad-group/network aggregation is rejected because later negative-keyword scope and campaign intent can differ.

### D7 — Duplicate source rows are fatal

The engine creates a stable identity from immutable report dimensions. Duplicate identities are rejected instead of summed, preventing accidental double counting from retries/import duplication.

### D8 — Financial claim wording

Allowed V1 wording:

> Potentially avoidable observed spend identified.

Not allowed:

> Exact wasted spend.

> Total account waste.

> Guaranteed savings.

> Hidden search-term waste estimate.

### D9 — Phase 4 does not create negative keywords

Financial evidence and action safety remain separate. Phase 5 must independently evaluate negative keyword text, match type, scope, blast radius, existing exclusions, and collision with valuable queries before any action is proposed.
