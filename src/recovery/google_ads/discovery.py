from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter import GOOGLE_ADS_API_VERSION, GoogleAdsV26Adapter
from .auth import normalize_customer_id
from .gaql import customer_descendants_query


@dataclass(frozen=True, slots=True)
class DiscoveredGoogleAdsAccount:
    customer_id: str
    descriptive_name: str
    currency_code: str
    time_zone: str
    manager: bool
    account_status: str
    test_account: bool
    direct_access: bool
    login_customer_id: str | None
    hierarchy_level: int


class GoogleAdsAccountDiscovery:
    """Discover selectable accounts for a user's OAuth credential.

    `ListAccessibleCustomers` returns directly accessible roots. For manager roots we
    query `customer_client`, which Google documents as including descendants. We keep
    the root manager ID as login_customer_id for descendants rather than asking the
    customer to know or type it manually.
    """

    def __init__(self, client: Any, *, max_accounts: int = 5000) -> None:
        if max_accounts < 1:
            raise ValueError("max_accounts must be positive")
        self.client = client
        self.adapter = GoogleAdsV26Adapter.from_google_ads_client(client)
        self.max_accounts = max_accounts

    @staticmethod
    def _enum_name(value: Any) -> str:
        return GoogleAdsV26Adapter._enum_name(value)

    def discover(self) -> tuple[DiscoveredGoogleAdsAccount, ...]:
        direct_ids = self.adapter.list_accessible_customer_ids()
        found: dict[str, DiscoveredGoogleAdsAccount] = {}

        for seed in direct_ids:
            seed = normalize_customer_id(seed)
            profile = self.adapter.get_customer_profile(seed)
            found[seed] = DiscoveredGoogleAdsAccount(
                customer_id=seed,
                descriptive_name=profile.descriptive_name,
                currency_code=profile.currency_code,
                time_zone=profile.time_zone,
                manager=profile.manager,
                account_status=profile.status,
                test_account=profile.test_account,
                direct_access=True,
                login_customer_id=None,
                hierarchy_level=0,
            )
            if len(found) > self.max_accounts:
                raise RuntimeError("Google Ads account discovery exceeded configured account limit")
            if not profile.manager:
                continue

            service = self.client.get_service("GoogleAdsService", version=GOOGLE_ADS_API_VERSION)
            stream = service.search_stream(customer_id=seed, query=customer_descendants_query(), timeout=120.0)
            for batch in stream:
                for row in batch.results:
                    cc = row.customer_client
                    cid = normalize_customer_id(str(cc.id))
                    level = int(cc.level)
                    # Level 0 repeats the manager itself and must remain direct-access.
                    if cid == seed:
                        continue
                    candidate = DiscoveredGoogleAdsAccount(
                        customer_id=cid,
                        descriptive_name=str(cc.descriptive_name or ""),
                        currency_code=str(cc.currency_code),
                        time_zone=str(cc.time_zone),
                        manager=bool(cc.manager),
                        account_status=self._enum_name(cc.status),
                        test_account=bool(getattr(cc, "test_account", False)),
                        direct_access=False,
                        login_customer_id=seed,
                        hierarchy_level=level,
                    )
                    existing = found.get(cid)
                    # Direct access wins; otherwise retain the shortest known manager path.
                    if existing is None or (not existing.direct_access and level < existing.hierarchy_level):
                        found[cid] = candidate
                    if len(found) > self.max_accounts:
                        raise RuntimeError("Google Ads account discovery exceeded configured account limit")

        return tuple(sorted(found.values(), key=lambda x: (x.manager, x.descriptive_name.casefold(), x.customer_id)))
