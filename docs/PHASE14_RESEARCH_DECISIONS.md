# Phase 14 Research Decisions — Production Semantic Router & Drift Guard

Date: 2026-10-15

## Goal

Promoting a semantic model must not mean "the AI is now always trusted." Production must
remain selective, version-pinned, observable, reversible, and fail closed.

## External findings that shaped the design

1. NIST AI 800-4 (March 2026) identifies post-deployment monitoring as necessary for
   detecting reliability degradation, unforeseen outputs, changing conditions, and drift.
   Source: https://www.nist.gov/news-events/news/2026/03/new-report-challenges-monitoring-deployed-ai-systems

2. NIST AI RMF Measure 2.4 recommends monitoring deployed AI functionality/behavior and
   comparing production metrics with pre-deployment metrics.
   Source: https://airc.nist.gov/airmf-resources/playbook/measure/

3. Gemini model documentation distinguishes stable, preview, latest, and experimental model
   strings. Google states that most production applications should use a specific stable model;
   `latest` aliases can be hot-swapped.
   Source: https://ai.google.dev/gemini-api/docs/models

4. Gemini exposes model metadata/version information and structured output, but application
   code must still enforce its own release identity and semantic safety constraints.
   Sources:
   - https://ai.google.dev/api/models
   - https://ai.google.dev/gemini-api/docs/structured-output

## Product decisions

### Fail closed

Released AI is used only if all of the following hold:

- an applicable release is active;
- the release is not tripped;
- configured model/thinking/prompt/contract exactly match the promoted release;
- provider/model identity matches at runtime;
- provider-reported model revision exactly matches the evaluated revision;
- the candidate reports a language explicitly approved by that release;
- declared confidence is present and at or above the calibration-selected threshold;
- deterministic BusinessFitEvaluator does not return UNKNOWN.

Any failure returns the conservative Phase-3 baseline. Financial and mutation phases never
receive an unqualified candidate result.

### Provider revision mismatch is a safety event

A runtime provider revision different from the promoted revision trips the release. Automatic
fallback is allowed; automatic migration to the new provider revision is not.

### Release trips are terminal

A tripped release cannot be reset to healthy or activated again. A corrected model/prompt/policy
must become a new immutable release and pass evaluation again.

### Exact-scope activation

At most one release may be active for an exact scope. An account-specific release is more
specific than a tenant-wide release and is preferred when both exist.

### Production evidence is append-only

Every routed semantic decision stores the baseline result, candidate result (if called), final
route, release fingerprint, provider revision, confidence, and source scope identity. This
allows later reconstruction of exactly which semantic result fed financial evidence.

### Drift requires blinded reviewed truth

Operational logs alone cannot establish semantic correctness. Drift evaluation uses production
decisions that have later been linked to blinded, release-eligible human gold labels.

The drift policy separates:

- minimum reviewed support;
- minimum actionable-irrelevant support;
- observed unsafe false exclusions;
- Wilson upper uncertainty bound.

Insufficient evidence does not become a "healthy" claim and does not auto-trip solely because
the sample is small. Once sufficient evidence exists, policy breaches trip the release.

### Shadow and production remain separate

Phase-13 shadow predictions stay in shadow tables with `production_effect_allowed=false`.
Phase-14 production decisions have a separate schema and are created only through the release
router.
