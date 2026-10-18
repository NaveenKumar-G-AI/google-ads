from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind,
    EvidenceRef, ExplicitNonOffer, IntentCategory, IntentPolicy, Offer, OfferStatus,
    PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.search_intent import AssessmentStatus, BusinessFitEvaluator, FitDisposition
from recovery.semantic_ai import (
    CandidateBenchmarkRunner, CandidateSemanticAI, GeminiInteractionsTransport,
    ModelUsage, SemanticAIConfig, SemanticAIBudgetError, SemanticAIContractError,
    SemanticAIRetryableError, SemanticModelResponse, ThinkingLevel,
)
from recovery.semantic_eval import DatasetSplit, GoldSemanticCase, LabelSource, ReleasePolicy

NOW=datetime(2026,10,15,8,0,tzinfo=timezone.utc)

def confirmed():
    return TruthBasis(TruthStatus.CONFIRMED,('owner',),'owner@test',NOW)

def truth():
    ev=EvidenceRef('owner',EvidenceKind.OPERATOR,'owner confirmation',NOW)
    return BusinessTruthSnapshot(
        business_id='biz', business_name='Accurate Roofing', version=1,
        created_at=NOW, created_by='owner@test',
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(Offer('roof-replacement','Roof replacement',('new roof',),'Residential roof replacement',CommercialModel.QUOTE_BASED,OfferStatus.ACTIVE,confirmed()),),
        explicit_non_offers=(ExplicitNonOffer('solar','Solar roofing',('solar roof',),'Not offered',confirmed()),),
        intent_policies=(IntentPolicy('jobs',IntentCategory.EMPLOYMENT,PolicyDisposition.DENY,'Recruitment is not acquisition',confirmed()),),
        evidence=(ev,),
    )

def result(item_id, query, *, status='resolved', intents=(), offers=('roof-replacement',), nonoffers=(), confidence=0.99, ambiguity=None):
    return {
        'item_id': item_id, 'raw_query': query, 'status': status, 'language_code':'en',
        'intents':[{'category':x,'confidence':confidence,'evidence':[x]} for x in intents],
        'offer_candidates':[{'offer_id':x,'confidence':confidence,'evidence':[x]} for x in offers],
        'non_offer_candidates':[{'exclusion_id':x,'confidence':confidence,'evidence':[x]} for x in nonoffers],
        'unresolved_signals':[], 'ambiguity_reason':ambiguity, 'declared_confidence':confidence,
    }

class FakeTransport:
    def __init__(self, builder, *, usage=ModelUsage(total_tokens=100)):
        self.builder=builder; self.calls=[]; self.usage=usage
    def classify(self, **kwargs):
        self.calls.append(kwargs)
        payload=json.loads(kwargs['input_json'])
        return SemanticModelResponse(self.builder(payload), 'fake', kwargs['model'], 'fake-v1', 'req1', self.usage)

def engine(builder, **config_kwargs):
    return CandidateSemanticAI(
        transport=FakeTransport(builder),
        config=SemanticAIConfig(maximum_attempts=1, **config_kwargs),
    )

def test_valid_candidate_maps_to_phase3_contract_and_application_owns_identity():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]})
    r=e.interpret_many(('roof replacement',),t)
    a=r.assessments[0]
    assert a.interpreter == 'candidate-semantic-ai'
    assert a.interpreter_version == e.version
    assert BusinessFitEvaluator().evaluate(a,t).disposition is FitDisposition.RELEVANT
    assert r.declared_confidences == (Decimal('0.99'),)

def test_semantic_prompt_excludes_financial_performance_fields():
    t=truth(); captured={}
    def build(p):
        captured.update(p)
        return {'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]}
    e=engine(build); e.interpret('roof replacement',t)
    text=json.dumps(captured).casefold()
    for forbidden in ('cost_micros','conversions','conversion_value','cpa','roas','revenue','clicks','impressions'):
        assert forbidden not in text

def test_unknown_business_id_is_rejected_even_when_json_schema_is_valid():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'],offers=('invented-offer',))]})
    with pytest.raises(SemanticAIContractError,match='unknown business IDs'):
        e.interpret('invented',t)

def test_missing_or_extra_batch_items_rejected():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]})
    with pytest.raises(SemanticAIContractError,match='result IDs'):
        e.interpret_many(('one','two'),t)

def test_model_cannot_rewrite_raw_query():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000','rewritten query')]})
    with pytest.raises(SemanticAIContractError,match='raw_query mismatch'):
        e.interpret('roof replacement',t)

def test_ambiguous_requires_reason_through_phase3_validation():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'],status='ambiguous',ambiguity=None)]})
    with pytest.raises(SemanticAIContractError,match='ambiguous assessment requires'):
        e.interpret('roof maybe',t)

def test_duplicate_input_queries_are_supported_without_mapping_confusion():
    t=truth()
    def build(p): return {'schema_version':1,'results':[result(x['item_id'],x['raw_query']) for x in reversed(p['queries'])]}
    e=engine(build)
    r=e.interpret_many(('roof replacement','roof replacement'),t)
    assert [x.raw_query for x in r.assessments] == ['roof replacement','roof replacement']

def test_retryable_errors_are_bounded_but_contract_errors_are_not_retried():
    t=truth()
    class Retrying:
        def __init__(self): self.n=0
        def classify(self,**kwargs):
            self.n+=1
            if self.n<3: raise SemanticAIRetryableError('429')
            p=json.loads(kwargs['input_json'])
            return SemanticModelResponse({'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]},'fake',kwargs['model'])
    tr=Retrying(); sleeps=[]
    e=CandidateSemanticAI(transport=tr,config=SemanticAIConfig(maximum_attempts=3,base_retry_seconds=0.01),sleep=sleeps.append,jitter=lambda:0.5)
    e.interpret('roof replacement',t)
    assert tr.n==3 and len(sleeps)==2

    class Bad:
        def __init__(self): self.n=0
        def classify(self,**kwargs): self.n+=1; raise SemanticAIContractError('bad')
    bad=Bad(); e2=CandidateSemanticAI(transport=bad,config=SemanticAIConfig(maximum_attempts=3),sleep=lambda _:None)
    with pytest.raises(SemanticAIContractError): e2.interpret('roof',t)
    assert bad.n==1

def test_token_budget_is_enforced_after_provider_usage_is_known():
    t=truth()
    tr=FakeTransport(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]},usage=ModelUsage(total_tokens=500))
    e=CandidateSemanticAI(transport=tr,config=SemanticAIConfig(maximum_attempts=1,maximum_total_tokens_per_request=100))
    with pytest.raises(SemanticAIBudgetError): e.interpret('roof',t)

def test_gemini_transport_uses_interactions_structured_output_without_tools_or_sampling_controls():
    captured={}
    class Interactions:
        def create(self,**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_text=json.dumps({'schema_version':1,'results':[]}),
                usage_metadata=SimpleNamespace(prompt_token_count=11,response_token_count=7,thoughts_token_count=3,total_token_count=21),
                model_version='gemini-3.8-flash-001',id='interaction-1',
            )
    client=SimpleNamespace(interactions=Interactions())
    tr=GeminiInteractionsTransport(client=client)
    r=tr.classify(model='gemini-3.8-flash',system_instruction='system',input_json='{}',response_schema={'type':'object'},thinking_level=ThinkingLevel.LOW,timeout_seconds=9)
    assert captured['store'] is False
    assert 'tools' not in captured
    assert captured['generation_config'] == {'thinking_level':'low'}
    assert captured['response_format']['mime_type']=='application/json'
    assert r.usage.total_tokens==21 and r.provider_model_version=='gemini-3.8-flash-001'

def test_prompt_fingerprint_changes_when_query_changes():
    t=truth()
    e=engine(lambda p:{'schema_version':1,'results':[result('q0000',p['queries'][0]['raw_query'])]})
    a=e.interpret_many(('roof replacement',),t).prompt_fingerprint
    b=e.interpret_many(('new roof',),t).prompt_fingerprint
    assert a != b

def gold(case_id,query,t,expected,split):
    return GoldSemanticCase(case_id,query,t.fingerprint_sha256,expected,AssessmentStatus.RESOLVED,'en',split,LabelSource.DOUBLE_REVIEW,2)

def test_benchmark_runner_selects_threshold_on_calibration_then_gates_test():
    t=truth()
    def build(p):
        out=[]
        for q in p['queries']:
            is_job='jobs' in q['raw_query']
            out.append(result(q['item_id'],q['raw_query'],intents=('employment',) if is_job else (),confidence=0.99))
        return {'schema_version':1,'results':out}
    e=engine(build,maximum_batch_queries=4)
    cases=[]
    for i in range(30): cases.append(gold(f'c{i}',f'roof replacement jobs {i}',t,FitDisposition.IRRELEVANT,DatasetSplit.CALIBRATION))
    for i in range(30): cases.append(gold(f't{i}',f'roof replacement jobs test {i}',t,FitDisposition.IRRELEVANT,DatasetSplit.TEST))
    runner=CandidateBenchmarkRunner(e)
    policy=ReleasePolicy(minimum_test_cases=20,minimum_safety_cases=20,minimum_calibration_support=20,maximum_wilson_upper_unsafe_rate=Decimal('0.2'))
    out=runner.run(cases=cases,truths={t.fingerprint_sha256:t},policy=policy)
    assert out.selected_confidence_threshold is not None
    assert out.gate_result.passed
    assert len(out.candidate_fingerprint)==64

def test_benchmark_rejects_mixed_provider_model_versions_across_batches():
    t=truth()
    class MixedTransport:
        def __init__(self): self.n=0
        def classify(self,**kwargs):
            self.n+=1
            p=json.loads(kwargs['input_json'])
            version='provider-v1' if self.n==1 else 'provider-v2'
            return SemanticModelResponse(
                {'schema_version':1,'results':[result(x['item_id'],x['raw_query'],intents=('employment',) if 'jobs' in x['raw_query'] else ()) for x in p['queries']]},
                'fake',kwargs['model'],version,f'req-{self.n}',ModelUsage(total_tokens=10),
            )
    e=CandidateSemanticAI(transport=MixedTransport(),config=SemanticAIConfig(maximum_attempts=1,maximum_batch_queries=1))
    cases=[
        gold('c1','roof replacement jobs 1',t,FitDisposition.IRRELEVANT,DatasetSplit.CALIBRATION),
        gold('t1','roof replacement jobs 2',t,FitDisposition.IRRELEVANT,DatasetSplit.TEST),
    ]
    with pytest.raises(SemanticAIContractError,match='mixed multiple provider model versions'):
        CandidateBenchmarkRunner(e).run(
            cases=cases, truths={t.fingerprint_sha256:t},
            policy=ReleasePolicy(minimum_test_cases=1,minimum_safety_cases=1,minimum_calibration_support=1),
        )
