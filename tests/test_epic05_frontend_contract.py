from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'web'

def read(rel): return (ROOT/rel).read_text(encoding='utf-8')

def test_measurement_is_active_canonical_navigation():
    shell=read('components/epic1/app-shell.tsx')
    assert '["Measurement","/app/measurement-integrity",true]' in shell

def test_measurement_product_surfaces_exist():
    for rel in ('app/(dashboard)/app/measurement-integrity/page.tsx','app/(dashboard)/app/measurement-integrity/conversion-actions/page.tsx','app/(dashboard)/app/measurement-integrity/goals/page.tsx','app/(dashboard)/app/measurement-integrity/lag/page.tsx'):
        assert (ROOT/rel).exists(),rel

def test_ui_uses_evidence_state_not_a_numeric_score():
    page=read('app/(dashboard)/app/measurement-integrity/page.tsx')
    assert 'Measurement confidence' in page
    assert 'conversion_dependent_claims_allowed' in page
    assert 'recovery_verification_allowed' in page
    assert '0–100' not in page

def test_conversion_action_ui_explicitly_does_not_infer_enhanced_conversion_status():
    page=read('app/(dashboard)/app/measurement-integrity/conversion-actions/page.tsx')
    assert 'Not inferred from this conversion-action resource' in page
