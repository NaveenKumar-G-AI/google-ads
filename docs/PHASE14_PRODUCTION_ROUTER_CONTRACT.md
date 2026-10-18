# Phase 14 Production Semantic Router Contract

## Authority boundary

The semantic router may choose the semantic assessment supplied to Phase 4. It may not compute
waste, propose negatives, approve mutations, or write Google Ads changes.

## Candidate authorization gates

1. Active release exists.
2. Release safety state is healthy.
3. Local candidate configuration matches release identity.
4. Runtime provider/model/contract match release identity.
5. Runtime provider revision equals evaluated provider revision.
6. Candidate language is approved.
7. Declared confidence meets the evaluated threshold.
8. Deterministic business-fit evaluation does not abstain to UNKNOWN.

If any gate fails, final semantics come from `ConservativeLexicalInterpreter`.

## Hard release failures

These trip the release:

- local candidate contract/model/thinking/prompt differs from release;
- runtime provider/model/contract differs from release;
- provider-reported model revision differs from release.

A transient provider error only causes per-request baseline fallback; it does not by itself prove
the release is unsafe.

## Audit record

Every routed source scope persists:

- exact analysis run;
- source identity;
- raw query;
- Business Truth fingerprint;
- baseline assessment + fit;
- candidate assessment + fit when called;
- final selected assessment + fit;
- route source/fallback reason;
- release fingerprint/id;
- provider revision;
- declared confidence;
- immutable decision fingerprint.

## Drift contract

Only decisions linked to blinded release-eligible gold labels participate in semantic drift.
Unsafe false exclusion means:

`released AI routed IRRELEVANT` while `gold disposition != IRRELEVANT`.

Policy evaluation uses both observed errors and a Wilson upper uncertainty bound. A tripped
release is terminal.
