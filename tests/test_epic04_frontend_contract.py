from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'web'
def read(rel): return (ROOT/rel).read_text()

def test_waste_intelligence_is_real_navigation_not_disabled_placeholder():
    shell=read('components/epic1/app-shell.tsx')
    assert '["Waste Intelligence","/app/waste-intelligence",true]' in shell

def test_waste_primary_surfaces_exist():
    for rel in ('app/(dashboard)/app/waste-intelligence/page.tsx','app/(dashboard)/app/waste-intelligence/queries/page.tsx','app/(dashboard)/app/waste-intelligence/dimensions/page.tsx','app/(dashboard)/app/waste-intelligence/geo/page.tsx'):
        assert (ROOT/rel).exists(),rel

def test_ui_explicitly_blocks_dimension_double_counting_and_zero_conversion_claims():
    note=read('components/epic4/waste-boundary-note.tsx')
    assert 'never additive' in note
    assert 'zero conversions' in note
    assert 'Diagnostic evidence only' in note

def test_geo_ui_says_physical_location_not_campaign_targeting():
    note=read('components/epic4/waste-boundary-note.tsx')
    assert 'actual user-location' in note
    assert 'Campaign targeting configuration alone is not treated as proof' in note

def test_overview_keeps_query_and_geo_candidate_separate():
    page=read('app/(dashboard)/app/waste-intelligence/page.tsx')
    assert 'Query candidate' in page and 'Geo candidate' in page
    assert 'Separate evidence lens — not additive' in page
