# Epic 8 — Research Decisions

Version: 0.27.0

## 1. Campaign serving evidence

Google Ads exposes `campaign.primary_status` and `campaign.primary_status_reasons` as output-only diagnostics explaining why a campaign is not serving or not serving optimally. Google notes that changes to the campaign and related entities may take time to appear in this status.

Decision: use these fields for provider-observed serving incidents; preserve the exact status/reasons and label them diagnostic rather than causal.

## 2. ChangeEvent is supplementary

Google ChangeEvent reports granular account changes within a recent history window and can take up to several minutes to appear.

Decision: do not use ChangeEvent as immediate proof that a just-submitted mutation succeeded. Recovery OS continues to use mutation response + exact resource identity + provider read-back for immediate mutation safety. ChangeEvent can support later audit/reconciliation.

## 3. Landing-page reporting is not an HTTP monitor

Google `landing_page_view` provides performance/page-experience metrics such as mobile-friendly-click percentage and speed score. It does not provide a general HTTP response-code truth signal.

Decision: do not label a destination as 404/500/broken from Google landing-page performance metrics alone. A future landing-page availability monitor must make a direct controlled HTTP check with redirect/TLS/timeout semantics and an explicit scanning policy.

## 4. Statistical anomalies require explicit policy

Decision: no opaque anomaly score. Spend/conversion monitors are opt-in and expose both thresholds and minimum-evidence gates.

## 5. Conversion-drop maturity

Decision: conversion-drop monitoring reads Measurement Integrity and excludes observations within the account's conversion-lag maturity policy. If conversion-dependent claims are blocked, the conversion-drop monitor does not manufacture an incident from immature/untrusted conversion data.

## 6. Query recurrence deferred

Decision: do not infer recurrence merely because query volume increases after an intervention. Exact recurrence requires a link between a previously applied case/action and later re-observation of the same protected query/intent under a valid comparison window. Until that evidence path exists, the monitor remains unavailable.

## 7. Alert economics

Decision: monitoring incidents are operational evidence. Their spend metrics are context only and are not independent financial buckets. Waste Intelligence and Recovery Center remain the only financial claim surfaces governed by their own evidence contracts.
