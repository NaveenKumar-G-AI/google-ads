from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from recovery.business_truth import (
    AudiencePolicy,
    BusinessOutcome,
    ProtectedBusinessQuery,
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
    TruthStatus,
)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("datetime field must be ISO-8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _basis(p: dict[str, Any]) -> TruthBasis:
    return TruthBasis(
        status=TruthStatus(p["status"]),
        evidence_ids=tuple(p.get("evidence_ids", ())),
        confirmed_by=p.get("confirmed_by"),
        confirmed_at=_dt(p["confirmed_at"]) if p.get("confirmed_at") else None,
        note=p.get("note"),
    )


def parse_business_truth_payload(
    payload: dict[str, Any], *, submitted_by: str, submitted_at: datetime | None = None
) -> BusinessTruthSnapshot:
    """Parse the canonical Phase-2 schema back into validated domain objects.

    `created_by` is server-owned and is always replaced by the authenticated actor.
    Every nested domain constructor still runs its full Phase-2 validation.
    """
    evidence = tuple(
        EvidenceRef(
            evidence_id=e["evidence_id"],
            kind=EvidenceKind(e["kind"]),
            reference=e["reference"],
            captured_at=_dt(e["captured_at"]),
            content_sha256=e.get("content_sha256"),
        )
        for e in payload.get("evidence", ())
    )
    offers = tuple(
        Offer(
            offer_id=o["offer_id"],
            name=o["name"],
            aliases=tuple(o.get("aliases", ())),
            description=o["description"],
            commercial_model=CommercialModel(o["commercial_model"]),
            offer_status=OfferStatus(o["offer_status"]),
            basis=_basis(o["basis"]),
        )
        for o in payload.get("offers", ())
    )
    non_offers = tuple(
        ExplicitNonOffer(
            exclusion_id=o["exclusion_id"],
            name=o["name"],
            aliases=tuple(o.get("aliases", ())),
            reason=o["reason"],
            basis=_basis(o["basis"]),
        )
        for o in payload.get("explicit_non_offers", ())
    )
    intent_policies = tuple(
        IntentPolicy(
            policy_id=p["policy_id"],
            category=IntentCategory(p["category"]),
            disposition=PolicyDisposition(p["disposition"]),
            reason=p["reason"],
            basis=_basis(p["basis"]),
            offer_ids=tuple(p.get("offer_ids", ())),
            condition=p.get("condition"),
        )
        for p in payload.get("intent_policies", ())
    )
    audience_policies = tuple(
        AudiencePolicy(
            audience_id=p["audience_id"],
            name=p["name"],
            aliases=tuple(p.get("aliases", ())),
            disposition=PolicyDisposition(p["disposition"]),
            reason=p["reason"],
            basis=_basis(p["basis"]),
            condition=p.get("condition"),
        )
        for p in payload.get("audience_policies", ())
    )
    geo = payload.get("geo_policy")
    geo_policy = None
    if geo is not None:
        def area(a: dict[str, Any]) -> GeoArea:
            return GeoArea(
                area_id=a["area_id"], display_name=a["display_name"],
                country_code=a["country_code"], region=a.get("region"), city=a.get("city"),
                postal_code=a.get("postal_code"),
                google_geo_target_constant=a.get("google_geo_target_constant"),
            )
        geo_policy = GeoPolicy(
            requirement=CustomerLocationRequirement(geo["requirement"]),
            included_areas=tuple(area(a) for a in geo.get("included_areas", ())),
            excluded_areas=tuple(area(a) for a in geo.get("excluded_areas", ())),
            basis=_basis(geo["basis"]),
            condition=geo.get("condition"),
        )
    outcomes = tuple(
        BusinessOutcome(
            outcome_id=o["outcome_id"], name=o["name"], role=OutcomeRole(o["role"]),
            description=o["description"], basis=_basis(o["basis"]),
        )
        for o in payload.get("outcomes", ())
    )
    protected_queries = tuple(
        ProtectedBusinessQuery(query=o["query"], reason=o["reason"], basis=_basis(o["basis"]))
        for o in payload.get("protected_queries", ())
    )
    return BusinessTruthSnapshot(
        business_id=payload["business_id"],
        business_name=payload["business_name"],
        version=int(payload["version"]),
        created_at=submitted_at or datetime.now(timezone.utc),
        created_by=submitted_by,
        offer_catalog_completeness=CatalogCompleteness(payload["offer_catalog_completeness"]),
        audience_catalog_completeness=CatalogCompleteness(payload["audience_catalog_completeness"]),
        offers=offers,
        explicit_non_offers=non_offers,
        intent_policies=intent_policies,
        audience_policies=audience_policies,
        geo_policy=geo_policy,
        outcomes=outcomes,
        protected_queries=protected_queries,
        evidence=evidence,
        schema_version=int(payload.get("schema_version", 1)),
        supersedes_version=payload.get("supersedes_version"),
    )
