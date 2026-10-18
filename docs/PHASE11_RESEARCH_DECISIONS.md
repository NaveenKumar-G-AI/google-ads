# Phase 11 — AI Semantic Evaluation & Calibration: Research Decisions

## Goal
No language model may influence Phase 4 financial evidence merely because it can return valid JSON. It must first pass a versioned, reproducible evaluation gate on search-query meaning under the exact Business Truth snapshot.

## Key decisions

1. **Selective prediction / abstention is a feature.** `UNKNOWN` and `CONDITIONAL` are safe outcomes. Coverage is secondary to avoiding false exclusions.
2. **False exclusion is the primary safety error.** Predicting `IRRELEVANT` when the adjudicated gold label is anything else is tracked separately from ordinary classification error.
3. **Gold labels are Business-Truth-specific.** The same query may be correct for one advertiser and wrong for another. Dataset identity therefore includes raw query + Business Truth fingerprint.
4. **Exclusion-critical gold requires multiple reviewers.** A gold `IRRELEVANT` label cannot be created from a single reviewer.
5. **Calibration and test splits are isolated by query + Business Truth identity.** The holdout test set cannot be used to tune confidence thresholds.
6. **Confidence is not trusted by default.** We measure Brier score and expected calibration error. A model claiming `0.99` must empirically behave like a high-confidence predictor before that value is useful.
7. **Zero observed errors on a tiny set proves little.** The gate includes a Wilson upper confidence bound for unsafe error rate and minimum support requirements.
8. **Multilingual performance is sliced, not averaged away.** Release policy can require minimum support and zero false exclusions for specific deployment languages.
9. **No spend/performance features enter semantic evaluation.** Phase 3's separation remains intact.
10. **Model-provider integration is intentionally not part of this phase.** Phase 11 builds the evaluation harness first. A provider/model is eligible only after producing outputs against this harness.

## External references used
- Google Ads Help: search terms report and negative keyword ideas; negative exact is the default when adding from the report and negatives differ from positive match behavior.
- Google Ads Help: low-volume queries can be omitted from the search terms report for privacy.
- Guo et al. (2017), *On Calibration of Modern Neural Networks*: model confidence can be miscalibrated; calibration must be measured rather than assumed.
- Geifman & El-Yaniv (2017/2019): selective classification formalizes the risk/coverage trade-off and reject option.
- NIST AI RMF Measure / 2026 TEVV guidance: document test sets, uncertainty, limitations, representative conditions, repeatable evaluation, and post-deployment monitoring.

## Release-policy note
The default numerical thresholds in code are **product risk-policy choices**, not universal scientific constants. They are deliberately conservative for V1 and must be versioned if changed. They must never be optimized on the holdout test set.

## Google Ads-specific safety implication
Google recommends using the Search Terms report to identify irrelevant searches and notes that adding a negative from the report defaults to negative exact. Google also warns that negative keywords differ from positive matching and do not broadly inherit close variants. Therefore semantic evaluation is asymmetric: a false `IRRELEVANT` can suppress legitimate demand and is treated as a higher-severity error than an abstention or missed exclusion.

Google also omits some low-volume queries from the Search Terms report for privacy, so evaluation claims apply only to semantic decisions on observable queries; Phase 4 continues to forbid extrapolating hidden-query waste.
