from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.google_ads.sync import (
    CustomerProfile,
    FileSyncStore,
    GoogleAdsSyncEngine,
    RetryPolicy,
    SyncChunk,
    call_with_retry,
    is_retryable_google_ads_error,
    split_date_window,
)


CUSTOMER = "1234567890"


def term(day: date, *, currency: str = "USD", customer: str = CUSTOMER):
    return SearchTermObservation(
        customer_id=customer,
        campaign_id="10",
        campaign_name="Search",
        ad_group_id="20",
        ad_group_name="Roof",
        search_term="roof replacement jobs",
        date=day,
        network="SEARCH",
        match_source="KEYWORD",
        search_term_match_type="BROAD",
        targeting_status="NONE",
        triggering_keyword="roof replacement",
        triggering_keyword_match_type="BROAD",
        impressions=10,
        clicks=1,
        cost_micros=1_000_000,
        conversions=Decimal("0"),
        conversions_value=Decimal("0"),
        all_conversions=Decimal("0"),
        all_conversions_value=Decimal("0"),
        currency_code=currency,
    )


def spend(day: date, *, currency: str = "USD", customer: str = CUSTOMER):
    return CampaignSpendObservation(
        customer_id=customer,
        campaign_id="10",
        campaign_name="Search",
        date=day,
        network="SEARCH",
        cost_micros=2_000_000,
        currency_code=currency,
    )


class FakeAdapter:
    def __init__(self):
        self.profile_calls = 0
        self.term_calls = 0
        self.spend_calls = 0
        self.inventory_calls = 0
        self.profile = CustomerProfile(
            customer_id=CUSTOMER,
            descriptive_name="Acme",
            currency_code="USD",
            time_zone="America/New_York",
            manager=False,
            status="ENABLED",
            test_account=False,
        )

    def get_customer_profile(self, customer_id):
        self.profile_calls += 1
        return self.profile

    def iter_search_terms(self, customer_id, start, end):
        self.term_calls += 1
        return iter([term(start)])

    def iter_campaign_network_spend(self, customer_id, start, end):
        self.spend_calls += 1
        return iter([spend(start)])

    def get_keyword_inventory(self, customer_id):
        self.inventory_calls += 1
        return (), ()


def test_split_date_window_is_gapless_and_inclusive():
    chunks = split_date_window(date(2026, 9, 1), date(2026, 9, 16), chunk_days=7)
    assert chunks == (
        SyncChunk(date(2026, 9, 1), date(2026, 9, 7)),
        SyncChunk(date(2026, 9, 8), date(2026, 9, 14)),
        SyncChunk(date(2026, 9, 15), date(2026, 9, 16)),
    )


def test_customer_profile_uses_account_timezone_for_today():
    profile = CustomerProfile(
        customer_id=CUSTOMER,
        descriptive_name="x",
        currency_code="USD",
        time_zone="America/Los_Angeles",
        manager=False,
        status="ENABLED",
        test_account=False,
    )
    # 00:30 UTC is still the previous calendar day in Los Angeles.
    assert profile.local_today(datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)) == date(2026, 10, 14)


def test_empty_chunk_can_be_committed_and_resumed(tmp_path: Path):
    profile = CustomerProfile(
        customer_id=CUSTOMER,
        descriptive_name="x",
        currency_code="USD",
        time_zone="UTC",
        manager=False,
        status="ENABLED",
        test_account=False,
    )
    store = FileSyncStore(tmp_path, profile=profile, start=date(2026, 9, 1), end=date(2026, 9, 1))
    chunk = SyncChunk(date(2026, 9, 1), date(2026, 9, 1))
    store.commit_chunk(chunk=chunk, search_terms=(), campaign_spend=())
    assert store.chunk_complete(chunk)


def test_sync_is_resumable_without_redownloading_completed_chunks(tmp_path: Path):
    adapter = FakeAdapter()
    engine = GoogleAdsSyncEngine(adapter, chunk_days=7, retry_policy=RetryPolicy(max_attempts=1))
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    first = engine.sync(
        customer_id=CUSTOMER,
        start=date(2026, 9, 1),
        end=date(2026, 9, 10),
        output_root=tmp_path,
        now=now,
        sleeper=lambda _: None,
    )
    assert first.downloaded_chunks == 2
    assert adapter.term_calls == 2

    second = engine.sync(
        customer_id=CUSTOMER,
        start=date(2026, 9, 1),
        end=date(2026, 9, 10),
        output_root=tmp_path,
        now=now,
        sleeper=lambda _: None,
    )
    assert second.downloaded_chunks == 0
    assert second.skipped_completed_chunks == 2
    assert adapter.term_calls == 2


def test_sync_rejects_future_date_in_customer_timezone(tmp_path: Path):
    adapter = FakeAdapter()
    engine = GoogleAdsSyncEngine(adapter, retry_policy=RetryPolicy(max_attempts=1))
    with pytest.raises(ValueError, match="future"):
        engine.sync(
            customer_id=CUSTOMER,
            start=date(2026, 10, 15),
            end=date(2026, 10, 15),
            output_root=tmp_path,
            now=datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc),
            sleeper=lambda _: None,
        )


def test_sync_rejects_currency_drift(tmp_path: Path):
    adapter = FakeAdapter()
    adapter.iter_search_terms = lambda customer_id, start, end: iter([term(start, currency="EUR")])
    engine = GoogleAdsSyncEngine(adapter, retry_policy=RetryPolicy(max_attempts=1))
    with pytest.raises(ValueError, match="currency"):
        engine.sync(
            customer_id=CUSTOMER,
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            output_root=tmp_path,
            now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
            sleeper=lambda _: None,
        )


def test_call_with_retry_only_retries_classifier_approved_errors():
    calls = 0
    sleeps = []

    def fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return 42

    result = call_with_retry(
        fn,
        policy=RetryPolicy(max_attempts=4, initial_delay_seconds=1, jitter_fraction=0),
        retryable=lambda exc: str(exc) == "temporary",
        sleeper=sleeps.append,
    )
    assert result == 42
    assert calls == 3
    assert sleeps == [1, 2]


def test_retry_classifier_does_not_retry_generic_quota_exhaustion():
    class Code:
        name = "RESOURCE_EXHAUSTED"

    class Rpc:
        def code(self):
            return Code()

    class Exc(Exception):
        error = Rpc()
        failure = None

    assert is_retryable_google_ads_error(Exc()) is False


def test_sync_rejects_missing_campaign_spend_denominator(tmp_path: Path):
    adapter = FakeAdapter()
    adapter.iter_campaign_network_spend = lambda customer_id, start, end: iter(())
    engine = GoogleAdsSyncEngine(adapter, retry_policy=RetryPolicy(max_attempts=1))
    with pytest.raises(ValueError, match="denominator missing"):
        engine.sync(
            customer_id=CUSTOMER,
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            output_root=tmp_path,
            now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
            sleeper=lambda _: None,
        )


def test_sync_rejects_visible_spend_above_campaign_denominator(tmp_path: Path):
    adapter = FakeAdapter()
    adapter.iter_campaign_network_spend = lambda customer_id, start, end: iter([
        CampaignSpendObservation(
            customer_id=CUSTOMER,
            campaign_id="10",
            campaign_name="Search",
            date=start,
            network="SEARCH",
            cost_micros=500_000,
            currency_code="USD",
        )
    ])
    engine = GoogleAdsSyncEngine(adapter, retry_policy=RetryPolicy(max_attempts=1))
    with pytest.raises(ValueError, match="exceeds comparable"):
        engine.sync(
            customer_id=CUSTOMER,
            start=date(2026, 9, 1),
            end=date(2026, 9, 1),
            output_root=tmp_path,
            now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
            sleeper=lambda _: None,
        )
