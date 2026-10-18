from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Sequence

from recovery.search_intent import normalize_query

_ALLOWED_SORTS = {"cost", "clicks", "impressions", "conversions", "query"}


def lexical_tokens(query: str) -> tuple[str, ...]:
    """Whitespace tokenization for lexical aggregation only.

    We intentionally preserve punctuation, accents and scripts exactly after the
    product's conservative NFKC/casefold normalization. Search Intelligence must not
    turn tokenization into an implicit semantic rewrite.
    """
    normalized = normalize_query(query)
    tokens = tuple(normalized.split())
    return tokens or (normalized,)


def make_ngrams(query: str, n: int) -> tuple[str, ...]:
    if n < 1 or n > 6:
        raise ValueError("n must be between 1 and 6")
    tokens = lexical_tokens(query)
    if len(tokens) < n:
        return ()
    return tuple(" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1))


@dataclass(frozen=True, slots=True)
class NGramSource:
    normalized_query: str
    impressions: int
    clicks: int
    cost_micros: int
    conversions: Decimal
    conversions_value: Decimal
    potentially_avoidable_observed_micros: int = 0


@dataclass(frozen=True, slots=True)
class NGramAggregate:
    ngram: str
    query_count: int
    impressions: int
    clicks: int
    cost_micros: int
    conversions: Decimal
    conversions_value: Decimal
    potentially_avoidable_observed_micros: int


def aggregate_ngrams(
    rows: Sequence[NGramSource], *, n: int, sort: str = "cost", limit: int = 100,
    without_conversions: bool = False,
) -> tuple[NGramAggregate, ...]:
    if sort not in _ALLOWED_SORTS - {"query"}:
        raise ValueError("unsupported n-gram sort")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if without_conversions and row.conversions != 0:
            continue
        for gram in dict.fromkeys(make_ngrams(row.normalized_query, n)):
            b=buckets.setdefault(gram, {
                "queries":set(), "impressions":0, "clicks":0, "cost_micros":0,
                "conversions":Decimal("0"), "conversions_value":Decimal("0"),
                "candidate":0,
            })
            b["queries"].add(row.normalized_query)
            b["impressions"] += row.impressions
            b["clicks"] += row.clicks
            b["cost_micros"] += row.cost_micros
            b["conversions"] += row.conversions
            b["conversions_value"] += row.conversions_value
            b["candidate"] += row.potentially_avoidable_observed_micros
    items=[NGramAggregate(
        ngram=k, query_count=len(v["queries"]), impressions=v["impressions"], clicks=v["clicks"],
        cost_micros=v["cost_micros"], conversions=v["conversions"],
        conversions_value=v["conversions_value"], potentially_avoidable_observed_micros=v["candidate"],
    ) for k,v in buckets.items()]
    key={
        "cost":lambda x:(x.cost_micros,x.query_count,x.ngram),
        "clicks":lambda x:(x.clicks,x.query_count,x.ngram),
        "impressions":lambda x:(x.impressions,x.query_count,x.ngram),
        "conversions":lambda x:(x.conversions,x.query_count,x.ngram),
    }[sort]
    return tuple(sorted(items,key=key,reverse=True)[:limit])


def validate_sort(sort: str) -> str:
    if sort not in _ALLOWED_SORTS:
        raise ValueError("unsupported search-term sort")
    return sort
