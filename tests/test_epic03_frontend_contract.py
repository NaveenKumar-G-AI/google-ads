from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'web'

def read(rel): return (ROOT/rel).read_text()

def test_search_intelligence_is_enabled_in_canonical_navigation():
    shell=read('components/epic1/app-shell.tsx')
    assert '["Search Intelligence","/app/search-intelligence",true]' in shell

def test_search_intelligence_has_real_explorer_surfaces():
    for rel in [
        'app/(dashboard)/app/search-intelligence/page.tsx',
        'app/(dashboard)/app/search-intelligence/terms/page.tsx',
        'app/(dashboard)/app/search-intelligence/terms/detail/page.tsx',
        'app/(dashboard)/app/search-intelligence/ngrams/page.tsx',
        'app/(dashboard)/app/search-intelligence/breakdowns/page.tsx',
        'app/(dashboard)/app/portfolios/[portfolioId]/search/page.tsx',
    ]: assert (ROOT/rel).exists(), rel

def test_frontend_explains_window_and_privacy_boundaries():
    joined='\n'.join(read(rel) for rel in [
        'components/epic3/financial-window-note.tsx',
        'app/(dashboard)/app/search-intelligence/page.tsx',
        'app/(dashboard)/app/search-intelligence/terms/detail/page.tsx',
    ])
    assert 'Financial evidence suppressed' in joined
    assert 'hidden queries' in joined.lower() or 'privacy' in joined.lower()

def test_ngram_ui_does_not_offer_ratio_sorting():
    page=read('app/(dashboard)/app/search-intelligence/ngrams/page.tsx')
    for bad in ['CTR','CPA','ROAS','Conversion rate']:
        assert bad not in page
    for good in ['Cost','Clicks','Impressions','Conversions']:
        assert good in page
