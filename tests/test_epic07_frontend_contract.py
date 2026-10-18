from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'web'
def read(rel):return (ROOT/rel).read_text(encoding='utf-8')

def test_recovery_center_is_active_canonical_navigation():
    assert '["Recovery Center","/app/recovery-center",true]' in read('components/epic1/app-shell.tsx')

def test_recovery_center_product_surfaces_exist():
    for rel in ('app/(dashboard)/app/recovery-center/page.tsx','app/(dashboard)/app/recovery-center/cases/page.tsx','app/(dashboard)/app/recovery-center/breakdowns/page.tsx','app/(dashboard)/app/recovery-center/timeline/page.tsx'):
        assert (ROOT/rel).exists(),rel

def test_recovery_center_ui_keeps_financial_classes_separate():
    page=read('app/(dashboard)/app/recovery-center/page.tsx')
    for text in ('Current observed candidate','Historical acted-on exposure','Projected prevented','Observed post-action query spend','Verified recovery'):
        assert text in page
    assert 'These financial classes are non-additive' in page
    assert 'never inferred waste' in page

def test_case_proof_links_back_to_exact_recovery_case():
    page=read('app/(dashboard)/app/recovery-center/cases/page.tsx')
    assert '/app/action-center/cases/' in page
    assert 'Latest ledger snapshot per exact mutation' in page
