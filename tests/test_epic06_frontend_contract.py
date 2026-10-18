from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'web'
def read(rel):return (ROOT/rel).read_text(encoding='utf-8')

def test_action_center_is_active_canonical_navigation():
    assert '["Action Center","/app/action-center",true]' in read('components/epic1/app-shell.tsx')

def test_action_center_product_surfaces_exist():
    for rel in ('app/(dashboard)/app/action-center/page.tsx','app/(dashboard)/app/action-center/approvals/page.tsx','app/(dashboard)/app/action-center/history/page.tsx','app/(dashboard)/app/action-center/cases/[caseId]/page.tsx'):
        assert (ROOT/rel).exists(),rel

def test_case_ui_never_labels_candidate_exposure_as_recovered():
    page=read('app/(dashboard)/app/action-center/cases/[caseId]/page.tsx')
    table=read('components/epic1/recovery-case-list.tsx')
    assert 'Potentially avoidable observed spend' in page
    assert 'This is not recovered money' in page
    assert 'not recovered' in table

def test_case_ui_exposes_staleness_and_exact_rollback_safety():
    page=read('app/(dashboard)/app/action-center/cases/[caseId]/page.tsx')
    assert 'Execution blocked — evidence is stale' in page
    assert 'Rollback exact resource' in page
    assert 'exact Google resource identity' in page

def test_case_ui_exposes_measurement_gate_instead_of_silently_hiding_disabled_execution():
    page=read('app/(dashboard)/app/action-center/cases/[caseId]/page.tsx')
    assert 'Measurement Integrity blocks approval/execution' in page
    assert 'conversion_claims_allowed' in page
