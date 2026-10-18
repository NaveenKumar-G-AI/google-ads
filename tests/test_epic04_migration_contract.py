from pathlib import Path
SQL=(Path(__file__).resolve().parents[1]/'src/recovery/db/migrations/0012_epic04_waste_intelligence.sql').read_text()

def test_waste_dimension_evidence_is_first_class_and_immutable():
    for table in ('waste_dimension_chunks','campaign_performance_segments','user_location_observations'):
        assert f'CREATE TABLE IF NOT EXISTS recovery.{table}' in SQL
    assert "prevent_immutable_mutation" in SQL
    assert "ENABLE ROW LEVEL SECURITY" in SQL and "FORCE ROW LEVEL SECURITY" in SQL

def test_geo_evidence_stores_actual_location_metadata_and_not_a_derived_waste_flag():
    for col in ('location_resource','canonical_name','country_code','target_type','targeting_location'):
        assert col in SQL
    assert 'is_waste' not in SQL.lower()
    assert 'waste_micros' not in SQL.lower()

def test_dimension_evidence_keeps_conversion_signals_for_later_maturity_checks():
    for col in ('conversions numeric','all_conversions numeric','conversions_value numeric','all_conversions_value numeric'):
        assert col in SQL
