from __future__ import annotations

from types import SimpleNamespace

from recovery.google_ads.adapter import GoogleAdsV26Adapter
from recovery.negative_keywords import NegativeMatchType, NegativeScope


CUSTOMER = "1234567890"


def enum(name: str):
    return SimpleNamespace(name=name)


class Batch:
    def __init__(self, *rows):
        self.results = rows


class SearchService:
    def __init__(self, router):
        self.router = router
        self.calls = []

    def search_stream(self, *, customer_id, query, timeout=None):
        self.calls.append((customer_id, query, timeout))
        return [Batch(*self.router(query))]


class CustomerService:
    def list_accessible_customers(self):
        return SimpleNamespace(resource_names=[f"customers/{CUSTOMER}", "customers/9999999999"])


class FakeClient:
    def __init__(self, router):
        self.search = SearchService(router)
        self.customer = CustomerService()

    def get_service(self, name, version=None):
        assert version == "v26"
        if name == "GoogleAdsService":
            return self.search
        if name == "CustomerService":
            return self.customer
        raise AssertionError(name)


def test_adapter_profile_and_accessible_customers_use_v26_and_timeout():
    def router(query):
        if "FROM customer" in query and "customer_client" not in query:
            return [
                SimpleNamespace(
                    customer=SimpleNamespace(
                        id=int(CUSTOMER),
                        descriptive_name="Acme",
                        currency_code="USD",
                        time_zone="America/New_York",
                        manager=False,
                        status=enum("ENABLED"),
                        test_account=False,
                    )
                )
            ]
        return []

    client = FakeClient(router)
    adapter = GoogleAdsV26Adapter(client, stream_timeout_seconds=321)
    profile = adapter.get_customer_profile(CUSTOMER)
    assert profile.customer_id == CUSTOMER
    assert profile.currency_code == "USD"
    assert profile.time_zone == "America/New_York"
    assert client.search.calls[-1][2] == 321
    assert adapter.list_accessible_customer_ids() == (CUSTOMER, "9999999999")


def test_adapter_maps_effective_shared_and_account_negatives_only():
    def router(query):
        if "FROM campaign_shared_set" in query:
            return [
                SimpleNamespace(
                    campaign=SimpleNamespace(id=10),
                    shared_set=SimpleNamespace(id=200, type=enum("NEGATIVE_KEYWORDS")),
                    campaign_shared_set=SimpleNamespace(
                        resource_name=f"customers/{CUSTOMER}/campaignSharedSets/10~200",
                        shared_set=f"customers/{CUSTOMER}/sharedSets/200",
                    ),
                )
            ]
        if "FROM customer_negative_criterion" in query:
            return [
                SimpleNamespace(
                    customer_negative_criterion=SimpleNamespace(
                        resource_name=f"customers/{CUSTOMER}/customerNegativeCriteria/1",
                        type=enum("NEGATIVE_KEYWORD_LIST"),
                        negative_keyword_list=SimpleNamespace(
                            shared_set=f"customers/{CUSTOMER}/sharedSets/300"
                        ),
                    )
                )
            ]
        if "FROM shared_criterion" in query:
            return [
                SimpleNamespace(
                    shared_set=SimpleNamespace(
                        id=200, name="Campaign list", type=enum("NEGATIVE_KEYWORDS")
                    ),
                    shared_criterion=SimpleNamespace(
                        resource_name=f"customers/{CUSTOMER}/sharedCriteria/200~1",
                        keyword=SimpleNamespace(text="jobs", match_type=enum("BROAD")),
                    ),
                ),
                SimpleNamespace(
                    shared_set=SimpleNamespace(
                        id=201, name="Unattached", type=enum("NEGATIVE_KEYWORDS")
                    ),
                    shared_criterion=SimpleNamespace(
                        resource_name=f"customers/{CUSTOMER}/sharedCriteria/201~2",
                        keyword=SimpleNamespace(text="salary", match_type=enum("BROAD")),
                    ),
                ),
                SimpleNamespace(
                    shared_set=SimpleNamespace(
                        id=300,
                        name="Account list",
                        type=enum("ACCOUNT_LEVEL_NEGATIVE_KEYWORDS"),
                    ),
                    shared_criterion=SimpleNamespace(
                        resource_name=f"customers/{CUSTOMER}/sharedCriteria/300~3",
                        keyword=SimpleNamespace(text="free", match_type=enum("EXACT")),
                    ),
                ),
            ]
        return []

    adapter = GoogleAdsV26Adapter(FakeClient(router))
    negatives = adapter._shared_and_account_negatives(CUSTOMER)
    assert len(negatives) == 2
    campaign = next(x for x in negatives if x.scope is NegativeScope.SHARED_LIST)
    account = next(x for x in negatives if x.scope is NegativeScope.ACCOUNT)
    assert campaign.text == "jobs"
    assert campaign.applied_campaign_ids == ("10",)
    assert campaign.match_type is NegativeMatchType.BROAD
    assert account.text == "free"
    assert account.match_type is NegativeMatchType.EXACT
