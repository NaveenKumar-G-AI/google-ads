from datetime import datetime, timezone
from uuid import uuid4
import pytest

from recovery.recovery_center import RecoveryProofTotals, aggregate_latest_ledger, latest_ledger_entries

NOW=datetime(2026,10,16,tzinfo=timezone.utc)

def row(mid, *, historical=100, projected=80, observed=5, verified=0, causal='not_evaluated', created=NOW):
    return {'entry_id':uuid4(),'mutation_event_id':mid,'currency_code':'INR','historical_candidate_micros':historical,
            'projected_prevented_micros':projected,'observed_post_action_query_spend_micros':observed,
            'verified_recovery_micros':verified,'causal_status':causal,'created_at':created}

def test_latest_ledger_snapshot_deduplicates_same_mutation_event():
    mid=uuid4(); a=row(mid,projected=10); b=row(mid,projected=20,created=NOW.replace(microsecond=1))
    latest=latest_ledger_entries([a,b])
    assert len(latest)==1 and latest[0]['projected_prevented_micros']==20

def test_unlinked_legacy_rows_are_excluded_from_recovery_headline():
    linked=row(uuid4(),historical=100)
    legacy={**row(uuid4(),historical=999),'mutation_event_id':None}
    b=aggregate_latest_ledger([linked,legacy])['INR']
    assert b['acted_on_historical_candidate_micros']==100
    assert b['ledger_action_count']==1

def test_verified_recovery_requires_verified_causal_status():
    with pytest.raises(ValueError,match='non-verified'):
        aggregate_latest_ledger([row(uuid4(),verified=50,causal='inconclusive')])

def test_financial_classes_are_non_additive_by_contract():
    t=RecoveryProofTotals('INR',100,90,80,10,20)
    assert t.descriptive_difference_vs_projection_micros==70
    with pytest.raises(RuntimeError,match='non-additive'):
        _=t.additive_total_micros

def test_currency_buckets_never_merge():
    a=row(uuid4()); b={**row(uuid4()),'currency_code':'USD'}
    out=aggregate_latest_ledger([a,b])
    assert set(out)=={'INR','USD'}
