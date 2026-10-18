# Phase 13 Shadow / Release Contract

## Shadow invariant

```text
candidate semantic output
!= financial finding
!= negative keyword proposal
!= approved Google mutation
```

A shadow prediction's `production_effect_allowed` is always false in Python and PostgreSQL.

## Gold-label invariant

Release-quality gold must be:

```text
raw query + exact Business Truth
→ blinded human review 1
→ blinded human review 2
→ agreement OR blinded adjudicator
→ immutable gold-case version
```

Candidate prediction is not an input to the gold-label decision.

## Dataset invariant

A dataset snapshot references exact immutable gold-case version IDs. A later correction does
not rewrite an old benchmark; it creates a new dataset fingerprint.

## Release invariant

A semantic release may be created only from a Phase-11 gate-passing evaluation with:

- non-null provider model revision
- non-null calibration-selected confidence threshold
- exact candidate contract identity
- exact dataset/report/policy fingerprints
- explicit approved language slices that were gated

## Runtime invariant

Phase 13 does not change `ConservativeAnalysisJobRunner`. Until a later production-routing
phase deliberately activates an evaluated release, financial evidence and negative actions
remain driven by the conservative semantic baseline.

## Revocation invariant

Revocation is terminal. A revoked release cannot be activated again. A replacement requires a
new immutable release definition and a new evaluation chain.
