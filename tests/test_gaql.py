from datetime import date

from recovery.google_ads.gaql import campaign_network_spend_query, positive_keywords_query, search_term_query


def test_search_term_query_is_scoped_to_search_campaigns_and_networks() -> None:
    q = search_term_query(date(2026, 8, 1), date(2026, 10, 1))
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "'SEARCH_PARTNERS'" in q
    assert "segments.date" in q
    assert "metrics.cost_micros" in q
    assert "segments.search_term_targeting_status" in q


def test_campaign_query_uses_same_date_and_network_scope() -> None:
    q = campaign_network_spend_query(date(2026, 8, 1), date(2026, 10, 1))
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "segments.ad_network_type" in q
    assert "2026-08-01" in q
    assert "2026-10-01" in q


def test_positive_keyword_inventory_query_excludes_negatives_and_non_search_campaigns() -> None:
    q = positive_keywords_query()
    assert "ad_group_criterion.negative = FALSE" in q
    assert "campaign.advertising_channel_type = 'SEARCH'" in q
    assert "ad_group_criterion.keyword.text" in q
    assert "ad_group_criterion.keyword.match_type" in q


def test_experiment_recovery_query_contains_direct_experiment_stats():
    from recovery.google_ads.gaql import experiment_recovery_query
    q = experiment_recovery_query(123, date(2026, 9, 1), date(2026, 9, 30))
    assert "FROM experiment" in q
    assert "metrics.control_cost_micros" in q
    assert "metrics.cost_micros_p_value" in q
    assert "metrics.conversions_absolute_change_p_value" in q
    assert "experiment.experiment_id = 123" in q


def test_experiment_recovery_query_rejects_invalid_id():
    from recovery.google_ads.gaql import experiment_recovery_query
    import pytest
    with pytest.raises(ValueError):
        experiment_recovery_query(0, date(2026, 9, 1), date(2026, 9, 30))


def test_applied_negative_readback_query_is_narrow_and_validates_ids():
    from recovery.google_ads.gaql import applied_ad_group_negative_query
    import pytest
    q = applied_ad_group_negative_query("1", "20")
    assert "ad_group.id = 20" in q
    assert "ad_group_criterion.negative = TRUE" in q
    assert "ad_group_criterion.resource_name" in q
    with pytest.raises(ValueError):
        applied_ad_group_negative_query("1 OR 1=1", "20")


def test_customer_profile_query_binds_currency_and_timezone():
    from recovery.google_ads.gaql import customer_profile_query
    q = customer_profile_query()
    assert "customer.currency_code" in q
    assert "customer.time_zone" in q
    assert "customer.manager" in q
    assert "LIMIT 1" in q


def test_customer_children_query_only_requests_direct_enabled_hierarchy():
    from recovery.google_ads.gaql import customer_children_query
    q = customer_children_query()
    assert "FROM customer_client" in q
    assert "customer_client.level <= 1" in q
    assert "customer_client.status = 'ENABLED'" in q
