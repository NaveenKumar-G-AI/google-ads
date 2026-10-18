from __future__ import annotations

import hashlib
from typing import Sequence

from recovery.domain import CampaignSpendObservation, SearchTermObservation, summarize_coverage
from recovery.evidence import observation_identity_sha256
from recovery.negative_keywords import ExistingNegativeKeyword, PositiveKeyword
from recovery.search_intent import normalize_query

from .canonical import canonical_json_text, canonical_payload, payload_sha256


def campaign_spend_identity_sha256(row: CampaignSpendObservation) -> str:
    parts = (
        row.customer_id,
        row.campaign_id,
        row.date.isoformat(),
        row.network.upper(),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _stable_rows(rows: Sequence[object], identity_fn) -> list[dict]:
    prepared = []
    for row in rows:
        payload = canonical_payload(row)
        prepared.append(
            {
                "identity": identity_fn(row),
                "payload_sha256": payload_sha256(row),
                "payload": payload,
            }
        )
    prepared.sort(key=lambda x: (x["identity"], x["payload_sha256"], canonical_json_text(x["payload"])))
    return prepared


def stable_chunk_payload(
    *,
    api_version: str,
    sync_schema_version: int,
    chunk_start: str,
    chunk_end: str,
    search_terms: Sequence[SearchTermObservation],
    campaign_spend: Sequence[CampaignSpendObservation],
    currency_code: str,
) -> dict:
    """Order-independent chunk envelope used as the database idempotency checksum."""

    if search_terms or campaign_spend:
        coverage = summarize_coverage(search_terms, campaign_spend)
        if coverage.currency_code.upper() != currency_code.upper():
            raise ValueError("chunk currency does not match account currency")
        visible = coverage.visible_search_term_cost_micros
        comparable = coverage.eligible_search_campaign_cost_micros
    else:
        visible = comparable = 0
    if visible > comparable:
        raise ValueError("visible search-term spend exceeds comparable campaign spend")

    return {
        "api_version": api_version,
        "sync_schema_version": sync_schema_version,
        "chunk": {"start": chunk_start, "end": chunk_end},
        "currency_code": currency_code.upper(),
        "search_terms": _stable_rows(search_terms, observation_identity_sha256),
        "campaign_spend": _stable_rows(campaign_spend, campaign_spend_identity_sha256),
        "coverage": {
            "visible_search_term_cost_micros": visible,
            "comparable_campaign_cost_micros": comparable,
        },
    }


def stable_inventory_payload(
    *,
    api_version: str,
    sync_schema_version: int,
    positive_keywords: Sequence[PositiveKeyword],
    existing_negatives: Sequence[ExistingNegativeKeyword],
) -> dict:
    def ordered(values: Sequence[object]) -> list[dict]:
        payloads = [canonical_payload(v) for v in values]
        return sorted(payloads, key=canonical_json_text)

    return {
        "api_version": api_version,
        "sync_schema_version": sync_schema_version,
        "positive_keywords": ordered(positive_keywords),
        "existing_negatives": ordered(existing_negatives),
    }
