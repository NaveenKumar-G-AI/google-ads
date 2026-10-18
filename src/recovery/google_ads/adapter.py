from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Iterator, Protocol

from recovery.domain import CampaignSpendObservation, SearchTermObservation
from recovery.waste_intelligence import CampaignPerformanceSegmentObservation, UserLocationObservation
from recovery.monitoring import GoogleChangeEventObservation
from recovery.monitoring import CampaignHealthObservation
from recovery.measurement_integrity import (
    ConversionActionObservation, CustomerConversionGoalObservation, CampaignConversionGoalObservation,
    CampaignGoalConfigObservation, ConversionLagObservation,
)
from recovery.negative_keywords import (
    ExistingNegativeKeyword,
    NegativeMatchType,
    NegativeScope,
    PositiveKeyword,
)
from recovery.google_ads.gaql import (
    account_negative_keyword_list_query,
    ad_group_negative_keywords_query,
    applied_ad_group_negative_query,
    campaign_negative_keywords_query,
    campaign_network_spend_query,
    campaign_performance_segments_query,
    campaign_health_query,
    user_location_performance_query,
    conversion_action_inventory_query,
    customer_conversion_goals_query,
    campaign_conversion_goals_query,
    campaign_goal_configs_query,
    conversion_lag_distribution_query,
    geo_target_constants_query,
    customer_profile_query,
    positive_keywords_query,
    search_term_query,
    change_events_query,
    shared_negative_keywords_query,
    shared_negative_sets_query,
)

GOOGLE_ADS_API_VERSION = "v26"


class AdsSearchService(Protocol):
    def search_stream(
        self, *, customer_id: str, query: str, timeout: float | None = None
    ) -> Iterable[Any]: ...


@dataclass(slots=True)
class GoogleAdsV26Adapter:
    """Version-isolated adapter around the official Google Ads Python client.

    Domain/scoring code never imports Google's generated protobuf types. API version
    upgrades should be localized to this package instead of leaking into the evidence
    and money logic.
    """

    client: Any
    stream_timeout_seconds: float = 600.0

    @classmethod
    def from_google_ads_client(cls, client: Any) -> "GoogleAdsV26Adapter":
        return cls(client=client)

    def _service(self) -> AdsSearchService:
        return self.client.get_service(
            "GoogleAdsService", version=GOOGLE_ADS_API_VERSION
        )

    def _rows(self, customer_id: str, query: str) -> Iterator[Any]:
        stream = self._service().search_stream(
            customer_id=customer_id,
            query=query,
            timeout=self.stream_timeout_seconds,
        )
        for batch in stream:
            for row in batch.results:
                yield row

    @staticmethod
    def _enum_name(value: Any) -> str:
        # Proto-plus enum values stringify differently across generated versions.
        # Prefer the enum name when available; fallback to stable string conversion.
        name = getattr(value, "name", None)
        if name:
            return str(name)
        text = str(value)
        return text.rsplit(".", 1)[-1]

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        # Decimal(str(...)) avoids binary-float artifacts from protobuf doubles.
        return Decimal(str(value))

    @staticmethod
    def _negative_match_type(value: Any) -> NegativeMatchType:
        name = GoogleAdsV26Adapter._enum_name(value).upper()
        try:
            return NegativeMatchType[name]
        except KeyError as exc:
            raise ValueError(f"unsupported/unknown negative keyword match type: {name}") from exc

    def list_accessible_customer_ids(self) -> tuple[str, ...]:
        """List directly accessible customers for the current credential only."""

        service = self.client.get_service(
            "CustomerService", version=GOOGLE_ADS_API_VERSION
        )
        response = service.list_accessible_customers()
        ids: list[str] = []
        for resource_name in response.resource_names:
            parts = str(resource_name).split("/")
            if len(parts) != 2 or parts[0] != "customers" or not parts[1].isdigit():
                raise ValueError(f"unexpected customer resource name: {resource_name}")
            ids.append(parts[1])
        return tuple(sorted(set(ids)))

    def get_customer_profile(self, customer_id: str) -> Any:
        """Return immutable account metadata used to bind a sync to account truth."""

        # Local import avoids a circular module dependency: sync owns the domain model,
        # while adapter owns Google-protobuf translation.
        from .sync import CustomerProfile

        rows = list(self._rows(customer_id, customer_profile_query()))
        if len(rows) != 1:
            raise ValueError(f"expected exactly one customer row, got {len(rows)}")
        customer = rows[0].customer
        return CustomerProfile(
            customer_id=str(customer.id),
            descriptive_name=str(customer.descriptive_name or ""),
            currency_code=str(customer.currency_code),
            time_zone=str(customer.time_zone),
            manager=bool(customer.manager),
            status=self._enum_name(customer.status),
            test_account=bool(customer.test_account),
        )

    def iter_change_events(self, customer_id: str, start: datetime, end: datetime) -> Iterator[GoogleChangeEventObservation]:
        for row in self._rows(customer_id, change_events_query(start, end)):
            ev=row.change_event
            raw=str(ev.change_date_time).replace("Z","+00:00")
            dt=datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt=dt.replace(tzinfo=timezone.utc)
            fields=tuple(str(x) for x in getattr(ev.changed_fields,"paths",()) or ())
            yield GoogleChangeEventObservation(
                change_date_time=dt.astimezone(timezone.utc),
                change_resource_type=self._enum_name(ev.change_resource_type),
                change_resource_name=str(ev.change_resource_name),
                client_type=self._enum_name(ev.client_type),
                user_email=str(ev.user_email) if getattr(ev,"user_email",None) else None,
                changed_fields=fields,
            )

    def iter_search_terms(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[SearchTermObservation]:
        query = search_term_query(start, end)
        for row in self._rows(customer_id, query):
            kw_text = getattr(row.segments.keyword.info, "text", "") or None
            kw_match = getattr(row.segments.keyword.info, "match_type", None)
            yield SearchTermObservation(
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                campaign_name=str(row.campaign.name),
                ad_group_id=str(row.ad_group.id),
                ad_group_name=str(row.ad_group.name),
                search_term=str(row.search_term_view.search_term),
                date=date.fromisoformat(str(row.segments.date)),
                network=self._enum_name(row.segments.ad_network_type),
                match_source=self._enum_name(row.segments.search_term_match_source),
                search_term_match_type=self._enum_name(
                    row.segments.search_term_match_type
                ),
                targeting_status=self._enum_name(
                    row.segments.search_term_targeting_status
                ),
                triggering_keyword=kw_text,
                triggering_keyword_match_type=(
                    self._enum_name(kw_match) if kw_text is not None else None
                ),
                impressions=int(row.metrics.impressions),
                clicks=int(row.metrics.clicks),
                cost_micros=int(row.metrics.cost_micros),
                conversions=self._decimal(row.metrics.conversions),
                conversions_value=self._decimal(row.metrics.conversions_value),
                all_conversions=self._decimal(row.metrics.all_conversions),
                all_conversions_value=self._decimal(
                    row.metrics.all_conversions_value
                ),
                currency_code=str(row.customer.currency_code),
            )

    def iter_campaign_network_spend(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[CampaignSpendObservation]:
        query = campaign_network_spend_query(start, end)
        for row in self._rows(customer_id, query):
            yield CampaignSpendObservation(
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                campaign_name=str(row.campaign.name),
                date=date.fromisoformat(str(row.segments.date)),
                network=self._enum_name(row.segments.ad_network_type),
                cost_micros=int(row.metrics.cost_micros),
                currency_code=str(row.customer.currency_code),
            )

    def iter_campaign_health(self, customer_id: str) -> Iterator[CampaignHealthObservation]:
        for row in self._rows(customer_id, campaign_health_query()):
            reasons = tuple(self._enum_name(x) for x in row.campaign.primary_status_reasons)
            yield CampaignHealthObservation(
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                campaign_name=str(row.campaign.name),
                advertising_channel_type=self._enum_name(row.campaign.advertising_channel_type),
                status=self._enum_name(row.campaign.status),
                primary_status=self._enum_name(row.campaign.primary_status),
                primary_status_reasons=reasons,
            )

    def iter_campaign_performance_segments(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[CampaignPerformanceSegmentObservation]:
        for row in self._rows(customer_id, campaign_performance_segments_query(start, end)):
            yield CampaignPerformanceSegmentObservation(
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                campaign_name=str(row.campaign.name),
                date=date.fromisoformat(str(row.segments.date)),
                network=self._enum_name(row.segments.ad_network_type),
                device=self._enum_name(row.segments.device),
                day_of_week=self._enum_name(row.segments.day_of_week),
                hour=int(row.segments.hour),
                impressions=int(row.metrics.impressions),
                clicks=int(row.metrics.clicks),
                cost_micros=int(row.metrics.cost_micros),
                conversions=self._decimal(row.metrics.conversions),
                conversions_value=self._decimal(row.metrics.conversions_value),
                all_conversions=self._decimal(row.metrics.all_conversions),
                all_conversions_value=self._decimal(row.metrics.all_conversions_value),
                currency_code=str(row.customer.currency_code),
            )

    def _geo_metadata(self, customer_id: str, resources: tuple[str, ...]) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for offset in range(0, len(resources), 500):
            chunk=resources[offset:offset+500]
            if not chunk:
                continue
            for row in self._rows(customer_id, geo_target_constants_query(chunk)):
                g=row.geo_target_constant
                result[str(g.resource_name)] = {
                    "name": str(g.name),
                    "canonical_name": str(g.canonical_name),
                    "country_code": str(g.country_code),
                    "target_type": str(g.target_type),
                }
        return result

    def iter_user_location_performance(
        self, customer_id: str, start: date, end: date
    ) -> Iterator[UserLocationObservation]:
        raw=list(self._rows(customer_id, user_location_performance_query(start,end)))
        resources: list[str] = []
        for row in raw:
            resource=str(getattr(row.segments, "geo_target_most_specific_location", "") or "")
            if not resource:
                resource=f"geoTargetConstants/{int(row.user_location_view.country_criterion_id)}"
            resources.append(resource)
        metadata=self._geo_metadata(customer_id, tuple(dict.fromkeys(resources))) if resources else {}
        for row,resource in zip(raw,resources):
            meta=metadata.get(resource,{})
            yield UserLocationObservation(
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                campaign_name=str(row.campaign.name),
                date=date.fromisoformat(str(row.segments.date)),
                network=self._enum_name(row.segments.ad_network_type),
                targeting_location=bool(row.user_location_view.targeting_location),
                country_criterion_id=str(row.user_location_view.country_criterion_id),
                location_resource=resource,
                location_name=meta.get("name"),
                canonical_name=meta.get("canonical_name"),
                country_code=meta.get("country_code"),
                target_type=meta.get("target_type"),
                impressions=int(row.metrics.impressions),
                clicks=int(row.metrics.clicks),
                cost_micros=int(row.metrics.cost_micros),
                conversions=self._decimal(row.metrics.conversions),
                conversions_value=self._decimal(row.metrics.conversions_value),
                all_conversions=self._decimal(row.metrics.all_conversions),
                all_conversions_value=self._decimal(row.metrics.all_conversions_value),
                currency_code=str(row.customer.currency_code),
            )

    @staticmethod
    def _date_or_none(value: Any) -> date | None:
        text=str(value or "").strip()
        if not text:
            return None
        return date.fromisoformat(text[:10])

    def iter_conversion_actions(self, customer_id: str) -> Iterator[ConversionActionObservation]:
        for row in self._rows(customer_id, conversion_action_inventory_query()):
            a=row.conversion_action
            value=getattr(a, "value_settings", None)
            attribution=getattr(a, "attribution_model_settings", None)
            yield ConversionActionObservation(
                customer_id=str(row.customer.id),
                resource_name=str(a.resource_name),
                action_id=str(a.id),
                name=str(a.name),
                status=self._enum_name(a.status),
                action_type=self._enum_name(a.type),
                category=self._enum_name(a.category),
                origin=self._enum_name(a.origin),
                owner_customer=(str(a.owner_customer) if getattr(a,"owner_customer","") else None),
                primary_for_goal=bool(a.primary_for_goal),
                counting_type=self._enum_name(a.counting_type),
                click_through_lookback_days=int(a.click_through_lookback_window_days),
                view_through_lookback_days=int(a.view_through_lookback_window_days),
                attribution_model=self._enum_name(getattr(attribution,"attribution_model", "UNSPECIFIED")),
                data_driven_model_status=self._enum_name(getattr(attribution,"data_driven_model_status", "UNSPECIFIED")),
                default_value=self._decimal(getattr(value,"default_value",0) or 0),
                default_currency_code=(str(getattr(value,"default_currency_code","") or "") or None),
                always_use_default_value=bool(getattr(value,"always_use_default_value",False)),
                all_conversions=self._decimal(row.metrics.all_conversions),
                all_conversions_value=self._decimal(row.metrics.all_conversions_value),
                last_conversion_date=self._date_or_none(getattr(row.metrics,"conversion_last_conversion_date",None)),
                last_received_request_at=(str(getattr(row.metrics,"conversion_last_received_request_date_time","") or "") or None),
            )

    def iter_customer_conversion_goals(self, customer_id: str) -> Iterator[CustomerConversionGoalObservation]:
        for row in self._rows(customer_id, customer_conversion_goals_query()):
            g=row.customer_conversion_goal
            yield CustomerConversionGoalObservation(
                customer_id=str(row.customer.id), resource_name=str(g.resource_name),
                category=self._enum_name(g.category), origin=self._enum_name(g.origin),
                biddable=bool(g.biddable),
            )

    def iter_campaign_conversion_goals(self, customer_id: str) -> Iterator[CampaignConversionGoalObservation]:
        for row in self._rows(customer_id, campaign_conversion_goals_query()):
            g=row.campaign_conversion_goal
            yield CampaignConversionGoalObservation(
                customer_id=str(row.customer.id), campaign_id=str(row.campaign.id), campaign_name=str(row.campaign.name),
                campaign_status=self._enum_name(row.campaign.status), resource_name=str(g.resource_name),
                category=self._enum_name(g.category), origin=self._enum_name(g.origin), biddable=bool(g.biddable),
            )

    def iter_campaign_goal_configs(self, customer_id: str) -> Iterator[CampaignGoalConfigObservation]:
        for row in self._rows(customer_id, campaign_goal_configs_query()):
            g=row.conversion_goal_campaign_config
            custom=str(getattr(g,"custom_conversion_goal","") or "") or None
            yield CampaignGoalConfigObservation(
                customer_id=str(row.customer.id), campaign_id=str(row.campaign.id), campaign_name=str(row.campaign.name),
                campaign_status=self._enum_name(row.campaign.status), resource_name=str(g.resource_name),
                goal_config_level=self._enum_name(g.goal_config_level), custom_conversion_goal=custom,
            )

    def iter_conversion_lag(self, customer_id: str, start: date, end: date) -> Iterator[ConversionLagObservation]:
        for row in self._rows(customer_id, conversion_lag_distribution_query(start,end)):
            resource=str(getattr(row.segments,"conversion_action","") or "")
            if not resource:
                continue
            yield ConversionLagObservation(
                customer_id=str(row.customer.id), conversion_action_resource=resource,
                conversion_action_name=str(getattr(row.segments,"conversion_action_name","") or resource),
                category=self._enum_name(getattr(row.segments,"conversion_action_category","UNSPECIFIED")),
                lag_bucket=self._enum_name(getattr(row.segments,"conversion_lag_bucket","UNSPECIFIED")),
                conversions=self._decimal(row.metrics.conversions), all_conversions=self._decimal(row.metrics.all_conversions),
                conversions_value=self._decimal(row.metrics.conversions_value),
                all_conversions_value=self._decimal(row.metrics.all_conversions_value),
            )

    def iter_positive_keywords(self, customer_id: str) -> Iterator[PositiveKeyword]:
        for row in self._rows(customer_id, positive_keywords_query()):
            yield PositiveKeyword(
                text=str(row.ad_group_criterion.keyword.text),
                match_type=self._enum_name(row.ad_group_criterion.keyword.match_type),
                customer_id=str(row.customer.id),
                campaign_id=str(row.campaign.id),
                ad_group_id=str(row.ad_group.id),
                status=self._enum_name(row.ad_group_criterion.status),
                resource_name=str(row.ad_group_criterion.resource_name),
            )

    def iter_ad_group_negatives(
        self, customer_id: str
    ) -> Iterator[ExistingNegativeKeyword]:
        for row in self._rows(customer_id, ad_group_negative_keywords_query()):
            yield ExistingNegativeKeyword(
                text=str(row.ad_group_criterion.keyword.text),
                match_type=self._negative_match_type(
                    row.ad_group_criterion.keyword.match_type
                ),
                scope=NegativeScope.AD_GROUP,
                customer_id=customer_id,
                campaign_id=str(row.campaign.id),
                ad_group_id=str(row.ad_group.id),
                resource_name=str(row.ad_group_criterion.resource_name),
            )

    def iter_campaign_negatives(
        self, customer_id: str
    ) -> Iterator[ExistingNegativeKeyword]:
        for row in self._rows(customer_id, campaign_negative_keywords_query()):
            yield ExistingNegativeKeyword(
                text=str(row.campaign_criterion.keyword.text),
                match_type=self._negative_match_type(
                    row.campaign_criterion.keyword.match_type
                ),
                scope=NegativeScope.CAMPAIGN,
                customer_id=customer_id,
                campaign_id=str(row.campaign.id),
                resource_name=str(row.campaign_criterion.resource_name),
            )

    @staticmethod
    def _shared_set_id_from_resource(resource_name: str) -> str:
        parts = resource_name.split("/")
        if len(parts) < 4 or parts[-2] != "sharedSets" or not parts[-1].isdigit():
            raise ValueError(f"unexpected shared set resource name: {resource_name}")
        return parts[-1]

    def _shared_and_account_negatives(
        self, customer_id: str
    ) -> tuple[ExistingNegativeKeyword, ...]:
        attachments: dict[str, set[str]] = {}
        for row in self._rows(customer_id, shared_negative_sets_query()):
            shared_set_id = str(row.shared_set.id)
            attachments.setdefault(shared_set_id, set()).add(str(row.campaign.id))

        account_set_ids: set[str] = set()
        for row in self._rows(customer_id, account_negative_keyword_list_query()):
            resource = str(
                row.customer_negative_criterion.negative_keyword_list.shared_set
            )
            account_set_ids.add(self._shared_set_id_from_resource(resource))

        results: list[ExistingNegativeKeyword] = []
        for row in self._rows(customer_id, shared_negative_keywords_query()):
            set_id = str(row.shared_set.id)
            set_type = self._enum_name(row.shared_set.type).upper()
            if set_type == "ACCOUNT_LEVEL_NEGATIVE_KEYWORDS":
                # Only effective when linked through CustomerNegativeCriterion.
                if set_id not in account_set_ids:
                    continue
                results.append(
                    ExistingNegativeKeyword(
                        text=str(row.shared_criterion.keyword.text),
                        match_type=self._negative_match_type(
                            row.shared_criterion.keyword.match_type
                        ),
                        scope=NegativeScope.ACCOUNT,
                        customer_id=customer_id,
                        resource_name=str(row.shared_criterion.resource_name),
                    )
                )
            elif set_type == "NEGATIVE_KEYWORDS":
                campaigns = tuple(sorted(attachments.get(set_id, set())))
                if not campaigns:
                    # An unattached shared list does not currently affect delivery.
                    continue
                results.append(
                    ExistingNegativeKeyword(
                        text=str(row.shared_criterion.keyword.text),
                        match_type=self._negative_match_type(
                            row.shared_criterion.keyword.match_type
                        ),
                        scope=NegativeScope.SHARED_LIST,
                        customer_id=customer_id,
                        shared_set_id=set_id,
                        applied_campaign_ids=campaigns,
                        resource_name=str(row.shared_criterion.resource_name),
                    )
                )
            else:
                raise ValueError(f"unexpected negative shared set type: {set_type}")
        return tuple(results)

    def get_keyword_inventory(
        self, customer_id: str
    ) -> tuple[tuple[PositiveKeyword, ...], tuple[ExistingNegativeKeyword, ...]]:
        positives = tuple(
            sorted(
                self.iter_positive_keywords(customer_id),
                key=lambda x: (x.campaign_id, x.ad_group_id, x.text.casefold()),
            )
        )
        negatives = tuple(
            sorted(
                (
                    *self.iter_ad_group_negatives(customer_id),
                    *self.iter_campaign_negatives(customer_id),
                    *self._shared_and_account_negatives(customer_id),
                ),
                key=lambda x: (
                    x.scope.value,
                    x.campaign_id or "",
                    x.ad_group_id or "",
                    x.shared_set_id or "",
                    x.text.casefold(),
                ),
            )
        )
        return positives, negatives

    def find_applied_ad_group_negative(
        self,
        *,
        customer_id: str,
        ad_group_id: str,
        resource_name: str,
    ) -> ExistingNegativeKeyword | None:
        for row in self._rows(
            customer_id, applied_ad_group_negative_query(customer_id, ad_group_id)
        ):
            if str(row.ad_group_criterion.resource_name) != resource_name:
                continue
            return ExistingNegativeKeyword(
                text=str(row.ad_group_criterion.keyword.text),
                match_type=self._negative_match_type(
                    row.ad_group_criterion.keyword.match_type
                ),
                scope=NegativeScope.AD_GROUP,
                customer_id=customer_id,
                campaign_id=str(row.campaign.id),
                ad_group_id=str(row.ad_group.id),
                resource_name=resource_name,
            )
        return None
