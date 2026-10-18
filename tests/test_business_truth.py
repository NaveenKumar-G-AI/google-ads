from datetime import datetime, timezone

import pytest

from recovery.business_truth import (
    AudiencePolicy,
    BusinessOutcome,
    BusinessTruthSnapshot,
    CatalogCompleteness,
    CommercialModel,
    CustomerLocationRequirement,
    EvidenceKind,
    EvidenceRef,
    ExplicitNonOffer,
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

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def confirmed(*evidence_ids: str) -> TruthBasis:
    return TruthBasis(
        status=TruthStatus.CONFIRMED,
        evidence_ids=tuple(evidence_ids),
        confirmed_by="owner@example.test",
        confirmed_at=NOW,
    )


def provisional() -> TruthBasis:
    return TruthBasis(status=TruthStatus.PROVISIONAL)


def evidence(evidence_id: str = "owner-1") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        kind=EvidenceKind.OPERATOR,
        reference="Owner onboarding confirmation",
        captured_at=NOW,
    )


def roofing_offer(basis: TruthBasis | None = None) -> Offer:
    return Offer(
        offer_id="roof-replacement",
        name="Roof replacement",
        aliases=("new roof", "replace roof"),
        description="Residential roof replacement service",
        commercial_model=CommercialModel.QUOTE_BASED,
        offer_status=OfferStatus.ACTIVE,
        basis=basis or confirmed("owner-1"),
    )


def snapshot(**overrides) -> BusinessTruthSnapshot:
    data = dict(
        business_id="biz-1",
        business_name="Accurate Roofing",
        version=1,
        created_at=NOW,
        created_by="owner@example.test",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(roofing_offer(),),
        evidence=(evidence(),),
    )
    data.update(overrides)
    return BusinessTruthSnapshot(**data)


def test_confirmed_truth_requires_confirmer_and_time():
    with pytest.raises(ValueError, match="confirmed_by"):
        TruthBasis(status=TruthStatus.CONFIRMED)


def test_snapshot_time_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        snapshot(created_at=datetime(2026, 10, 15, 12, 0))


def test_partial_catalog_does_not_make_unlisted_offering_invalid():
    s = snapshot(
        offer_catalog_completeness=CatalogCompleteness.PARTIAL,
        explicit_non_offers=(),
    )
    report = s.readiness_for(TruthClaim.OFFERING_MISMATCH)
    assert report.ready is False
    assert {i.code for i in report.issues} == {"OFFER_CATALOG_NOT_COMPLETE"}


def test_partial_catalog_can_only_use_explicit_confirmed_non_offers():
    s = snapshot(
        offer_catalog_completeness=CatalogCompleteness.PARTIAL,
        explicit_non_offers=(
            ExplicitNonOffer(
                exclusion_id="solar",
                name="Solar installation",
                aliases=("solar panels",),
                reason="Business does not install solar",
                basis=confirmed("owner-1"),
            ),
        ),
    )
    report = s.readiness_for(TruthClaim.OFFERING_MISMATCH)
    assert report.ready is True
    assert {i.code for i in report.issues} == {"OFFER_CATALOG_PARTIAL"}


def test_provisional_non_offer_cannot_unlock_partial_catalog():
    s = snapshot(
        offer_catalog_completeness=CatalogCompleteness.PARTIAL,
        explicit_non_offers=(
            ExplicitNonOffer(
                exclusion_id="solar",
                name="Solar installation",
                aliases=(),
                reason="Extracted from website",
                basis=provisional(),
            ),
        ),
    )
    assert s.readiness_for(TruthClaim.OFFERING_MISMATCH).ready is False


def test_confirmed_offer_and_confirmed_non_offer_cannot_conflict():
    with pytest.raises(ValueError, match="conflicts"):
        snapshot(
            explicit_non_offers=(
                ExplicitNonOffer(
                    exclusion_id="bad",
                    name="New roof",
                    aliases=(),
                    reason="Contradictory test",
                    basis=confirmed("owner-1"),
                ),
            )
        )


def test_missing_intent_policy_is_unknown_not_denied():
    s = snapshot(intent_policies=())
    assert s.confirmed_intent_policy(IntentCategory.EMPLOYMENT) is None
    assert s.readiness_for(TruthClaim.INTENT_MISMATCH).ready is False


def test_explicit_employment_policy_can_deny_jobs():
    p = IntentPolicy(
        policy_id="employment-global",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="Advertising account is for customer acquisition, not recruiting",
        basis=confirmed("owner-1"),
    )
    s = snapshot(intent_policies=(p,))
    assert s.readiness_for(TruthClaim.INTENT_MISMATCH).ready is True
    assert s.confirmed_intent_policy(IntentCategory.EMPLOYMENT) == p


def test_competitor_intent_can_be_conditional_not_forced_bad():
    p = IntentPolicy(
        policy_id="competitor-global",
        category=IntentCategory.COMPETITOR,
        disposition=PolicyDisposition.CONDITIONAL,
        reason="Some comparison searches are valuable",
        condition="Review by campaign and competitor before action",
        basis=confirmed("owner-1"),
    )
    s = snapshot(intent_policies=(p,))
    assert s.confirmed_intent_policy(IntentCategory.COMPETITOR).disposition is PolicyDisposition.CONDITIONAL


def test_conditional_policy_requires_condition():
    with pytest.raises(ValueError, match="requires condition"):
        IntentPolicy(
            policy_id="info",
            category=IntentCategory.INFORMATIONAL,
            disposition=PolicyDisposition.CONDITIONAL,
            reason="Depends",
            basis=confirmed("owner-1"),
        )


def test_offer_specific_intent_policy_precedes_global():
    global_rule = IntentPolicy(
        policy_id="free-global",
        category=IntentCategory.FREE,
        disposition=PolicyDisposition.DENY,
        reason="No free service",
        basis=confirmed("owner-1"),
    )
    scoped_rule = IntentPolicy(
        policy_id="free-roof",
        category=IntentCategory.FREE,
        disposition=PolicyDisposition.ALLOW,
        reason="Free roof inspection is offered",
        basis=confirmed("owner-1"),
        offer_ids=("roof-replacement",),
    )
    s = snapshot(intent_policies=(global_rule, scoped_rule))
    assert s.confirmed_intent_policy(IntentCategory.FREE).disposition is PolicyDisposition.DENY
    assert s.confirmed_intent_policy(
        IntentCategory.FREE, offer_id="roof-replacement"
    ).disposition is PolicyDisposition.ALLOW


def test_conflicting_confirmed_intent_rules_are_rejected():
    a = IntentPolicy(
        policy_id="jobs-a",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="No recruitment",
        basis=confirmed("owner-1"),
    )
    b = IntentPolicy(
        policy_id="jobs-b",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.ALLOW,
        reason="Contradiction",
        basis=confirmed("owner-1"),
    )
    with pytest.raises(ValueError, match="conflicting confirmed intent"):
        snapshot(intent_policies=(a, b))


def test_intent_policy_cannot_reference_unknown_offer():
    p = IntentPolicy(
        policy_id="free-x",
        category=IntentCategory.FREE,
        disposition=PolicyDisposition.DENY,
        reason="test",
        basis=confirmed("owner-1"),
        offer_ids=("missing-offer",),
    )
    with pytest.raises(ValueError, match="unknown offer"):
        snapshot(intent_policies=(p,))


def test_geo_policy_distinguishes_customer_presence_from_job_destination():
    dallas = GeoArea(
        area_id="dallas",
        display_name="Dallas, Texas",
        country_code="US",
        region="Texas",
        city="Dallas",
    )
    geo = GeoPolicy(
        requirement=CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA,
        included_areas=(dallas,),
        excluded_areas=(),
        basis=confirmed("owner-1"),
    )
    s = snapshot(geo_policy=geo)
    assert s.readiness_for(TruthClaim.GEO_MISMATCH).ready is True


def test_geo_service_area_requires_included_area():
    with pytest.raises(ValueError, match="requires at least one included area"):
        GeoPolicy(
            requirement=CustomerLocationRequirement.CUSTOMER_MUST_BE_IN_SERVICE_AREA,
            included_areas=(),
            excluded_areas=(),
            basis=confirmed("owner-1"),
        )


def test_geo_same_area_cannot_be_include_and_exclude():
    a = GeoArea("dallas-a", "Dallas", "US", region="Texas", city="Dallas")
    b = GeoArea("dallas-b", "Dallas city", "US", region="Texas", city="Dallas")
    with pytest.raises(ValueError, match="both included and excluded"):
        GeoPolicy(
            requirement=CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA,
            included_areas=(a,),
            excluded_areas=(b,),
            basis=confirmed("owner-1"),
        )


def test_conversion_quality_requires_confirmed_primary_business_outcome():
    page_view = BusinessOutcome(
        outcome_id="page-view",
        name="Page view",
        role=OutcomeRole.NOT_A_BUSINESS_OUTCOME,
        description="Page load only",
        basis=confirmed("owner-1"),
    )
    s = snapshot(outcomes=(page_view,))
    assert s.readiness_for(TruthClaim.CONVERSION_QUALITY).ready is False


def test_confirmed_primary_outcome_unlocks_conversion_truth():
    lead = BusinessOutcome(
        outcome_id="qualified-lead",
        name="Qualified lead",
        role=OutcomeRole.PRIMARY_BUSINESS_OUTCOME,
        description="Lead accepted as a genuine roofing prospect",
        basis=confirmed("owner-1"),
    )
    s = snapshot(outcomes=(lead,))
    assert s.readiness_for(TruthClaim.CONVERSION_QUALITY).ready is True


def test_unknown_evidence_reference_is_rejected():
    bad_offer = roofing_offer(confirmed("does-not-exist"))
    with pytest.raises(ValueError, match="unknown evidence"):
        snapshot(offers=(bad_offer,))


def test_fingerprint_changes_when_business_truth_changes():
    a = snapshot()
    b = snapshot(
        version=2,
        supersedes_version=1,
        business_name="Accurate Roofing & Exteriors",
    )
    assert a.fingerprint_sha256 != b.fingerprint_sha256


def test_fingerprint_is_independent_of_collection_order():
    e2 = evidence("owner-2")
    p1 = IntentPolicy(
        policy_id="jobs",
        category=IntentCategory.EMPLOYMENT,
        disposition=PolicyDisposition.DENY,
        reason="No recruitment",
        basis=confirmed("owner-1"),
    )
    p2 = IntentPolicy(
        policy_id="free",
        category=IntentCategory.FREE,
        disposition=PolicyDisposition.DENY,
        reason="No free service",
        basis=confirmed("owner-2"),
    )
    a = snapshot(intent_policies=(p1, p2), evidence=(evidence(), e2))
    b = snapshot(intent_policies=(p2, p1), evidence=(e2, evidence()))
    assert a.fingerprint_sha256 == b.fingerprint_sha256


def test_audience_unknown_is_not_automatically_rejected():
    s = snapshot(audience_policies=())
    assert s.readiness_for(TruthClaim.AUDIENCE_MISMATCH).ready is False


def test_confirmed_denied_audience_can_support_audience_claim():
    rule = AudiencePolicy(
        audience_id="renters",
        name="Renters",
        aliases=("tenant", "renting"),
        disposition=PolicyDisposition.DENY,
        reason="Service requires property-owner authorization",
        basis=confirmed("owner-1"),
    )
    s = snapshot(audience_policies=(rule,))
    report = s.readiness_for(TruthClaim.AUDIENCE_MISMATCH)
    assert report.ready is True
    assert any(i.code == "AUDIENCE_CATALOG_PARTIAL" for i in report.issues)
