from datetime import date
from decimal import Decimal
from recovery.measurement_integrity import (
    ConversionActionObservation,CustomerConversionGoalObservation,CampaignGoalConfigObservation,
    ConversionLagObservation,MeasurementMapping,MeasurementConfidence,assess_measurement_integrity,lag_bucket_max_days,
)

def action(*,primary=True,status='ENABLED',resource='customers/123/conversionActions/1'):
    return ConversionActionObservation(customer_id='123',resource_name=resource,action_id=resource.rsplit('/',1)[-1],name='Qualified lead',status=status,
        action_type='WEBPAGE',category='QUALIFIED_LEAD',origin='WEBSITE',owner_customer='customers/123',primary_for_goal=primary,counting_type='ONE_PER_CLICK',
        click_through_lookback_days=30,view_through_lookback_days=1,attribution_model='GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN',data_driven_model_status='AVAILABLE',
        default_value=Decimal('1'),default_currency_code='INR',always_use_default_value=False,all_conversions=Decimal('12'),all_conversions_value=Decimal('12'),
        last_conversion_date=date(2026,10,10),last_received_request_at='2026-10-10 12:00:00')

def mapping(resource='customers/123/conversionActions/1',role='primary_business_outcome',confirmed=True):
    return MeasurementMapping(resource,'truth-1','qualified',role,confirmed)

def test_no_inventory_is_unknown_and_blocks_conversion_dependent_claims():
    a=assess_measurement_integrity(actions=[],customer_goals=[],campaign_goals=[],campaign_configs=[],lag_observations=[],mappings={},configured_conversion_lag_days=7)
    assert a.confidence is MeasurementConfidence.UNKNOWN
    assert not a.conversion_dependent_claims_allowed and not a.recovery_verification_allowed

def test_confirmed_primary_business_outcome_can_be_strong():
    x=action(); g=CustomerConversionGoalObservation('123','customers/123/customerConversionGoals/QUALIFIED_LEAD~WEBSITE','QUALIFIED_LEAD','WEBSITE',True)
    a=assess_measurement_integrity(actions=[x],customer_goals=[g],campaign_goals=[],campaign_configs=[],lag_observations=[],mappings={x.resource_name:mapping()},configured_conversion_lag_days=30)
    assert a.confidence is MeasurementConfidence.STRONG
    assert a.conversion_dependent_claims_allowed and a.recovery_verification_allowed

def test_primary_action_mapped_to_non_business_outcome_is_blocker():
    x=action(); a=assess_measurement_integrity(actions=[x],customer_goals=[],campaign_goals=[],campaign_configs=[],lag_observations=[],mappings={x.resource_name:mapping(role='not_a_business_outcome')},configured_conversion_lag_days=30)
    assert a.confidence is MeasurementConfidence.BLOCKED
    assert any(i.code=='primary_action_is_not_business_outcome' for i in a.issues)

def test_unmapped_primary_is_constrained_not_invented_as_trustworthy():
    x=action(); a=assess_measurement_integrity(actions=[x],customer_goals=[],campaign_goals=[],campaign_configs=[],lag_observations=[],mappings={},configured_conversion_lag_days=30)
    assert a.confidence is MeasurementConfidence.CONSTRAINED
    assert any(i.code=='primary_action_unmapped' for i in a.issues)

def test_secondary_confirmed_business_outcome_is_review_signal():
    x=action(primary=False); a=assess_measurement_integrity(actions=[x],customer_goals=[],campaign_goals=[],campaign_configs=[],lag_observations=[],mappings={x.resource_name:mapping()},configured_conversion_lag_days=30)
    assert a.confidence is MeasurementConfidence.CONSTRAINED
    assert any(i.code=='business_outcome_is_secondary' for i in a.issues)

def test_observed_lag_later_than_policy_constrains_recent_zero_conversion_evidence():
    x=action(); lag=ConversionLagObservation('123',x.resource_name,x.name,'QUALIFIED_LEAD','TWENTY_ONE_TO_THIRTY_DAYS',Decimal('1'),Decimal('1'),Decimal('1'),Decimal('1'))
    a=assess_measurement_integrity(actions=[x],customer_goals=[],campaign_goals=[],campaign_configs=[],lag_observations=[lag],mappings={x.resource_name:mapping()},configured_conversion_lag_days=7)
    assert a.confidence is MeasurementConfidence.CONSTRAINED
    assert any(i.code=='configured_lag_shorter_than_observed' for i in a.issues)

def test_campaign_specific_goal_config_is_visible_complexity_not_automatic_blocker():
    x=action(); cfg=CampaignGoalConfigObservation('123','99','Brand Search','ENABLED','customers/123/conversionGoalCampaignConfigs/99','CAMPAIGN',None)
    a=assess_measurement_integrity(actions=[x],customer_goals=[],campaign_goals=[],campaign_configs=[cfg],lag_observations=[],mappings={x.resource_name:mapping()},configured_conversion_lag_days=30)
    assert a.confidence is MeasurementConfidence.STRONG
    assert any(i.code=='campaign_specific_goal_configuration' and i.severity.value=='info' for i in a.issues)

def test_lag_bucket_mapping_is_explicit_and_unknown_does_not_guess():
    assert lag_bucket_max_days('SIXTY_TO_NINETY_DAYS')==90
    assert lag_bucket_max_days('UNKNOWN') is None
    assert lag_bucket_max_days('future_bucket') is None
