"""Offline Phase-13 demonstration: shadow output + blinded human gold review.

No Google/Gemini credentials are needed because the example uses a deterministic fake
transport. Real shadow jobs use the durable worker and server-side Gemini key.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind, EvidenceRef,
    IntentCategory, IntentPolicy, Offer, OfferStatus, PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.search_intent import AssessmentStatus, FitDisposition
from recovery.semantic_ai import CandidateSemanticAI, SemanticAIConfig, SemanticModelResponse
from recovery.semantic_release import BlindHumanReview, ShadowInput, ShadowSemanticRunner, adjudicate_gold_case

NOW=datetime(2026,10,15,8,0,tzinfo=timezone.utc)
basis=TruthBasis(TruthStatus.CONFIRMED,("owner",),"owner",NOW)
truth=BusinessTruthSnapshot(
    business_id="biz",business_name="Accurate Roofing",version=1,created_at=NOW,created_by="owner",
    offer_catalog_completeness=CatalogCompleteness.COMPLETE,
    audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
    offers=(Offer("roof","Roof replacement",(),"Residential roofing",CommercialModel.QUOTE_BASED,OfferStatus.ACTIVE,basis),),
    intent_policies=(IntentPolicy("jobs",IntentCategory.EMPLOYMENT,PolicyDisposition.DENY,"Not acquisition",basis),),
    evidence=(EvidenceRef("owner",EvidenceKind.OPERATOR,"Owner confirmation",NOW),),
)

class Fake:
    provider="demo-provider"
    def classify(self,**kwargs):
        p=json.loads(kwargs["input_json"])
        q=p["queries"][0]
        return SemanticModelResponse({"schema_version":1,"results":[{
            "item_id":q["item_id"],"raw_query":q["raw_query"],"status":"resolved","language_code":"en",
            "intents":[{"category":"employment","confidence":0.99,"evidence":["jobs"]}],
            "offer_candidates":[{"offer_id":"roof","confidence":0.99,"evidence":["roof"]}],
            "non_offer_candidates":[],"unresolved_signals":[],"ambiguity_reason":None,"declared_confidence":0.99,
        }]},self.provider,kwargs["model"],"demo-revision-001","demo-request")

candidate=CandidateSemanticAI(transport=Fake(),config=SemanticAIConfig(maximum_attempts=1))
source=ShadowInput.create(raw_query="roof replacement jobs",customer_id="1234567890",campaign_id="10",ad_group_id="20",network="SEARCH",observation_ids=("obs-1",),truth_fingerprint=truth.fingerprint_sha256)
shadow=ShadowSemanticRunner(candidate).run(inputs=(source,),truth=truth)
p=shadow.predictions[0]
print("candidate:",p.candidate_fit.disposition.value)
print("baseline:",p.baseline_fit.disposition.value)
print("production effect allowed:",p.production_effect_allowed)

reviews=(
    BlindHumanReview(source.raw_query,truth.fingerprint_sha256,"reviewer-a",FitDisposition.IRRELEVANT,AssessmentStatus.RESOLVED,"en",NOW,tags=("employment",)),
    BlindHumanReview(source.raw_query,truth.fingerprint_sha256,"reviewer-b",FitDisposition.IRRELEVANT,AssessmentStatus.RESOLVED,"en",NOW,tags=("employment",)),
)
gold=adjudicate_gold_case(reviews,dataset_salt="demo-split-secret")
print("gold label:",gold.expected_disposition.value)
print("gold source:",gold.label_source.value)
print("split:",gold.split.value)
