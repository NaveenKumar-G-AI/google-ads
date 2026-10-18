from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Any, Iterable


TRUTH_SCHEMA_VERSION = 1


class TruthStatus(str, Enum):
    """Whether a business fact is safe to treat as truth.

    Only CONFIRMED facts may support high-confidence automated actions. Facts that
    were extracted from a site/model but not confirmed stay PROVISIONAL.
    """

    CONFIRMED = "confirmed"
    PROVISIONAL = "provisional"
    DISPUTED = "disputed"
    RETIRED = "retired"


class EvidenceKind(str, Enum):
    OPERATOR = "operator"
    BUSINESS_WEBSITE = "business_website"
    BUSINESS_DOCUMENT = "business_document"
    CRM = "crm"
    CONTRACT = "contract"
    PUBLIC_SOURCE = "public_source"
    MODEL_INFERENCE = "model_inference"
    OTHER = "other"


class CatalogCompleteness(str, Enum):
    """Critical anti-hallucination state for catalogs.

    COMPLETE means absence can be meaningful. PARTIAL/UNKNOWN mean the system may
    not conclude "the business does not sell X" merely because X is not listed.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class OfferStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class CommercialModel(str, Enum):
    PAID = "paid"
    FREE = "free"
    FREEMIUM = "freemium"
    QUOTE_BASED = "quote_based"
    SUBSCRIPTION = "subscription"
    MARKETPLACE = "marketplace"
    OTHER = "other"
    UNKNOWN = "unknown"


class PolicyDisposition(str, Enum):
    """A business decision, never an AI guess.

    ALLOW: intent/audience is valid for acquisition.
    DENY: explicitly not wanted.
    CONDITIONAL: validity depends on context; never auto-exclude from this rule alone.
    UNKNOWN: business has not decided/confirmed.
    """

    ALLOW = "allow"
    DENY = "deny"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class IntentCategory(str, Enum):
    PURCHASE = "purchase"
    QUOTE = "quote"
    BOOKING = "booking"
    DEMO = "demo"
    TRIAL = "trial"
    INFORMATIONAL = "informational"
    DIY = "diy"
    FREE = "free"
    EMPLOYMENT = "employment"
    SUPPORT = "support"
    TRAINING = "training"
    RESEARCH = "research"
    COMPETITOR = "competitor"
    SECOND_HAND = "second_hand"
    RENTAL = "rental"
    REPAIR = "repair"
    WHOLESALE = "wholesale"
    OTHER = "other"


class CustomerLocationRequirement(str, Enum):
    """Business reality, intentionally independent of Google Ads geo settings."""

    NO_RESTRICTION = "no_restriction"
    CUSTOMER_MUST_BE_IN_SERVICE_AREA = "customer_must_be_in_service_area"
    DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA = "destination_or_job_must_be_in_service_area"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class OutcomeRole(str, Enum):
    PRIMARY_BUSINESS_OUTCOME = "primary_business_outcome"
    SUPPORTING_SIGNAL = "supporting_signal"
    NOT_A_BUSINESS_OUTCOME = "not_a_business_outcome"
    UNKNOWN = "unknown"


class TruthClaim(str, Enum):
    OFFERING_MISMATCH = "offering_mismatch"
    INTENT_MISMATCH = "intent_mismatch"
    AUDIENCE_MISMATCH = "audience_mismatch"
    GEO_MISMATCH = "geo_mismatch"
    CONVERSION_QUALITY = "conversion_quality"


def _nonblank(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} cannot be blank")
    return cleaned


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def _unique_normalized(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _nonblank(field_name, value)
        key = _normal(cleaned)
        if key in seen:
            raise ValueError(f"duplicate {field_name}: {cleaned!r}")
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _ensure_aware(dt: datetime, field_name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    evidence_id: str
    kind: EvidenceKind
    reference: str
    captured_at: datetime
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _nonblank("evidence_id", self.evidence_id))
        object.__setattr__(self, "reference", _nonblank("reference", self.reference))
        _ensure_aware(self.captured_at, "captured_at")
        if self.content_sha256 is not None:
            digest = self.content_sha256.strip().lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("content_sha256 must be a 64-character hex SHA-256")
            object.__setattr__(self, "content_sha256", digest)


@dataclass(frozen=True, slots=True)
class TruthBasis:
    status: TruthStatus
    evidence_ids: tuple[str, ...] = ()
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_ids",
            _unique_normalized(self.evidence_ids, field_name="evidence_id"),
        )
        if self.status is TruthStatus.CONFIRMED:
            if self.confirmed_by is None or not self.confirmed_by.strip():
                raise ValueError("confirmed truth requires confirmed_by")
            if self.confirmed_at is None:
                raise ValueError("confirmed truth requires confirmed_at")
            _ensure_aware(self.confirmed_at, "confirmed_at")
        elif self.confirmed_at is not None:
            _ensure_aware(self.confirmed_at, "confirmed_at")

    @property
    def is_confirmed(self) -> bool:
        return self.status is TruthStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class Offer:
    offer_id: str
    name: str
    aliases: tuple[str, ...]
    description: str
    commercial_model: CommercialModel
    offer_status: OfferStatus
    basis: TruthBasis

    def __post_init__(self) -> None:
        object.__setattr__(self, "offer_id", _nonblank("offer_id", self.offer_id))
        object.__setattr__(self, "name", _nonblank("offer name", self.name))
        object.__setattr__(self, "description", _nonblank("offer description", self.description))
        object.__setattr__(
            self, "aliases", _unique_normalized(self.aliases, field_name="offer alias")
        )

    @property
    def searchable_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True, slots=True)
class ExplicitNonOffer:
    exclusion_id: str
    name: str
    aliases: tuple[str, ...]
    reason: str
    basis: TruthBasis

    def __post_init__(self) -> None:
        object.__setattr__(self, "exclusion_id", _nonblank("exclusion_id", self.exclusion_id))
        object.__setattr__(self, "name", _nonblank("non-offer name", self.name))
        object.__setattr__(self, "reason", _nonblank("non-offer reason", self.reason))
        object.__setattr__(
            self, "aliases", _unique_normalized(self.aliases, field_name="non-offer alias")
        )

    @property
    def searchable_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True, slots=True)
class IntentPolicy:
    policy_id: str
    category: IntentCategory
    disposition: PolicyDisposition
    reason: str
    basis: TruthBasis
    offer_ids: tuple[str, ...] = ()
    condition: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _nonblank("policy_id", self.policy_id))
        object.__setattr__(self, "reason", _nonblank("intent policy reason", self.reason))
        object.__setattr__(
            self, "offer_ids", _unique_normalized(self.offer_ids, field_name="offer_id")
        )
        if self.disposition is PolicyDisposition.CONDITIONAL:
            if self.condition is None or not self.condition.strip():
                raise ValueError("conditional intent policy requires condition")


@dataclass(frozen=True, slots=True)
class AudiencePolicy:
    audience_id: str
    name: str
    aliases: tuple[str, ...]
    disposition: PolicyDisposition
    reason: str
    basis: TruthBasis
    condition: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "audience_id", _nonblank("audience_id", self.audience_id))
        object.__setattr__(self, "name", _nonblank("audience name", self.name))
        object.__setattr__(self, "reason", _nonblank("audience reason", self.reason))
        object.__setattr__(
            self, "aliases", _unique_normalized(self.aliases, field_name="audience alias")
        )
        if self.disposition is PolicyDisposition.CONDITIONAL:
            if self.condition is None or not self.condition.strip():
                raise ValueError("conditional audience policy requires condition")


@dataclass(frozen=True, slots=True)
class GeoArea:
    area_id: str
    display_name: str
    country_code: str
    region: str | None = None
    city: str | None = None
    postal_code: str | None = None
    google_geo_target_constant: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "area_id", _nonblank("area_id", self.area_id))
        object.__setattr__(self, "display_name", _nonblank("display_name", self.display_name))
        code = self.country_code.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError("country_code must be a 2-letter country code")
        object.__setattr__(self, "country_code", code)

    @property
    def semantic_key(self) -> tuple[str, str, str, str]:
        return (
            self.country_code,
            _normal(self.region or ""),
            _normal(self.city or ""),
            _normal(self.postal_code or ""),
        )


@dataclass(frozen=True, slots=True)
class GeoPolicy:
    requirement: CustomerLocationRequirement
    included_areas: tuple[GeoArea, ...]
    excluded_areas: tuple[GeoArea, ...]
    basis: TruthBasis
    condition: str | None = None

    def __post_init__(self) -> None:
        ids = [a.area_id for a in (*self.included_areas, *self.excluded_areas)]
        if len({_normal(x) for x in ids}) != len(ids):
            raise ValueError("geo area IDs must be unique")
        included_keys = {a.semantic_key for a in self.included_areas}
        excluded_keys = {a.semantic_key for a in self.excluded_areas}
        overlap = included_keys & excluded_keys
        if overlap:
            raise ValueError("same geographic area cannot be both included and excluded")
        if self.requirement is CustomerLocationRequirement.NO_RESTRICTION:
            if self.included_areas or self.excluded_areas:
                raise ValueError("NO_RESTRICTION geo policy cannot define include/exclude areas")
        if self.requirement in {
            CustomerLocationRequirement.CUSTOMER_MUST_BE_IN_SERVICE_AREA,
            CustomerLocationRequirement.DESTINATION_OR_JOB_MUST_BE_IN_SERVICE_AREA,
        } and not self.included_areas:
            raise ValueError("service-area geo policy requires at least one included area")
        if self.requirement is CustomerLocationRequirement.CONDITIONAL:
            if self.condition is None or not self.condition.strip():
                raise ValueError("conditional geo policy requires condition")


@dataclass(frozen=True, slots=True)
class ProtectedBusinessQuery:
    """Business-confirmed query that must remain eligible for paid search.

    This is intentionally business truth rather than a Google Ads keyword object.
    The analysis worker scopes it to the current campaign/ad group only when
    evaluating whether a proposed negative could block it.
    """

    query: str
    reason: str
    basis: TruthBasis

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _nonblank("protected query", self.query))
        object.__setattr__(self, "reason", _nonblank("protected query reason", self.reason))


@dataclass(frozen=True, slots=True)
class BusinessOutcome:
    outcome_id: str
    name: str
    role: OutcomeRole
    description: str
    basis: TruthBasis

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_id", _nonblank("outcome_id", self.outcome_id))
        object.__setattr__(self, "name", _nonblank("outcome name", self.name))
        object.__setattr__(self, "description", _nonblank("outcome description", self.description))


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    code: str
    message: str
    blocker: bool


@dataclass(frozen=True, slots=True)
class TruthReadinessReport:
    claim: TruthClaim
    issues: tuple[ReadinessIssue, ...]

    @property
    def ready(self) -> bool:
        return not any(i.blocker for i in self.issues)


@dataclass(frozen=True, slots=True)
class BusinessTruthSnapshot:
    """Immutable, versioned statement of what the business says is true.

    Every downstream classification/recommendation should store this snapshot's
    SHA-256 fingerprint. That makes later audits reproducible even after business
    facts change.
    """

    business_id: str
    business_name: str
    version: int
    created_at: datetime
    created_by: str
    offer_catalog_completeness: CatalogCompleteness
    audience_catalog_completeness: CatalogCompleteness
    offers: tuple[Offer, ...]
    explicit_non_offers: tuple[ExplicitNonOffer, ...] = ()
    intent_policies: tuple[IntentPolicy, ...] = ()
    audience_policies: tuple[AudiencePolicy, ...] = ()
    geo_policy: GeoPolicy | None = None
    outcomes: tuple[BusinessOutcome, ...] = ()
    protected_queries: tuple[ProtectedBusinessQuery, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    schema_version: int = TRUTH_SCHEMA_VERSION
    supersedes_version: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "business_id", _nonblank("business_id", self.business_id))
        object.__setattr__(self, "business_name", _nonblank("business_name", self.business_name))
        object.__setattr__(self, "created_by", _nonblank("created_by", self.created_by))
        _ensure_aware(self.created_at, "created_at")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.schema_version != TRUTH_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported business-truth schema version: {self.schema_version}"
            )
        if self.supersedes_version is not None:
            if self.supersedes_version < 1 or self.supersedes_version >= self.version:
                raise ValueError("supersedes_version must be >=1 and lower than version")

        self._validate_unique_ids()
        self._validate_evidence_references()
        self._validate_offer_references()
        self._validate_semantic_conflicts()
        self._validate_intent_policy_conflicts()

    def _validate_unique_ids(self) -> None:
        groups = {
            "offer": [x.offer_id for x in self.offers],
            "explicit non-offer": [x.exclusion_id for x in self.explicit_non_offers],
            "intent policy": [x.policy_id for x in self.intent_policies],
            "audience": [x.audience_id for x in self.audience_policies],
            "outcome": [x.outcome_id for x in self.outcomes],
            "evidence": [x.evidence_id for x in self.evidence],
        }
        for label, values in groups.items():
            if len({_normal(v) for v in values}) != len(values):
                raise ValueError(f"duplicate {label} ID")
        protected = [_normal(x.query) for x in self.protected_queries]
        if len(set(protected)) != len(protected):
            raise ValueError("duplicate protected business query")

    def _all_bases(self) -> tuple[TruthBasis, ...]:
        bases: list[TruthBasis] = []
        bases.extend(x.basis for x in self.offers)
        bases.extend(x.basis for x in self.explicit_non_offers)
        bases.extend(x.basis for x in self.intent_policies)
        bases.extend(x.basis for x in self.audience_policies)
        bases.extend(x.basis for x in self.outcomes)
        bases.extend(x.basis for x in self.protected_queries)
        if self.geo_policy is not None:
            bases.append(self.geo_policy.basis)
        return tuple(bases)

    def _validate_evidence_references(self) -> None:
        known = {_normal(e.evidence_id) for e in self.evidence}
        for basis in self._all_bases():
            missing = [x for x in basis.evidence_ids if _normal(x) not in known]
            if missing:
                raise ValueError(f"truth basis references unknown evidence IDs: {missing}")

    def _validate_offer_references(self) -> None:
        offer_ids = {_normal(x.offer_id) for x in self.offers}
        for policy in self.intent_policies:
            missing = [x for x in policy.offer_ids if _normal(x) not in offer_ids]
            if missing:
                raise ValueError(f"intent policy references unknown offer IDs: {missing}")

    def _validate_semantic_conflicts(self) -> None:
        active_confirmed_terms: dict[str, str] = {}
        for offer in self.offers:
            if offer.offer_status is OfferStatus.ACTIVE and offer.basis.is_confirmed:
                for term in offer.searchable_names:
                    active_confirmed_terms[_normal(term)] = offer.offer_id

        for non_offer in self.explicit_non_offers:
            if not non_offer.basis.is_confirmed:
                continue
            for term in non_offer.searchable_names:
                key = _normal(term)
                if key in active_confirmed_terms:
                    raise ValueError(
                        "confirmed non-offer conflicts with confirmed active offer: "
                        f"{term!r}"
                    )

    def _validate_intent_policy_conflicts(self) -> None:
        seen: dict[tuple[IntentCategory, tuple[str, ...]], PolicyDisposition] = {}
        for policy in self.intent_policies:
            if not policy.basis.is_confirmed:
                continue
            scope = tuple(sorted(_normal(x) for x in policy.offer_ids))
            key = (policy.category, scope)
            previous = seen.get(key)
            if previous is not None and previous != policy.disposition:
                raise ValueError(
                    "conflicting confirmed intent policies for same category/scope"
                )
            seen[key] = policy.disposition

    def _confirmed_active_offers(self) -> tuple[Offer, ...]:
        return tuple(
            x
            for x in self.offers
            if x.offer_status is OfferStatus.ACTIVE and x.basis.is_confirmed
        )

    def readiness_for(self, claim: TruthClaim) -> TruthReadinessReport:
        issues: list[ReadinessIssue] = []

        if claim is TruthClaim.OFFERING_MISMATCH:
            if not self._confirmed_active_offers():
                issues.append(
                    ReadinessIssue(
                        "NO_CONFIRMED_ACTIVE_OFFERS",
                        "At least one active offer must be operator-confirmed.",
                        True,
                    )
                )
            if self.offer_catalog_completeness is not CatalogCompleteness.COMPLETE:
                confirmed_non_offers = any(x.basis.is_confirmed for x in self.explicit_non_offers)
                if not confirmed_non_offers:
                    issues.append(
                        ReadinessIssue(
                            "OFFER_CATALOG_NOT_COMPLETE",
                            "Absence from a partial/unknown offer catalog cannot prove the business does not sell something; add explicit confirmed non-offers or confirm the catalog is complete.",
                            True,
                        )
                    )
                else:
                    issues.append(
                        ReadinessIssue(
                            "OFFER_CATALOG_PARTIAL",
                            "Only explicit confirmed non-offers may support exclusion; absence from the catalog remains unknown.",
                            False,
                        )
                    )

        elif claim is TruthClaim.INTENT_MISMATCH:
            if not any(
                p.basis.is_confirmed and p.disposition is not PolicyDisposition.UNKNOWN
                for p in self.intent_policies
            ):
                issues.append(
                    ReadinessIssue(
                        "NO_CONFIRMED_INTENT_POLICY",
                        "No confirmed intent policy exists; generic assumptions such as 'jobs/free/informational are bad' are forbidden.",
                        True,
                    )
                )

        elif claim is TruthClaim.AUDIENCE_MISMATCH:
            if not any(
                p.basis.is_confirmed and p.disposition is not PolicyDisposition.UNKNOWN
                for p in self.audience_policies
            ):
                issues.append(
                    ReadinessIssue(
                        "NO_CONFIRMED_AUDIENCE_POLICY",
                        "No confirmed audience rule exists.",
                        True,
                    )
                )
            elif self.audience_catalog_completeness is not CatalogCompleteness.COMPLETE:
                issues.append(
                    ReadinessIssue(
                        "AUDIENCE_CATALOG_PARTIAL",
                        "Unlisted audiences remain unknown unless explicitly denied.",
                        False,
                    )
                )

        elif claim is TruthClaim.GEO_MISMATCH:
            if self.geo_policy is None or not self.geo_policy.basis.is_confirmed:
                issues.append(
                    ReadinessIssue(
                        "NO_CONFIRMED_GEO_POLICY",
                        "Geographic waste cannot be claimed without confirmed business service-area truth.",
                        True,
                    )
                )
            elif self.geo_policy.requirement is CustomerLocationRequirement.UNKNOWN:
                issues.append(
                    ReadinessIssue(
                        "UNKNOWN_GEO_REQUIREMENT",
                        "Business has not defined what customer/job location actually makes a lead valid.",
                        True,
                    )
                )

        elif claim is TruthClaim.CONVERSION_QUALITY:
            if not any(
                o.basis.is_confirmed and o.role is OutcomeRole.PRIMARY_BUSINESS_OUTCOME
                for o in self.outcomes
            ):
                issues.append(
                    ReadinessIssue(
                        "NO_PRIMARY_BUSINESS_OUTCOME",
                        "At least one confirmed primary business outcome is required before judging conversion quality.",
                        True,
                    )
                )

        return TruthReadinessReport(claim=claim, issues=tuple(issues))

    def confirmed_intent_policy(
        self, category: IntentCategory, *, offer_id: str | None = None
    ) -> IntentPolicy | None:
        """Resolve an explicit policy; never invent a default.

        Offer-specific rules take precedence over global rules. Missing policy returns
        None, which downstream code must treat as UNKNOWN rather than DENY.
        """

        normalized_offer = _normal(offer_id) if offer_id else None
        candidates = [
            p
            for p in self.intent_policies
            if p.category is category and p.basis.is_confirmed
        ]
        if normalized_offer is not None:
            scoped = [
                p
                for p in candidates
                if normalized_offer in {_normal(x) for x in p.offer_ids}
            ]
            if scoped:
                return sorted(scoped, key=lambda p: p.policy_id)[0]
        global_rules = [p for p in candidates if not p.offer_ids]
        return sorted(global_rules, key=lambda p: p.policy_id)[0] if global_rules else None

    def confirmed_protected_queries(self) -> tuple[ProtectedBusinessQuery, ...]:
        return tuple(x for x in self.protected_queries if x.basis.is_confirmed)

    def canonical_dict(self) -> dict[str, Any]:
        """Deterministic semantic serialization used for audit fingerprints."""

        def convert(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, datetime):
                return value.isoformat()
            if is_dataclass(value):
                return {f.name: convert(getattr(value, f.name)) for f in fields(value)}
            if isinstance(value, tuple):
                return [convert(x) for x in value]
            if isinstance(value, list):
                return [convert(x) for x in value]
            if isinstance(value, dict):
                return {str(k): convert(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
            return value

        # Order-insensitive collections are sorted by stable IDs so equivalent
        # snapshots hash identically even if a UI submits items in another order.
        payload = {
            "schema_version": self.schema_version,
            "business_id": self.business_id,
            "business_name": self.business_name,
            "version": self.version,
            "supersedes_version": self.supersedes_version,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "offer_catalog_completeness": self.offer_catalog_completeness,
            "audience_catalog_completeness": self.audience_catalog_completeness,
            "offers": tuple(sorted(self.offers, key=lambda x: _normal(x.offer_id))),
            "explicit_non_offers": tuple(sorted(self.explicit_non_offers, key=lambda x: _normal(x.exclusion_id))),
            "intent_policies": tuple(sorted(self.intent_policies, key=lambda x: _normal(x.policy_id))),
            "audience_policies": tuple(sorted(self.audience_policies, key=lambda x: _normal(x.audience_id))),
            "geo_policy": self.geo_policy,
            "outcomes": tuple(sorted(self.outcomes, key=lambda x: _normal(x.outcome_id))),
            "evidence": tuple(sorted(self.evidence, key=lambda x: _normal(x.evidence_id))),
        }
        result = convert(payload)

        # Alias/evidence-id/offer-id ordering is semantically irrelevant.
        for offer in result["offers"]:
            offer["aliases"] = sorted(offer["aliases"], key=_normal)
            offer["basis"]["evidence_ids"] = sorted(offer["basis"]["evidence_ids"], key=_normal)
        for item in result["explicit_non_offers"]:
            item["aliases"] = sorted(item["aliases"], key=_normal)
            item["basis"]["evidence_ids"] = sorted(item["basis"]["evidence_ids"], key=_normal)
        for item in result["intent_policies"]:
            item["offer_ids"] = sorted(item["offer_ids"], key=_normal)
            item["basis"]["evidence_ids"] = sorted(item["basis"]["evidence_ids"], key=_normal)
        for item in result["audience_policies"]:
            item["aliases"] = sorted(item["aliases"], key=_normal)
            item["basis"]["evidence_ids"] = sorted(item["basis"]["evidence_ids"], key=_normal)
        for item in result["outcomes"]:
            item["basis"]["evidence_ids"] = sorted(item["basis"]["evidence_ids"], key=_normal)
        if result["geo_policy"] is not None:
            result["geo_policy"]["included_areas"] = sorted(
                result["geo_policy"]["included_areas"], key=lambda x: _normal(x["area_id"])
            )
            result["geo_policy"]["excluded_areas"] = sorted(
                result["geo_policy"]["excluded_areas"], key=lambda x: _normal(x["area_id"])
            )
            result["geo_policy"]["basis"]["evidence_ids"] = sorted(
                result["geo_policy"]["basis"]["evidence_ids"], key=_normal
            )
        return result

    @property
    def fingerprint_sha256(self) -> str:
        encoded = json.dumps(
            self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
