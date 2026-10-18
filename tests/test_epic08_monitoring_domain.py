from decimal import Decimal
import pytest
from recovery.monitoring import (
    CampaignHealthObservation, AlertSeverity, campaign_health_signal,
    spend_anomaly_signal, conversion_drop_signal, derive_alert_state,
    incident_observation_action, validate_alert_transition,
)


def test_paused_campaign_is_not_incident_by_itself():
    row=CampaignHealthObservation('123','1','Paused search','SEARCH','PAUSED','PAUSED',('CAMPAIGN_PAUSED',))
    assert campaign_health_signal(row) is None


def test_provider_not_eligible_and_limited_severities_are_conservative():
    critical=CampaignHealthObservation('123','1','Lead gen','SEARCH','ENABLED','NOT_ELIGIBLE',('NO_AD_GROUP_ADS',))
    warning=CampaignHealthObservation('123','2','Brand','SEARCH','ENABLED','LIMITED',('BUDGET_CONSTRAINED',))
    assert campaign_health_signal(critical).severity is AlertSeverity.CRITICAL
    assert campaign_health_signal(warning).severity is AlertSeverity.WARNING
    assert campaign_health_signal(critical).evidence['financial_claim_supported'] is False


def test_spend_anomaly_is_diagnostic_not_waste_claim():
    signal=spend_anomaly_signal(campaign_id='1',campaign_name='A',currency_code='USD',baseline_daily_cost_micros=10_000_000,recent_daily_cost_micros=30_000_000,baseline_days=14,recent_days=3)
    assert signal and signal.evidence['financial_claim_supported'] is False
    assert signal.evidence['causal_claim_supported'] is False


def test_spend_anomaly_requires_volume_and_observation_depth():
    assert spend_anomaly_signal(campaign_id='1',campaign_name='A',currency_code='USD',baseline_daily_cost_micros=1_000_000,recent_daily_cost_micros=20_000_000,baseline_days=14,recent_days=3) is None
    assert spend_anomaly_signal(campaign_id='1',campaign_name='A',currency_code='USD',baseline_daily_cost_micros=10_000_000,recent_daily_cost_micros=30_000_000,baseline_days=3,recent_days=1) is None


def test_conversion_drop_is_noncausal_and_carries_maturity_policy():
    signal=conversion_drop_signal(campaign_id='1',campaign_name='A',currency_code='USD',baseline_daily_cost_micros=10_000_000,recent_daily_cost_micros=8_000_000,baseline_daily_conversions=Decimal('10'),recent_daily_conversions=Decimal('1'),baseline_days=14,recent_days=3,maturity_lag_days=7)
    assert signal and signal.severity is AlertSeverity.CRITICAL
    assert signal.evidence['causal_claim_supported'] is False
    assert signal.evidence['maturity_lag_days']==7


def test_alert_state_is_immutable_event_projection():
    events=[{'event_type':'opened','occurred_at':1},{'event_type':'acknowledged','occurred_at':2},{'event_type':'resolved','occurred_at':3}]
    assert derive_alert_state(events).value=='resolved'


def test_active_incident_is_reobserved_and_true_recurrence_gets_new_generation():
    assert incident_observation_action('open',2)==('reuse',2,'observed')
    assert incident_observation_action('acknowledged',2)==('reuse',2,'observed')
    assert incident_observation_action('resolved',2,condition_cleared_after_close=True)==('new',3,'opened')
    assert incident_observation_action('dismissed',7,condition_cleared_after_close=True)==('new',8,'opened')


def test_manual_close_without_observed_clear_does_not_inflate_recurrence_generation():
    assert incident_observation_action('resolved',2,condition_cleared_after_close=False)==('reuse',2,'reopened')
    assert incident_observation_action('dismissed',7,condition_cleared_after_close=False)==('reuse',7,'observed')


def test_transition_contract_rejects_history_rewrite_and_assignment_after_closure():
    validate_alert_transition('open','acknowledged')
    validate_alert_transition('acknowledged','resolved')
    validate_alert_transition('resolved','reopened')
    validate_alert_transition('dismissed','commented')
    with pytest.raises(ValueError): validate_alert_transition('resolved','acknowledged')
    with pytest.raises(ValueError): validate_alert_transition('resolved','assigned')
    with pytest.raises(ValueError): validate_alert_transition('acknowledged','acknowledged')
