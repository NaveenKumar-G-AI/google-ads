from pathlib import Path
SRC=(Path(__file__).resolve().parents[1]/'src/recovery/api/repository.py').read_text()

def test_search_reads_only_completed_chunks_and_sync_runs():
    assert "c.status='completed'" in SRC
    assert "sr.status='completed'" in SRC

def test_financial_evidence_is_suppressed_outside_exact_analysis_window():
    assert 'analysis["window_matches"]' in SRC
    assert 'financial_evidence_in_window' in SRC
    assert 'if analysis["window_matches"] else 0' in SRC

def test_hidden_query_spend_is_never_reconstructed_into_query_rows():
    assert 'Privacy-hidden demand is not reconstructed into individual queries.' in SRC
    assert 'unobserved_search_micros' in SRC

def test_portfolio_ngram_groups_by_currency():
    assert 'GROUP BY currency_code,ngram' in SRC
