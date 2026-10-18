# Accuracy Contract — V1

This product must optimize for **truthfulness of the output**, not number of findings.

## What V1 may claim

- It may report observed Google Ads spend exactly from `metrics.cost_micros` after conversion from integer micros.
- It may report the account currency from `customer.currency_code`.
- It may identify a specific observed search term as semantically irrelevant only after the advertiser's business context is confirmed.
- It may label a monetary amount as **potentially avoidable observed spend** only when the underlying observed terms are individually included in the finding.

## What V1 must NOT claim

- `0 conversions == wasted spend`.
- Search-term report data represents 100% of account searches.
- A low-volume omitted query can be reconstructed or guessed.
- A negative keyword is safe merely because an LLM suggested it.
- An account-level 'waste' number is exact when search-term coverage is incomplete.
- Recent zero-conversion traffic is mature evidence before conversion lag is considered.
- Performance Max search terms are part of the initial Search-only engine.

## Required confidence dimensions

Every future finding must carry independent evidence for:

1. **Data coverage** — visible search-term spend vs comparable Search/Search Partners campaign spend.
2. **Data maturity** — whether enough time has elapsed for conversion lag policy.
3. **Business-context confidence** — confirmed services, products, locations, exclusions and special intents such as hiring/support.
4. **Semantic confidence** — model/rule confidence that the query intent conflicts with the confirmed business context.
5. **Action risk** — the blast radius of a proposed negative keyword and match type.
6. **Existing exclusion state** — direct, shared-list and account-level negatives already in effect.

## Money handling

All Google Ads spend is stored as **integer micros**. Never use binary floating-point for spend arithmetic.

## Coverage wording

The UI should prefer:

> "Potentially avoidable spend found in the search terms Google exposed"

not:

> "Your exact wasted spend"

until later evidence supports a stronger claim.

## Mutation policy

V1 is read-only by default. A future mutation layer must require explicit approval and preview the exact scope/match type before applying exclusions.

## Phase 4 — Financial Evidence Contract

1. A poor-performing but semantically relevant query is never classified as waste by Phase 4.
2. A semantic mismatch must come from the Phase 3 Business Truth decision, not from cost or conversion performance.
3. Conversion-immature spend is excluded from the potentially-avoidable amount.
4. Any mature Google Ads conversion/count/value signal blocks automatic financial classification until conversion-action quality is validated.
5. Privacy-hidden/unobserved query spend is reported separately and is never extrapolated into waste.
6. Current EXCLUDED/ADDED_EXCLUDED terms are historical evidence, not new recovery opportunities.
7. Duplicate report observations and overlapping summary findings are rejected to prevent double counting.
8. Potentially avoidable spend is an observed-evidence claim, not a guarantee that every excluded click would have been prevented or that the same money will become profit.
9. Phase 4 never chooses a negative-keyword match type or applies an account mutation.
