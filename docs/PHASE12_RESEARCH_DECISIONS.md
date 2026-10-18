# Phase 12 — Candidate AI Semantic Engine research decisions

## Purpose

Phase 12 adds a real model boundary without granting that model production authority.
The exact model + prompt + schema + thinking configuration remains a **candidate** until
Phase 11 evaluates it on a human-reviewed calibration/test corpus and the release gate passes.

## Current provider candidate

The first live transport uses Google's **Gemini Interactions API** with stable
`gemini-3.8-flash`. As of 2026-10-15 Google documents Gemini 3.8 Flash as GA/stable and
supporting structured outputs. `google-genai==2.31.0` is pinned for reproducibility.

## Accuracy boundaries

1. Financial/performance fields are forbidden from the semantic prompt.
2. Only confirmed active offers, explicit non-offers and confirmed intent policies are supplied.
3. No tools, web search, URL context, code execution, or account data are exposed to the model.
4. Search terms and business text are explicitly treated as untrusted data to resist prompt-injection-like strings.
5. Structured JSON is necessary but insufficient: all enum values, business IDs, query identity,
   duplicates and confidence ranges are revalidated by application code.
6. Model-produced interpreter names/versions are ignored. The application stamps those values.
7. Model-declared confidence is untrusted. Phase 11 calibrates it and chooses an actionable threshold.
8. Missing/ambiguous meaning is a valid outcome. The model is instructed to abstain rather than guess.
9. Batching uses opaque `item_id` values and requires exactly one result for every requested query.
10. Provider transient failures have bounded retries; semantic-contract failures do not retry.
11. Token usage is captured when available and can be capped per request. This is a cost/safety guard,
    not a semantic-quality shortcut.

## Why the Interactions API

Google's current migration guidance moves structured output to `response_format` in the
Interactions API and marks older `response_schema` fields as deprecated. This phase therefore
uses Interactions directly to reduce future migration risk.

## Why production still uses the conservative baseline

The Phase-10 worker is deliberately unchanged. Existence of an LLM adapter is not evidence of
quality. The candidate must first be run through the Phase-11 benchmark using the exact model,
prompt version, schema version and thinking setting. Only a passing release record may later
become selectable by production analysis jobs.
