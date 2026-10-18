# Epic 3 — Search Intelligence Specification v1

Version: 0.22.0

## Product outcome

Search Intelligence turns persisted Google Ads search-demand evidence into an operating workbench. It is not a query-generation feature and it must not reconstruct privacy-hidden search terms.

V1 surfaces:
- Search Intelligence overview
- Search Term Explorer
- Search-term evidence detail
- business-fit / intent / network / match-source breakdowns
- 1–6 token n-gram explorer
- user saved views
- portfolio n-grams separated by currency
- visible-vs-unobserved coverage

## Evidence hierarchy

### Visible query evidence
Search-term rows come only from immutable `search_term_view` observations that were committed by completed sync chunks belonging to completed sync runs.

### Business-fit and semantic labels
Labels are the latest completed Recovery OS analysis context. They are diagnostic overlays; they do not rewrite the original query observation.

### Financial finding evidence
Financial findings are analysis-window-specific. They may appear only when the selected Search Intelligence date window exactly equals the source sync window of the latest completed analysis. For arbitrary custom windows the UI may display the latest semantic label, but financial finding status and money are suppressed.

### Coverage / privacy-hidden demand
Unobserved search spend is a coverage limitation. It is not a pool of assumed waste. V1 does not synthesize hidden queries from the campaign-spend denominator.

Google Search Terms Insights are a separate provider aggregate that can include search demand not individually exposed in the normal search-term report. Category/subcategory ingestion belongs to the later Search Themes capability and must remain category-level when added; it must never be converted into fabricated individual queries.

## Query normalization

The existing conservative query identity remains authoritative:
- Unicode NFKC
- trim/collapse whitespace
- casefold

The n-gram explorer then splits this normalized identity on whitespace only. It does not:
- stem
- remove punctuation
- strip accents
- translate
- merge synonyms
- apply AI rewriting

Semantic equivalence belongs to the semantic-analysis layer, not lexical n-grams.

## N-gram ranking

V1 supports 1–6 token contiguous n-grams.

Allowed sorts:
- cost
- clicks
- impressions
- conversions

Ratio sorts such as CTR, CPA, CVR and ROAS are intentionally absent because very low-volume phrases can dominate ratio ranking and mislead operators.

A repeated n-gram inside the same normalized query contributes that query's metrics once to that n-gram aggregate.

## Portfolio n-grams

Portfolio n-grams may span multiple advertiser accounts, but monetary metrics are grouped by `currency_code`. Recovery OS never adds INR and USD cost into one portfolio number.

## Match-source interpretation

The product stores the Google Ads match-source enum from the query observation. Current provider values can distinguish advertiser-provided keyword matching from sources such as AI Max, Dynamic Search Ads and Performance Max when those resources expose compatible data.

V1's `search_term_view` ingestion remains Search-campaign focused. Performance Max query ingestion is not falsely implied by this view.

## Saved views

Saved views are:
- user-scoped
- tenant-scoped
- either account-scoped or portfolio-scoped, never both
- RLS protected
- limited to 16KB of filter state

They store filter configuration only, not copied evidence or financial results.

## Failure / degraded states

Search Intelligence must explicitly handle:
- no completed visible query observations
- date range outside observed data
- only one of start/end supplied
- no completed analysis
- selected window differs from analysis window
- low/unknown coverage
- no semantic label
- conflicting semantic/business-fit labels across scopes
- provider dimensions absent/unknown
- no portfolio accounts

## V1.5 boundary

Not claimed complete in Epic 3 V1:
- Google Search Terms Insights category/subcategory ingestion (“Search Themes”)
- campaign-level Performance Max search-term insight product
- emerging-query anomaly detection
- positive keyword opportunity engine
- scheduled query alerts
- semantic cluster explorer beyond existing analysis labels

These require their own provider-truth and persistence contracts rather than being simulated from visible query rows.
