# Research decisions — 2026-10-15

## API baseline

- Target Google Ads API **v26**, released 2026-10-14.
- Python official client: `google-ads==34.0.0` or newer compatible release supporting v26.
- Keep Google protobuf/GAQL details inside a versioned adapter; domain/scoring code remains provider-independent.

## Scope

V1 analyzes **Search campaigns only**. `search_term_view` is appropriate for search-term-level metrics and does not include Performance Max. PMax is explicitly deferred.

## Search-term incompleteness

Google omits some low-volume queries from the search terms report for privacy. Therefore we calculate a coverage ratio from observed search-term cost divided by comparable Search/Search Partners campaign cost and never present an uncovered account-wide number as exact.

## Conversion lag

Google documents conversion lag. There is no universal advertiser-independent safe delay, so `conversion_lag_days` is configurable. Recent rows cannot be used as standalone performance-failure evidence.

## Negative keyword safety

Negative keywords behave differently from positive keywords and do not automatically match all semantic variants. Match type and scope must be explicit. Existing direct, shared-set and account-level exclusions must be loaded before proposing a new negative.

## Currency

Use `customer.currency_code`; store money as integer `cost_micros` and convert with Decimal only for presentation/calculation requiring units.

## Search network alignment

Coverage compares the same networks (`SEARCH`, `SEARCH_PARTNERS`) over the same date range to reduce denominator mismatch.
