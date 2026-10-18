from datetime import datetime, timezone

from recovery.api.business_truth_io import parse_business_truth_payload
from recovery.business_truth import (
    BusinessTruthSnapshot, CatalogCompleteness, CommercialModel, EvidenceKind,
    EvidenceRef, Offer, OfferStatus, TruthBasis, TruthStatus,
)

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def sample_snapshot():
    basis = TruthBasis(
        status=TruthStatus.CONFIRMED,
        evidence_ids=("owner",),
        confirmed_by="owner@example.test",
        confirmed_at=NOW,
    )
    ev = EvidenceRef(
        evidence_id="owner", kind=EvidenceKind.OPERATOR,
        reference="Owner confirmation", captured_at=NOW,
    )
    offer = Offer(
        offer_id="roof", name="Roof replacement", aliases=("new roof",),
        description="Residential roof replacement",
        commercial_model=CommercialModel.QUOTE_BASED,
        offer_status=OfferStatus.ACTIVE, basis=basis,
    )
    return BusinessTruthSnapshot(
        business_id="biz", business_name="Accurate Roofing", version=1,
        created_at=NOW, created_by="untrusted-client-value",
        offer_catalog_completeness=CatalogCompleteness.COMPLETE,
        audience_catalog_completeness=CatalogCompleteness.UNKNOWN,
        offers=(offer,), evidence=(ev,),
    )


def test_api_reconstructs_domain_and_overrides_created_by():
    original = sample_snapshot()
    submitted_at = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)
    parsed = parse_business_truth_payload(
        original.canonical_dict(), submitted_by="user:server-verified", submitted_at=submitted_at
    )
    assert parsed.created_by == "user:server-verified"
    assert parsed.created_at == submitted_at
    assert parsed.business_name == original.business_name
    assert parsed.offers[0].offer_id == "roof"
    assert parsed.fingerprint_sha256 != original.fingerprint_sha256
