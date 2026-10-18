from datetime import datetime, timezone
from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel,
    EvidenceKind, EvidenceRef, IntentCategory, IntentPolicy,
    Offer, OfferStatus, PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.search_intent import ConservativeLexicalInterpreter, BusinessFitEvaluator

now = datetime.now(timezone.utc)
basis = TruthBasis(
    status=TruthStatus.CONFIRMED,
    evidence_ids=("owner",),
    confirmed_by="owner",
    confirmed_at=now,
)
truth = BusinessTruthSnapshot(
    business_id="demo-roofing",
    business_name="Demo Roofing",
    version=1,
    created_at=now,
    created_by="owner",
    offer_catalog_completeness=CatalogCompleteness.COMPLETE,
    audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
    offers=(Offer(
        offer_id="roof-replacement",
        name="Roof replacement",
        aliases=("new roof",),
        description="Residential roof replacement",
        commercial_model=CommercialModel.QUOTE_BASED,
        offer_status=OfferStatus.ACTIVE,
        basis=basis,
    ),),
    intent_policies=(IntentPolicy(
        policy_id="employment-deny",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="Customer acquisition account is not used for recruiting",
        basis=basis,
    ),),
    evidence=(EvidenceRef(
        evidence_id="owner",
        kind=EvidenceKind.OPERATOR,
        reference="Owner-confirmed demo truth",
        captured_at=now,
    ),),
)

interpreter = ConservativeLexicalInterpreter()
evaluator = BusinessFitEvaluator()
for query in ("roof replacement", "roof replacement jobs", "best option near me"):
    semantic = interpreter.interpret(query, truth)
    decision = evaluator.evaluate(semantic, truth)
    print(f"{query!r}: {semantic.status.value} -> {decision.disposition.value}")
