from datetime import date, datetime, timezone

from recovery.google_ads.sync import CustomerProfile, GoogleAdsSyncEngine, SyncChunk


class Adapter:
    def get_customer_profile(self, customer_id):
        return CustomerProfile(customer_id, "Demo", "USD", "UTC", False, "ENABLED", False)

    def iter_search_terms(self, customer_id, start, end):
        return iter(())

    def iter_campaign_network_spend(self, customer_id, start, end):
        return iter(())

    def get_keyword_inventory(self, customer_id):
        return ((), ())


class Store:
    location = "postgres://sync-runs/demo"
    def __init__(self):
        self.committed = []
        self.inventory = False
    def chunk_complete(self, chunk):
        return False
    def commit_chunk(self, *, chunk, search_terms, campaign_spend):
        self.committed.append(chunk)
    def commit_inventory(self, *, positive_keywords, existing_negatives):
        self.inventory = True


def test_sync_engine_can_use_database_store_without_file_output(tmp_path):
    store = Store()
    calls = []
    def factory(*, profile, start, end):
        calls.append((profile.customer_id, start, end))
        return store
    engine = GoogleAdsSyncEngine(Adapter(), chunk_days=7)
    result = engine.sync(
        customer_id="1234567890",
        start=date(2026, 10, 1),
        end=date(2026, 10, 8),
        store_factory=factory,
        now=datetime(2026, 10, 15, tzinfo=timezone.utc),
    )
    assert calls == [("1234567890", date(2026, 10, 1), date(2026, 10, 8))]
    assert len(store.committed) == 2
    assert store.inventory is True
    assert result.output_directory == "postgres://sync-runs/demo"
