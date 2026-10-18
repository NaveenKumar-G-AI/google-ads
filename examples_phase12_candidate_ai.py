from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'src'
if str(SRC) not in sys.path: sys.path.insert(0,str(SRC))

from datetime import datetime, timezone
from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind,
    EvidenceRef, IntentCategory, IntentPolicy, Offer, OfferStatus,
    PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.semantic_ai import CandidateSemanticAI, GeminiInteractionsTransport, SemanticAIConfig
from recovery.search_intent import BusinessFitEvaluator

NOW=datetime.now(timezone.utc)
ev=EvidenceRef('owner',EvidenceKind.OPERATOR,'demo owner confirmation',NOW)
basis=TruthBasis(TruthStatus.CONFIRMED,('owner',),'owner@example.invalid',NOW)
truth=BusinessTruthSnapshot(
    business_id='roofco', business_name='Roof Co', version=1, created_at=NOW,
    created_by='owner@example.invalid',
    offer_catalog_completeness=CatalogCompleteness.COMPLETE,
    audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
    offers=(Offer('roof-replacement','Roof replacement',('new roof',),'Residential roof replacement',CommercialModel.QUOTE_BASED,OfferStatus.ACTIVE,basis),),
    intent_policies=(IntentPolicy('employment-deny',IntentCategory.EMPLOYMENT,PolicyDisposition.DENY,'Recruitment traffic is not an acquisition goal',basis),),
    evidence=(ev,),
)

engine=CandidateSemanticAI(
    transport=GeminiInteractionsTransport(),
    config=SemanticAIConfig(model='gemini-3.8-flash'),
)
result=engine.interpret_many(('roof replacement','roof replacement jobs','best option near me'),truth)
fit=BusinessFitEvaluator()
for a,c in zip(result.assessments,result.declared_confidences):
    d=fit.evaluate(a,truth)
    print({'query':a.raw_query,'semantic_status':a.status.value,'business_fit':d.disposition.value,'declared_confidence':str(c) if c is not None else None})
print({'provider':result.provider,'model':result.model,'usage':result.usage,'prompt_fingerprint':result.prompt_fingerprint})
print('Candidate only: do not enable in production until the Phase-11 release gate passes.')
