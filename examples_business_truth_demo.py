from datetime import datetime, timezone

from recovery.business_truth import (
    BusinessOutcome,
    BusinessTruthSnapshot,
    CatalogCompleteness,
    CommercialModel,
    CustomerLocationRequirement,
    EvidenceKind,
    EvidenceRef,
    GeoArea,
    GeoPolicy,
    IntentCategory,
    IntentPolicy,
    Offer,
    OfferStatus,
    OutcomeRole,
    PolicyDisposition,
    TruthBasis,
    TruthClaim,
    TruthStatus,
)

now = datetime.now(timezone.utc)
evidence = EvidenceRef(
    evidence_id="owner-confirmation",
    kind=EvidenceKind.OPERATOR,
    reference="Owner onboarding answers",
    captured_at=now,
)
confirmed = TruthBasis(
    status=TruthStatus.CONFIRMED,
    evidence_ids=(evidence.evidence_id,),
    confirmed_by="business-owner",
    confirmed_at=now,
)

truth = BusinessTruthSnapshot(
    business_id="demo-roofing",
    business_name="Demo Roofing",
    version=1,
    created_at=now,
    created_by="business-owner",
    offer_catalog_completeness=CatalogCompleteness.COMPLETE,
    audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
    offers=(
        Offer(
            offer_id="roof-replacement",
            name="Roof replacement",
            aliases=("new roof", "replace roof"),
            description="Residential roof replacement",
            commercial_model=CommercialModel.QUOTE_BASED,
            offer_status=OfferStatus.ACTIVE,
            basis=confirmed,
        ),
    ),
    intent_policies=(
        IntentPolicy(
            policy_id="employment",
            category=IntentCategory.EMPLOYMENT,
            disposition=PolicyDisposition.DENY,
            reason="Acquisition campaigns do not recruit employees",
            basis=confirmed,
        ),
        IntentPolicy(
            policy_id="informational",
            category=IntentCategory.INFORMATIONAL,
            disposition=PolicyDisposition.CONDITIONAL,
            reason="Some educational searches may precede a high-value purchase",
            condition="Require campaign and query context; never exclude automatically",
            basis=confirmed,
        ),
    ),
    geo_policy=GeoPolicy(
        requirement=CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA,
        included_areas=(
            GeoArea(
                area_id="dallas",
                display_name="Dallas, Texas",
                country_code="US",
                region="Texas",
                city="Dallas",
            ),
        ),
        excluded_areas=(),
        basis=confirmed,
    ),
    outcomes=(
        BusinessOutcome(
            outcome_id="qualified-lead",
            name="Qualified lead",
            role=OutcomeRole.PRIMARY_BUSINESS_OUTCOME,
            description="A genuine property owner requesting an eligible roofing service",
            basis=confirmed,
        ),
    ),
    evidence=(evidence,),
)

print("Business Truth fingerprint:", truth.fingerprint_sha256)
for claim in TruthClaim:
    report = truth.readiness_for(claim)
    print(f"{claim.value:22} ready={report.ready}")
    for issue in report.issues:
        print("  -", issue.code, "BLOCKER" if issue.blocker else "warning")
