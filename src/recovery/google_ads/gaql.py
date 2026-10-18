from __future__ import annotations

from datetime import date, datetime, timezone


ALLOWED_NETWORKS = ("SEARCH", "SEARCH_PARTNERS")


def _iso(d: date) -> str:
    if not isinstance(d, date):
        raise TypeError("date arguments must be datetime.date")
    return d.isoformat()


def _validate_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start date must be <= end date")


def search_term_query(start: date, end: date) -> str:
    """GAQL for daily Search campaign query observations.

    Daily segmentation is intentional: it lets the accuracy layer treat recent rows
    as conversion-immature instead of contaminating the historical evidence.
    """

    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  ad_group.id,
  ad_group.name,
  search_term_view.search_term,
  search_term_view.status,
  segments.date,
  segments.ad_network_type,
  segments.search_term_match_source,
  segments.search_term_match_type,
  segments.search_term_targeting_status,
  segments.keyword.info.text,
  segments.keyword.info.match_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.all_conversions,
  metrics.all_conversions_value
FROM search_term_view
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def campaign_network_spend_query(start: date, end: date) -> str:
    """Denominator query for search-term visibility/coverage calculation."""

    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  segments.date,
  segments.ad_network_type,
  metrics.cost_micros
FROM campaign
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def campaign_negative_keywords_query() -> str:
    return """
SELECT
  campaign.id,
  campaign_criterion.resource_name,
  campaign_criterion.negative,
  campaign_criterion.type,
  campaign_criterion.keyword.text,
  campaign_criterion.keyword.match_type
FROM campaign_criterion
WHERE campaign_criterion.negative = TRUE
  AND campaign_criterion.type = 'KEYWORD'
""".strip()


def ad_group_negative_keywords_query() -> str:
    return """
SELECT
  campaign.id,
  ad_group.id,
  ad_group_criterion.resource_name,
  ad_group_criterion.negative,
  ad_group_criterion.type,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type
FROM ad_group_criterion
WHERE ad_group_criterion.negative = TRUE
  AND ad_group_criterion.type = 'KEYWORD'
""".strip()


def shared_negative_sets_query() -> str:
    """Find shared negative keyword sets attached to campaigns.

    The set contents are fetched separately from `shared_criterion`; keeping this as
    a separate query makes attachment scope explicit and auditable.
    """

    return """
SELECT
  campaign.id,
  campaign_shared_set.resource_name,
  campaign_shared_set.shared_set,
  shared_set.id,
  shared_set.name,
  shared_set.type
FROM campaign_shared_set
WHERE shared_set.type = 'NEGATIVE_KEYWORDS'
""".strip()


def shared_negative_keywords_query() -> str:
    return """
SELECT
  shared_set.id,
  shared_set.name,
  shared_set.type,
  shared_criterion.resource_name,
  shared_criterion.keyword.text,
  shared_criterion.keyword.match_type
FROM shared_criterion
WHERE shared_set.type IN ('NEGATIVE_KEYWORDS', 'ACCOUNT_LEVEL_NEGATIVE_KEYWORDS')
""".strip()


def account_negative_keyword_list_query() -> str:
    return """
SELECT
  customer_negative_criterion.resource_name,
  customer_negative_criterion.type,
  customer_negative_criterion.negative_keyword_list.shared_set
FROM customer_negative_criterion
WHERE customer_negative_criterion.type = 'NEGATIVE_KEYWORD_LIST'
""".strip()


def positive_keywords_query() -> str:
    """Current positive Search keyword inventory for collision analysis."""

    return """
SELECT
  customer.id,
  campaign.id,
  ad_group.id,
  ad_group_criterion.resource_name,
  ad_group_criterion.status,
  ad_group_criterion.negative,
  ad_group_criterion.type,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = FALSE
  AND campaign.advertising_channel_type = 'SEARCH'
""".strip()


def experiment_recovery_query(experiment_id: int, start: date, end: date) -> str:
    """Direct experiment metrics used by Phase 6 causal verification.

    Google exposes treatment/control values plus point estimates, margins of error,
    and p-values on the experiment resource. The date filter is explicit so the
    statistical evidence and the ledger verification window cannot silently diverge.
    """

    if not isinstance(experiment_id, int) or experiment_id <= 0:
        raise ValueError("experiment_id must be a positive integer")
    _validate_window(start, end)
    return f"""
SELECT
  experiment.experiment_id,
  experiment.name,
  experiment.type,
  experiment.status,
  metrics.cost_micros,
  metrics.control_cost_micros,
  metrics.cost_micros_change_point_estimate,
  metrics.cost_micros_margin_of_error,
  metrics.cost_micros_p_value,
  metrics.conversions,
  metrics.control_conversions,
  metrics.conversions_absolute_change_point_estimate,
  metrics.conversions_absolute_change_margin_of_error,
  metrics.conversions_absolute_change_p_value,
  metrics.conversion_value_per_cost,
  metrics.control_conversion_value_per_cost,
  metrics.conversion_value_per_cost_change_point_estimate,
  metrics.conversion_value_per_cost_margin_of_error,
  metrics.conversion_value_per_cost_p_value
FROM experiment
WHERE experiment.experiment_id = {experiment_id}
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def applied_ad_group_negative_query(customer_id: str, ad_group_id: str) -> str:
    """Read back live ad-group negative criteria after mutation.

    IDs are restricted to decimal digits to keep GAQL construction non-ambiguous.
    The caller still matches the exact resource_name returned by the mutate response.
    """

    if not customer_id.isdigit() or not ad_group_id.isdigit():
        raise ValueError("customer_id and ad_group_id must contain digits only")
    return f"""
SELECT
  customer.id,
  campaign.id,
  ad_group.id,
  ad_group_criterion.resource_name,
  ad_group_criterion.negative,
  ad_group_criterion.type,
  ad_group_criterion.status,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type
FROM ad_group_criterion
WHERE ad_group.id = {ad_group_id}
  AND ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.negative = TRUE
""".strip()


def customer_profile_query() -> str:
    """Minimal immutable account metadata required for trustworthy syncs."""

    return """
SELECT
  customer.id,
  customer.descriptive_name,
  customer.currency_code,
  customer.time_zone,
  customer.manager,
  customer.status,
  customer.test_account
FROM customer
LIMIT 1
""".strip()


def customer_children_query() -> str:
    """Direct manager children only; recurse explicitly if a hierarchy is needed."""

    return """
SELECT
  customer_client.client_customer,
  customer_client.level,
  customer_client.manager,
  customer_client.descriptive_name,
  customer_client.currency_code,
  customer_client.time_zone,
  customer_client.id,
  customer_client.status
FROM customer_client
WHERE customer_client.level <= 1
  AND customer_client.status = 'ENABLED'
""".strip()


def customer_descendants_query() -> str:
    """All enabled descendants visible beneath a manager account.

    Google documents `customer_client` as a hierarchy resource whose rows include the
    queried manager (level 0) and descendants with increasing levels. Onboarding needs
    the complete hierarchy so agency users are never asked to know nested manager IDs.
    """

    return """
SELECT
  customer_client.client_customer,
  customer_client.level,
  customer_client.manager,
  customer_client.descriptive_name,
  customer_client.currency_code,
  customer_client.time_zone,
  customer_client.id,
  customer_client.status
FROM customer_client
WHERE customer_client.status = 'ENABLED'
""".strip()


def campaign_performance_segments_query(start: date, end: date) -> str:
    """Observed Search performance by device/day/hour/network.

    These dimensions are diagnostics. Zero conversions alone never becomes a waste
    claim; Epic 4 uses them as context unless another evidence layer establishes loss.
    """
    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  segments.date,
  segments.ad_network_type,
  segments.device,
  segments.day_of_week,
  segments.hour,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.all_conversions,
  metrics.all_conversions_value
FROM campaign
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def user_location_performance_query(start: date, end: date) -> str:
    """Physical user-location evidence, not campaign target configuration."""
    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  customer.currency_code,
  campaign.id,
  campaign.name,
  user_location_view.country_criterion_id,
  user_location_view.targeting_location,
  segments.date,
  segments.ad_network_type,
  segments.geo_target_most_specific_location,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value,
  metrics.all_conversions,
  metrics.all_conversions_value
FROM user_location_view
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND segments.ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
  AND segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def geo_target_constants_query(resource_names: tuple[str, ...]) -> str:
    if not resource_names:
        raise ValueError("at least one geo target resource is required")
    if len(resource_names) > 500:
        raise ValueError("geo target metadata query is limited to 500 resources")
    escaped=[]
    for value in resource_names:
        value=value.strip()
        if not value.startswith("geoTargetConstants/") or not value.split("/")[-1].isdigit():
            raise ValueError(f"invalid geo target resource: {value}")
        escaped.append("'"+value+"'")
    joined=", ".join(escaped)
    return f"""
SELECT
  geo_target_constant.resource_name,
  geo_target_constant.id,
  geo_target_constant.name,
  geo_target_constant.canonical_name,
  geo_target_constant.country_code,
  geo_target_constant.target_type,
  geo_target_constant.status
FROM geo_target_constant
WHERE geo_target_constant.resource_name IN ({joined})
""".strip()


def campaign_health_query() -> str:
    """Current Search campaign serving-health snapshot.

    Google documents primary_status/reasons as output-only diagnostics that may lag
    account changes. Recovery OS stores them as observed provider evidence, not as
    instantaneous truth or financial-loss proof.
    """
    return """
SELECT
  customer.id,
  campaign.id,
  campaign.name,
  campaign.advertising_channel_type,
  campaign.status,
  campaign.primary_status,
  campaign.primary_status_reasons
FROM campaign
WHERE campaign.advertising_channel_type = 'SEARCH'
  AND campaign.status != 'REMOVED'
""".strip()


def conversion_action_inventory_query() -> str:
    """Current conversion-action configuration and coarse activity metadata.

    `primary_for_goal` is authoritative for primary/secondary role. The deprecated
    include_in_conversions_metric field is intentionally not used.
    """
    return """
SELECT
  customer.id,
  conversion_action.id,
  conversion_action.resource_name,
  conversion_action.name,
  conversion_action.status,
  conversion_action.type,
  conversion_action.category,
  conversion_action.origin,
  conversion_action.owner_customer,
  conversion_action.primary_for_goal,
  conversion_action.counting_type,
  conversion_action.click_through_lookback_window_days,
  conversion_action.view_through_lookback_window_days,
  conversion_action.attribution_model_settings.attribution_model,
  conversion_action.attribution_model_settings.data_driven_model_status,
  conversion_action.value_settings.default_value,
  conversion_action.value_settings.default_currency_code,
  conversion_action.value_settings.always_use_default_value,
  metrics.all_conversions,
  metrics.all_conversions_value,
  metrics.conversion_last_conversion_date,
  metrics.conversion_last_received_request_date_time
FROM conversion_action
""".strip()


def customer_conversion_goals_query() -> str:
    return """
SELECT
  customer.id,
  customer_conversion_goal.resource_name,
  customer_conversion_goal.category,
  customer_conversion_goal.origin,
  customer_conversion_goal.biddable
FROM customer_conversion_goal
""".strip()


def campaign_conversion_goals_query() -> str:
    return """
SELECT
  customer.id,
  campaign.id,
  campaign.name,
  campaign.status,
  campaign_conversion_goal.resource_name,
  campaign_conversion_goal.category,
  campaign_conversion_goal.origin,
  campaign_conversion_goal.biddable
FROM campaign_conversion_goal
WHERE campaign.status != 'REMOVED'
""".strip()


def campaign_goal_configs_query() -> str:
    return """
SELECT
  customer.id,
  campaign.id,
  campaign.name,
  campaign.status,
  conversion_goal_campaign_config.resource_name,
  conversion_goal_campaign_config.goal_config_level,
  conversion_goal_campaign_config.custom_conversion_goal
FROM conversion_goal_campaign_config
WHERE campaign.status != 'REMOVED'
""".strip()


def conversion_lag_distribution_query(start: date, end: date) -> str:
    _validate_window(start, end)
    return f"""
SELECT
  customer.id,
  segments.conversion_action,
  segments.conversion_action_name,
  segments.conversion_action_category,
  segments.conversion_lag_bucket,
  metrics.conversions,
  metrics.all_conversions,
  metrics.conversions_value,
  metrics.all_conversions_value
FROM customer
WHERE segments.date BETWEEN '{_iso(start)}' AND '{_iso(end)}'
""".strip()


def offline_conversion_upload_diagnostics_query() -> str:
    """Offline upload diagnostics, queried only when a conversion-customer context is known."""
    return """
SELECT
  offline_conversion_upload_conversion_action_summary.resource_name,
  offline_conversion_upload_conversion_action_summary.conversion_action_id,
  offline_conversion_upload_conversion_action_summary.conversion_action_name,
  offline_conversion_upload_conversion_action_summary.client,
  offline_conversion_upload_conversion_action_summary.status,
  offline_conversion_upload_conversion_action_summary.total_event_count,
  offline_conversion_upload_conversion_action_summary.successful_event_count,
  offline_conversion_upload_conversion_action_summary.pending_event_count,
  offline_conversion_upload_conversion_action_summary.last_upload_date_time
FROM offline_conversion_upload_conversion_action_summary
""".strip()


def change_events_query(start: datetime, end: datetime) -> str:
    """Recent Google Ads configuration changes.

    ChangeEvent is bounded to recent provider history and may be delayed; callers must
    use it as supplementary monitoring evidence, never synchronous mutation truth.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("change event timestamps must be timezone-aware")
    if start > end:
        raise ValueError("start must be <= end")
    if (end-start).days > 30:
        raise ValueError("Google ChangeEvent window cannot exceed 30 days")
    s=start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")
    e=end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")
    return f"""
SELECT
  change_event.change_date_time,
  change_event.change_resource_type,
  change_event.change_resource_name,
  change_event.client_type,
  change_event.user_email,
  change_event.changed_fields
FROM change_event
WHERE change_event.change_date_time >= '{s}'
  AND change_event.change_date_time <= '{e}'
ORDER BY change_event.change_date_time DESC
LIMIT 10000
""".strip()
