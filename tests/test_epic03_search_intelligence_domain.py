from decimal import Decimal
import pytest
from recovery.search_intelligence import NGramSource, aggregate_ngrams, lexical_tokens, make_ngrams, validate_sort


def row(q,cost,conv='0',candidate=0):
    return NGramSource(q,10,2,cost,Decimal(conv),Decimal('0'),candidate)


def test_lexical_tokens_preserve_punctuation_accents_and_scripts_after_conservative_normalization():
    assert lexical_tokens('  Café   repair!  தமிழ்  ') == ('café','repair!','தமிழ்')


def test_ngrams_are_contiguous_whitespace_tokens_only():
    assert make_ngrams('Emergency roof repair now',2) == ('emergency roof','roof repair','repair now')
    assert make_ngrams('one two',3) == ()
    with pytest.raises(ValueError): make_ngrams('x',7)


def test_ngram_aggregation_counts_each_query_once_per_gram():
    out=aggregate_ngrams([row('free free quote',100, candidate=20)],n=1)
    free=next(x for x in out if x.ngram=='free')
    assert free.query_count==1 and free.cost_micros==100 and free.potentially_avoidable_observed_micros==20


def test_ngram_sort_is_volume_only_and_ratio_sort_is_rejected():
    assert [x.ngram for x in aggregate_ngrams([row('cheap roof',10),row('roof repair',100)],n=1,sort='cost')][0:1] == ['roof']
    with pytest.raises(ValueError): aggregate_ngrams([row('x',1)],n=1,sort='ctr')
    with pytest.raises(ValueError): validate_sort('cpa')


def test_zero_conversion_filter_is_explicit():
    out=aggregate_ngrams([row('jobs roof',100,'0'),row('roof service',200,'1')],n=1,without_conversions=True)
    assert {x.ngram for x in out} == {'jobs','roof'}
