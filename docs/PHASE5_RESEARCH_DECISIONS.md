# Phase 5 — Safe Negative Keyword Engine: Research Decisions

## Goal

Phase 5 does **not** optimize campaign performance. It converts a Phase-4
`POTENTIALLY_AVOIDABLE` finding into a narrowly scoped, human-reviewable Google Ads
negative-keyword proposal while preventing obvious collateral damage.

## Authoritative behavior incorporated

1. Google Ads Search negative keywords support broad, phrase, and exact match, but
   negative match types behave differently from positive match types.
2. Negative broad match blocks when all negative terms occur in the search, in any
   order. Negative phrase requires the terms in the same order. Negative exact blocks
   the exact phrase without extra words.
3. Negative keywords do not expand like positive close variants. Google advises adding
   needed singular/plural/synonym variants separately where appropriate.
4. In Google's Search Terms workflow, a selected query is added as **negative exact by
   default**. Phase 5 mirrors that conservative default.
5. Negative keywords can exist at ad-group, campaign, shared-list, and account scope.
   Broader scopes affect more traffic. V1-generated actions therefore use ad-group
   scope only.
6. Google warns that negative keywords can overlap positive keywords and prevent ads
   from serving. Phase 5 checks current positive keyword text before declaring a
   proposal low risk.
7. Keyword text is constrained by Google Ads criterion limits. V1 rejects proposals
   above 80 characters or 10 parsed words before mutation planning.
8. Google Ads mutate requests support `validate_only`. Every Phase-5 mutation plan
   requires a validate-only pass before a real mutate.

## Accuracy boundary

The local collision matcher is a conservative **risk screen**, not an emulator of
Google's auction/matching implementation. Google does not expose a deterministic local
API that reproduces every normalization/misspelling edge case. Punctuation is
normalized aggressively to prefer false-positive collision warnings over false safety.

Therefore:

- a detected collision is actionable safety evidence;
- the absence of a detected collision is **not proof** that no possible Google match
  could collide;
- phrase/broad negatives remain review-only in V1;
- no proposal is executed without human approval;
- no proposal is executed without Google `validate_only` validation.

## V1 generation policy

Automatic proposal generation is intentionally limited to:

- one observed normalized query;
- evidence marked `POTENTIALLY_AVOIDABLE` by Phase 4;
- a complete evidence snapshot for that action scope;
- negative **EXACT**;
- source **AD_GROUP** scope;
- no existing negative already covering the query;
- no protected-query collision;
- no positive-keyword collision.

Anything broader is a review task, not an automatic optimization.
