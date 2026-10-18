# Phase 11 Semantic Evaluation Contract

A candidate semantic model is not production-eligible unless all of the following are true:

- Evaluation uses an immutable labelled dataset tied to Business Truth fingerprints.
- Calibration and test examples do not share the same query + Business Truth identity.
- All exclusion-critical gold labels have at least two reviewers/adjudication.
- Candidate predictions exist for every test example; missing cases are failures, not silently ignored.
- Any reference to an unknown offer/non-offer ID remains rejected by the Phase 3 strict parser/evaluator.
- `IRRELEVANT` on a non-irrelevant gold case is an **unsafe false exclusion**.
- Release policy checks minimum total support, minimum negative-action support, false-exclusion count, irrelevant precision, uncertainty bound, confidence calibration, and required language slices.
- Confidence thresholds are selected using the calibration split only.
- The holdout test split is run once for release assessment; it is not a tuning loop.
- Production monitoring must later compare real abstention/error slices against this pre-deployment baseline.

The evaluation harness does not mutate Google Ads and does not use clicks, spend, conversions, CPA, ROAS, or recovery estimates.

## Confidence semantics
`declared_confidence` is provider-neutral. It may come from a model score, an ensemble, or a separately trained/calibrated confidence estimator. The product does **not** assume a self-reported LLM confidence is trustworthy. If a candidate cannot supply a score that calibrates on held-out data, it cannot use confidence to unlock `IRRELEVANT` actions.

The selected threshold is learned from the **calibration split only**. On the holdout test split, only predicted `IRRELEVANT` cases at or above that threshold count as action-eligible for the release safety metrics. Lower-confidence negative predictions are treated as abstentions for action purposes.

## Challenge slices
Before production release, the deployment policy should explicitly require the challenge slices relevant to the product, for example:
- ambiguous query
- mixed intent
- Business Truth counterfactual (same query, different advertiser truth)
- explicit non-offer
- denied intent
- missing/unknown business policy
- competitor/brand query
- employment
- free/DIY/training/rental/second-hand where applicable
- typo/noisy query
- multilingual/code-switched query for every supported market

A high global score cannot compensate for an unsafe required slice.
