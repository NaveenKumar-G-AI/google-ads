from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from datetime import datetime, timezone
from decimal import Decimal

from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind,
    EvidenceRef, IntentCategory, IntentPolicy, Offer, OfferStatus,
    PolicyDisposition, TruthBasis, TruthStatus,
)
from recovery.search_intent import (
    AssessmentStatus, BusinessFitEvaluator, ConservativeLexicalInterpreter,
    FitDisposition,
)
from recovery.semantic_eval import (
    CandidatePrediction, DatasetSplit, GoldSemanticCase, LabelSource,
    SemanticEvaluator, evaluation_report_to_dict,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)


def truth() -> BusinessTruthSnapshot:
    ev = EvidenceRef("e1", EvidenceKind.OPERATOR, "demo owner confirmation", NOW)
    basis = TruthBasis(TruthStatus.CONFIRMED, ("e1",), "owner@test", NOW)
    return BusinessTruthSnapshot(
        business_id="roofco",
        business_name="Roof Co",
        version=1,
        created_at=NOW,
        created_by="owner@test",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(
            Offer(
                "roof-replacement", "Roof replacement", ("new roof",),
                "Residential roof replacement", CommercialModel.QUOTE_BASED,
                OfferStatus.ACTIVE, basis,
            ),
        ),
        intent_policies=(
            IntentPolicy(
                "employment-deny", IntentCategory.EMPLOYMENT,
                PolicyDisposition.DENY,
                "Recruiting traffic is not a customer-acquisition goal", basis,
            ),
        ),
        evidence=(ev,),
    )


t = truth()
interpreter = ConservativeLexicalInterpreter()
cases = [
    GoldSemanticCase("1", "roof replacement", t.fingerprint_sha256, FitDisposition.RELEVANT, AssessmentStatus.RESOLVED, "en", DatasetSplit.TEST, LabelSource.DOUBLE_REVIEW, 2),
    GoldSemanticCase("2", "roof replacement jobs", t.fingerprint_sha256, FitDisposition.IRRELEVANT, AssessmentStatus.RESOLVED, "en", DatasetSplit.TEST, LabelSource.ADJUDICATED, 2),
    GoldSemanticCase("3", "best option near me", t.fingerprint_sha256, FitDisposition.UNKNOWN, AssessmentStatus.INSUFFICIENT, "en", DatasetSplit.TEST, LabelSource.DOUBLE_REVIEW, 2),
]
predictions = [
    CandidatePrediction(
        c.case_id,
        interpreter.interpret(c.raw_query, t),
        Decimal("0.99") if c.case_id != "3" else Decimal("0.60"),
    )
    for c in cases
]
report = SemanticEvaluator(fit_evaluator=BusinessFitEvaluator()).evaluate(
    model_id="conservative-lexical-baseline",
    model_version="1.0",
    cases=cases,
    predictions=predictions,
    truths={t.fingerprint_sha256: t},
)
print(evaluation_report_to_dict(report))
print("Unsafe false exclusions:", report.unsafe_false_exclusions)
print("This demo is intentionally tiny and therefore cannot pass the production release gate.")
