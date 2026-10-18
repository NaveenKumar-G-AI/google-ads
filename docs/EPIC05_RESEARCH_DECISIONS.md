# Epic 5 — Research Decisions

Version: 0.24.0

This document records the provider-level facts that shaped the implementation. These are implementation constraints, not marketing claims.

## 1. Primary versus secondary conversion actions

Current Google Ads API semantics expose `ConversionAction.primary_for_goal`. This is the field Recovery OS uses to represent the provider's primary/secondary designation. The older include-in-conversions field is deprecated and is intentionally not used by Epic 5.

Decision: store `primary_for_goal` exactly as provider evidence and never equate it with confirmed business value.

## 2. Customer conversion goals

Google Ads groups account-default conversion-goal configuration by category and origin and exposes whether a goal is biddable.

Decision: store customer goal configuration separately from the conversion-action resource. It is configuration evidence, not Business Truth.

## 3. Campaign conversion goals and overrides

Campaigns can use campaign-specific goal configuration rather than only customer defaults, and custom goal configuration can also alter optimization behavior.

Decision: persist campaign conversion goals and campaign goal-config level. Measurement diagnostics must not assume all campaigns inherit the account default.

## 4. Conversion lag

Google Ads exposes `segments.conversion_lag_bucket` for lagged-conversion reporting.

Decision: persist observed lag buckets and compare them with Recovery OS's configured conversion maturity window. Lag is a maturity constraint, not a reason to invent future conversions.

## 5. Enhanced conversions

The ConversionAction resource does not provide a reliable universal field from which Recovery OS can infer that enhanced conversions are enabled and healthy.

Decision: show `not_observable_from_conversion_action_resource`. Do not infer a positive or negative status. Add future provider/tag diagnostics only when an authoritative source is available.

## 6. Offline conversion diagnostics and 2026 ingestion direction

Google exposes offline conversion upload diagnostics, but new offline/enhanced-conversion-for-leads ingestion is moving toward the Data Manager API in 2026 and legacy Google Ads API upload access is being restricted.

Decision: Epic 5 remains diagnostic/read-oriented. It does not introduce a new conversion upload mutation path. A future ingestion feature must target the then-current supported API and its authentication/consent requirements.

## 7. Business Truth mapping

Google Ads knows how a conversion action is configured for optimization; it does not know whether the user's business considers that event a primary business outcome.

Decision: add an explicit, version-bound mapping between provider conversion actions and confirmed Business Truth outcomes. Recovery OS financial/recovery claims may depend on this mapping.

## 8. Confidence representation

A numeric tracking score would require arbitrary weighting and can create false precision.

Decision: use categorical, explainable states (`strong`, `constrained`, `blocked`, `unknown`) with exact issues and explicit downstream gates.

## 9. Data retention / provenance

Provider measurement evidence must remain reproducible against the exact completed sync that produced it.

Decision: immutable measurement snapshots and append-only mapping events with PostgreSQL RLS and tenant scoping.
