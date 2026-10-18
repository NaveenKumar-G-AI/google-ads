# Phase 13 Research Decisions — Shadow Mode + AI Release Registry

Date: 2026-10-15

## Objective

Allow a candidate semantic model to observe real imported Google Ads Search queries without
allowing that candidate to alter financial findings, negative-keyword proposals, or Google
Ads. Accumulate human-labelled evidence and promote only an exact, evaluated model contract.

## External grounding checked before implementation

### NIST AI RMF / TEVV

NIST's AI RMF Measure function says AI systems should be tested before deployment and
regularly in operation, with documented test sets, metrics, uncertainty and performance
assessment. It also notes that independent review can reduce internal bias/conflict of
interest.

- https://airc.nist.gov/airmf-resources/airmf/5-sec-core/
- https://airc.nist.gov/airmf-resources/playbook/measure/

NIST's 2026 AITE program specifically uses blind/sequestered evaluation data to mitigate
train/test contamination and support objective assessment. Our system is not NIST AITE, but
the principle directly motivates keeping release labels blind to the candidate prediction.

- https://www.nist.gov/news-events/news/2026/07/announcing-nists-artificial-intelligence-technology-evaluation-aite
- https://pages.nist.gov/ai-technology-evaluation/

### Google Ads search-term data boundary

Google Ads `search_term_view` remains an ad-group-level Search query view and does not include
Performance Max. Phase 13 therefore shadows the same Search-only semantic boundary used by
the earlier V1 analysis rather than expanding product scope during AI validation.

- https://developers.google.com/google-ads/api/fields/v25/search_term_view

## Decisions

### 1. Shadow predictions are structurally non-production

Shadow output is stored in dedicated `semantic_shadow_*` tables. It is not stored as a
`financial_finding`, `negative_keyword_proposal`, or Recovery Ledger entry.

The database column:

```text
production_effect_allowed = false
```

has a CHECK constraint forcing it to remain false.

### 2. Semantic SQL projection excludes performance

The shadow worker selects only:

- observation version ID
- customer/campaign/ad-group IDs
- network
- raw search term

It does not load cost, clicks, impressions, conversions, conversion value, CPA, ROAS, revenue,
or budget into the semantic runner.

### 3. Gold labels cannot be copied from model output

Human reviews used for release-quality gold labels must be marked as blinded to the candidate
prediction. Review rows deliberately have no foreign key to a candidate prediction.

At least two distinct reviewers are required. If they disagree, exactly one blinded
adjudicator decision is required.

### 4. Split assignment is stable and model-independent

Calibration/test assignment is HMAC-SHA256 over the case identity and a dataset split salt.
The model prediction and label are not part of the split decision. The raw salt does not need
to be stored with the release; a fingerprint can be persisted for provenance.

### 5. Corrected labels create versions

Gold evidence is append-only. A correction creates a new `semantic_gold_case_versions` row
that supersedes an older one. A released evaluation references an immutable dataset snapshot
containing exact gold-case version IDs.

### 6. Model name is not a release identity

A promotable release is pinned to:

- provider
- model alias
- provider-reported model revision
- thinking level
- prompt version
- stable candidate semantic-contract fingerprint
- structured-output semantic schema version
- calibration-selected confidence threshold
- release-policy fingerprint
- evaluation-report fingerprint
- dataset fingerprint
- explicitly approved language slices

Changing one of those requires a new evaluation/release.

### 7. Provider revision is mandatory for promotion

A candidate may run in shadow mode without a provider-reported revision, but it cannot be
promoted. This prevents a stable alias from silently representing an unrecorded model change.

### 8. Approved languages must have been explicit release-gate slices

A release cannot add a language after evaluation. Every approved language must have been
listed in `ReleasePolicy.required_language_slices`, have enough holdout support, and have no
thresholded unsafe false exclusion in the evaluated test report.

### 9. Release lifecycle is append-only

Release definition is immutable. Activation/deactivation/revocation are separate append-only
events. Revocation is terminal. PostgreSQL uses its own `recorded_at` ordering and advisory
locking so user-supplied timestamps cannot reorder state transitions.

### 10. Conservative production analysis remains unchanged

Phase-10 production analysis still uses `ConservativeLexicalInterpreter`. Phase 13 does not
wire the candidate into Phase 4/5. The candidate has to earn activation through evaluation
before any later phase can introduce a production semantic router.
