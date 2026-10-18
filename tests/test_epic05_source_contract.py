from datetime import date
from pathlib import Path
from recovery.google_ads.gaql import conversion_action_inventory_query,customer_conversion_goals_query,campaign_conversion_goals_query,campaign_goal_configs_query,conversion_lag_distribution_query
ROOT=Path(__file__).resolve().parents[1]

def test_current_google_primary_secondary_field_is_used_not_deprecated_include_metric():
    q=conversion_action_inventory_query()
    assert 'conversion_action.primary_for_goal' in q
    assert 'include_in_conversions_metric' not in q
    for f in ('conversion_action.counting_type','click_through_lookback_window_days','view_through_lookback_window_days','attribution_model_settings.attribution_model'):
        assert f in q

def test_goal_queries_keep_account_and_campaign_config_distinct():
    assert 'FROM customer_conversion_goal' in customer_conversion_goals_query()
    assert 'FROM campaign_conversion_goal' in campaign_conversion_goals_query()
    q=campaign_goal_configs_query()
    assert 'conversion_goal_campaign_config.goal_config_level' in q
    assert 'conversion_goal_campaign_config.custom_conversion_goal' in q

def test_conversion_lag_uses_provider_lag_bucket_not_local_date_guessing():
    q=conversion_lag_distribution_query(date(2026,10,1),date(2026,10,15))
    assert 'segments.conversion_lag_bucket' in q
    assert 'segments.conversion_action' in q
    assert "segments.date BETWEEN '2026-10-01' AND '2026-10-15'" in q

def test_measurement_snapshot_commits_before_inventory_marks_sync_completed():
    src=(ROOT/'src/recovery/google_ads/sync.py').read_text()
    assert src.index('commit_measurement(') < src.index('store.commit_inventory(')

def test_enhanced_conversion_status_is_not_fabricated_from_conversion_action_fields():
    repo=(ROOT/'src/recovery/api/repository.py').read_text()
    assert 'not_observable_from_conversion_action_resource' in repo
    assert 'enhanced_conversions_enabled=True' not in repo
