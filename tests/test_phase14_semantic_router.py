from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind, EvidenceRef,
    IntentCategory, IntentPolicy, Offer, OfferStatus, PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.search_intent import FitDisposition
from recovery.semantic_ai import CandidateSemanticAI, SemanticAIConfig, SemanticModelResponse
from recovery.semantic_router import (
    ActiveSemanticRelease, DriftPolicy, FallbackReason, ProductionSemanticRouter,
    ReviewedProductionDecision, RouteSource, SemanticDriftGuard,
)

NOW=datetime(2026,10,15,9,0,tzinfo=timezone.utc)


def confirmed(): return TruthBasis(TruthStatus.CONFIRMED,("owner",),"owner",NOW)

def truth():
    return BusinessTruthSnapshot(
        business_id='biz', business_name='Roof Co', version=1, created_at=NOW, created_by='owner',
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(Offer('roof','Roof replacement',('new roof',),'Roofing',CommercialModel.QUOTE_BASED,OfferStatus.ACTIVE,confirmed()),),
        intent_policies=(IntentPolicy('jobs',IntentCategory.EMPLOYMENT,PolicyDisposition.DENY,'No hiring acquisition',confirmed()),),
        evidence=(EvidenceRef('owner',EvidenceKind.OPERATOR,'owner',NOW),),
    )


def item(item_id, query, *, confidence=0.99, language='en', jobs=False):
    return {
        'item_id':item_id,'raw_query':query,'status':'resolved','language_code':language,
        'intents':([{'category':'employment','confidence':0.99,'evidence':['jobs']}] if jobs else []),
        'offer_candidates':[{'offer_id':'roof','confidence':0.99,'evidence':['roof']}],
        'non_offer_candidates':[],'unresolved_signals':[],'ambiguity_reason':None,
        'declared_confidence':confidence,
    }


class Transport:
    def __init__(self, *, version='rev-1', confidence=0.99, language='en', provider='fake'):
        self.version=version; self.confidence=confidence; self.language=language; self.provider=provider
    def classify(self, **kwargs):
        p=json.loads(kwargs['input_json'])
        results=[item(x['item_id'],x['raw_query'],confidence=self.confidence,language=self.language,jobs='jobs' in x['raw_query']) for x in p['queries']]
        return SemanticModelResponse({'schema_version':1,'results':results},self.provider,kwargs['model'],self.version,'req')


class Resolver:
    def __init__(self, release): self.release=release
    def active_release(self): return self.release


def setup(*, confidence=0.99, language='en', version='rev-1', tripped=False):
    ai=CandidateSemanticAI(transport=Transport(version=version,confidence=confidence,language=language),config=SemanticAIConfig(maximum_attempts=1))
    rel=ActiveSemanticRelease(
        release_definition_id='11111111-1111-1111-1111-111111111111',
        release_fingerprint='a'*64, provider='fake', model=ai.config.model,
        provider_model_version='rev-1', thinking_level=ai.config.thinking_level.value,
        prompt_version=ai.prompt_version, candidate_contract_fingerprint=ai.contract_fingerprint,
        semantic_schema_version=1, selected_confidence_threshold=Decimal('0.95'),
        approved_languages=('en',), tripped=tripped, trip_reason='drift' if tripped else None,
    )
    return ai, rel


def test_no_active_release_uses_baseline():
    ai,_=setup()
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(None)).route(query='roof replacement jobs',truth=truth())
    assert r.route_source is RouteSource.BASELINE
    assert r.fallback_reason is FallbackReason.NO_ACTIVE_RELEASE


def test_exact_active_release_can_supply_semantics():
    ai,rel=setup()
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(rel)).route(query='roof replacement jobs',truth=truth())
    assert r.route_source is RouteSource.RELEASED_AI
    assert r.fit.disposition is FitDisposition.IRRELEVANT
    assert r.release_fingerprint == rel.release_fingerprint
    assert r.declared_confidence == Decimal('0.99')


def test_low_confidence_and_unapproved_language_fall_back():
    ai,rel=setup(confidence=0.80)
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(rel)).route(query='roof replacement jobs',truth=truth())
    assert r.route_source is RouteSource.BASELINE
    assert r.fallback_reason is FallbackReason.CONFIDENCE_BELOW_THRESHOLD

    ai2,rel2=setup(language='ta')
    r2=ProductionSemanticRouter(candidate=ai2,release_resolver=Resolver(rel2)).route(query='roof replacement jobs',truth=truth())
    assert r2.route_source is RouteSource.BASELINE
    assert r2.fallback_reason is FallbackReason.LANGUAGE_UNAPPROVED


def test_tripped_release_never_calls_candidate_authoritatively():
    ai,rel=setup(tripped=True)
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(rel)).route(query='roof replacement jobs',truth=truth())
    assert r.route_source is RouteSource.BASELINE
    assert r.fallback_reason is FallbackReason.RELEASE_TRIPPED


def test_provider_revision_change_falls_back_and_trips_release():
    ai,rel=setup(version='rev-2')
    trips=[]
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(rel),on_hard_release_failure=lambda release,reason:trips.append((release,reason))).route(query='roof replacement jobs',truth=truth())
    assert r.route_source is RouteSource.BASELINE
    assert r.fallback_reason is FallbackReason.PROVIDER_VERSION_MISMATCH
    assert len(trips)==1 and 'provider revision changed' in trips[0][1]


def test_local_candidate_contract_mismatch_trips_without_trusting_model():
    ai,rel=setup()
    bad=replace(rel, candidate_contract_fingerprint='b'*64)
    trips=[]
    r=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(bad),on_hard_release_failure=lambda release,reason:trips.append(reason)).route(query='roof jobs',truth=truth())
    assert r.fallback_reason is FallbackReason.RELEASE_IDENTITY_MISMATCH
    assert trips


def obs(i, *, predicted=FitDisposition.IRRELEVANT, gold=FitDisposition.IRRELEVANT):
    return ReviewedProductionDecision(
        decision_fingerprint=f'{i:064x}', release_fingerprint='a'*64,
        route_source=RouteSource.RELEASED_AI, predicted_disposition=predicted, gold_disposition=gold,
    )


def test_drift_guard_refuses_claim_on_small_sample():
    guard=SemanticDriftGuard(DriftPolicy(minimum_reviewed_cases=20,minimum_actionable_irrelevant_cases=10,maximum_wilson_upper_unsafe_rate=Decimal('0.5')))
    out=guard.evaluate(release_fingerprint='a'*64,observations=[obs(i) for i in range(5)])
    assert not out.sufficient_evidence
    assert not out.tripped


def test_drift_guard_trips_on_any_unsafe_false_exclusion_under_zero_tolerance():
    policy=DriftPolicy(minimum_reviewed_cases=20,minimum_actionable_irrelevant_cases=20,maximum_unsafe_false_exclusions=0,maximum_wilson_upper_unsafe_rate=Decimal('0.5'))
    rows=[obs(i) for i in range(20)]
    rows[-1]=obs(19,gold=FitDisposition.RELEVANT)
    out=SemanticDriftGuard(policy).evaluate(release_fingerprint='a'*64,observations=rows)
    assert out.sufficient_evidence
    assert out.tripped
    assert out.unsafe_false_exclusions==1


def test_route_decision_fingerprint_is_stable():
    ai,rel=setup()
    fixed=lambda: NOW
    router=ProductionSemanticRouter(candidate=ai,release_resolver=Resolver(rel),clock=fixed)
    a=router.route(query='roof replacement jobs',truth=truth())
    b=router.route(query='roof replacement jobs',truth=truth())
    assert a.fingerprint_sha256==b.fingerprint_sha256
