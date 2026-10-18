# Epic 5 — Measurement Integrity Contract

Version: 0.24.0

## Purpose

Recovery OS must decide whether Google Ads conversion evidence is trustworthy enough to participate in economic claims. Epic 5 therefore treats measurement as its own evidence domain rather than assuming every Google Ads conversion is a valid business outcome.

## Canonical confidence states

Recovery OS does **not** expose a synthetic 0–100 measurement score.

The only canonical confidence states are:

- `strong`
- `constrained`
- `blocked`
- `unknown`

Every non-strong state must be accompanied by explicit evidence issues. The backend, not the browser, decides the state.

## Claim gates

The measurement assessment exposes two explicit gates:

- `conversion_dependent_claims_allowed`
- `recovery_verification_allowed`

These gates apply to claims that depend on conversion evidence. A Business Truth mismatch can still be described independently when its proof does not depend on conversions. Measurement weakness must not erase unrelated evidence, and unrelated evidence must not be used to hide measurement weakness.

## Business Truth mapping

Google Ads configuration is not business truth.

Each Google conversion action can be explicitly mapped to an outcome in the latest confirmed Business Truth snapshot. The mapping is version-bound and append-only.

A mapping may establish that a conversion action is:

- a confirmed primary business outcome,
- a supporting signal,
- not a business outcome,
- or unmapped/unknown.

A primary Google conversion action that is unmapped constrains measurement confidence. A primary action explicitly mapped to `not_a_business_outcome` blocks conversion-dependent claims until the conflict is corrected.

Mappings from an older Business Truth version never silently qualify the current version.

## Provider evidence

Each completed sync can commit an immutable measurement snapshot containing:

- conversion-action inventory,
- customer conversion goals,
- campaign conversion goals,
- campaign goal configuration,
- observed conversion-lag distribution.

The measurement snapshot must commit before the sync is marked complete. An older completed sync that predates Epic 5 does not get a manufactured measurement assessment; it remains unknown until a compatible sync is completed.

## Google primary / secondary semantics

The implementation uses `conversion_action.primary_for_goal` as the current provider signal for primary versus secondary behavior. It deliberately does not use the deprecated include-in-conversions flag.

Customer and campaign goal configuration are persisted separately because campaign-level configuration and custom goals can alter which conversion goals are used for optimization.

Therefore:

- `primary_for_goal=true` alone is not treated as proof that the conversion is a valid business outcome;
- `primary_for_goal=false` alone is not treated as proof that the conversion is irrelevant;
- account and campaign goal context must remain visible.

## Conversion lag

Google Ads lag buckets are persisted as observed evidence. Recovery OS compares the largest observed lag bucket containing conversions with the account's configured conversion maturity window.

If observed conversion lag extends materially beyond the configured maturity policy, zero-conversion reasoning is constrained. Recovery OS does not silently interpret recent zero-conversion traffic as mature failure.

## Enhanced conversions

Epic 5 explicitly does **not** infer enhanced-conversion enablement or health from the ConversionAction resource.

The API/UI returns an explicit non-observable state instead of fabricating one. Future enhanced-conversion health must come from a provider diagnostic or an appropriately scoped tag/measurement integration.

## Offline conversion uploads

Epic 5 diagnoses measurement configuration; it does not add a new offline-conversion writer. Google's 2026 platform direction moves new offline/enhanced-conversion-for-leads ingestion toward the Data Manager API, so any future writer must be researched and implemented against the current supported ingestion path at that time.

## Financial truth boundary

Measurement Confidence does not create a financial amount. It only determines whether conversion-dependent reasoning can be trusted.

It must never generate:

- waste from zero conversions alone,
- recovery from a conversion increase alone,
- revenue from Google conversion values without confirmed business mapping.

## Permissions

- Viewer: read measurement evidence.
- Analyst: read measurement evidence.
- Admin / Owner: read and manage Business Truth mappings.

Mapping permissions are enforced by the backend. UI visibility is not the security boundary.

## Immutability

Provider measurement snapshots are append-only. Business Truth mappings are append-only events. Historical provider evidence or mapping events are never edited in place.

## Production acceptance

Epic 5 is considered implemented only when:

1. provider evidence is stored immutably and tenant-isolated,
2. confidence is deterministic and explainable,
3. stale Business Truth mappings are rejected from current confidence,
4. primary/secondary provider semantics are represented with goal context,
5. lag evidence can constrain maturity-dependent reasoning,
6. enhanced conversions are not fabricated,
7. API permissions enforce mapping authority,
8. the customer UI shows exact issues and claim gates,
9. cumulative regression tests and frontend contracts pass.
