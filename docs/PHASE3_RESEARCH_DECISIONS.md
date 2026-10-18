# Phase 3 — Search Intent Intelligence: Research Decisions

Research date: 2026-10-15

## Objective

Interpret what a search query means and compare that meaning with operator-confirmed
business truth. Phase 3 does **not** judge financial waste and does **not** create a
negative keyword action.

## Official-source findings that constrain the implementation

1. Google describes the search terms report as the actual searches that triggered ads
   and explicitly recommends it as a source of negative-keyword ideas when terms are
   not relevant to the products/services sold.
   - https://support.google.com/google-ads/answer/7102466
   - https://support.google.com/google-ads/answer/13738234

2. Negative keyword behavior differs from positive matching. Google warns that
   negative keywords do not match all variants and that match type must be chosen so
   valid searches are not blocked. Therefore semantic irrelevance and the later
   negative-keyword *action* are separate decisions.
   - https://support.google.com/google-ads/answer/9701952
   - https://support.google.com/google-ads/answer/7102466

3. Positive keywords can match close variants, paraphrases, and same-intent searches.
   Consequently the triggering keyword text cannot be used as a substitute for
   understanding the actual search term.
   - https://support.google.com/google-ads/answer/9342105

4. Search Terms Insights can aggregate all search terms, including terms not exposed
   individually for privacy reasons, into intent/product-service categories. This is
   valuable future evidence but it is not a license to invent the hidden queries.
   Phase 3 therefore evaluates only the query it actually receives.
   - https://support.google.com/google-ads/answer/11386930

5. `search_term_view` reports Search-term metrics at ad-group level and currently does
   not include Performance Max. V1 continues to be Search-campaign-only.
   - https://developers.google.com/google-ads/api/fields/v26/search_term_view

## Accuracy decisions

### 1. Meaning is isolated from performance
The semantic interpreter is forbidden from seeing spend, clicks, conversions, CPA,
ROAS, or revenue. A costly zero-conversion query must not be labelled irrelevant just
because it performed poorly.

### 2. Model confidence is not statistical probability
A semantic model's `0.97` confidence is recorded as interpreter confidence only. It is
not presented as a calibrated 97% probability unless we later calibrate it empirically.

### 3. UNKNOWN is first-class
Ambiguous, unresolved, low-confidence, malformed, or under-specified interpretations
produce UNKNOWN rather than forced relevance/irrelevance.

### 4. Business IDs are closed-world references
A future AI may only reference stable `offer_id` / `exclusion_id` values supplied in
business context. Hallucinated IDs are rejected before evaluation.

### 5. Business policy remains deterministic
The model interprets query meaning. It does not decide whether employment/free/DIY/etc.
is commercially good or bad. `BusinessTruthSnapshot` owns that decision.

### 6. Mixed intents are not collapsed
If a query has material intents that resolve to conflicting, conditional, or missing
business policies, Phase 3 returns CONDITIONAL/UNKNOWN instead of choosing whichever
label has the highest score.

### 7. Raw query is immutable evidence
Unicode NFKC + whitespace/case normalization is used only for comparison. We retain the
raw query and do not stem, translate, strip accents, or remove punctuation in the
canonical evidence record.

### 8. Phase 3 never writes negatives
Even a semantic result of IRRELEVANT means only "eligible to become an exclusion
candidate." Phase 4 must add observation maturity, spend/evidence, repeat patterns, and
other safeguards; Phase 5 will handle negative keyword scope/match/blast-radius safety.

## Current interpreter

`ConservativeLexicalInterpreter` exists solely as a deterministic executable baseline
and test harness. It intentionally refuses to guess most queries. It is **not** being
presented as the production AI classifier.

A production semantic model will plug into the same `SemanticAssessment` contract later,
after provider/model selection and an evaluation dataset are established.
