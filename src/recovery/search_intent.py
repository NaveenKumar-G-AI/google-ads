from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol

from .business_truth import (
    BusinessTruthSnapshot,
    IntentCategory,
    OfferStatus,
    PolicyDisposition,
)

INTENT_SCHEMA_VERSION = 1


def _confidence(value: Decimal | str | float | int) -> Decimal:
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if result < 0 or result > 1:
        raise ValueError("confidence must be in [0, 1]")
    return result


def normalize_query(text: str) -> str:
    """Conservative normalization for comparison, never a replacement for raw text.

    NFKC collapses compatibility variants (for example full-width Latin characters)
    while preserving the original query separately for audit/replay. We intentionally
    do not stem, translate, remove accents, or drop punctuation because those steps can
    change meaning in names, locations, SKUs, and non-English queries.
    """

    if not isinstance(text, str):
        raise TypeError("query must be a string")
    normalized = " ".join(unicodedata.normalize("NFKC", text).strip().split())
    if not normalized:
        raise ValueError("query cannot be blank")
    return normalized.casefold()


class AssessmentStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


class FitDisposition(str, Enum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class FitReasonCode(str, Enum):
    EXPLICIT_NON_OFFER = "explicit_non_offer"
    DENIED_INTENT = "denied_intent"
    ALLOWED_INTENT = "allowed_intent"
    DIRECT_CONFIRMED_OFFER = "direct_confirmed_offer"
    CONDITIONAL_INTENT = "conditional_intent"
    MISSING_INTENT_POLICY = "missing_intent_policy"
    AMBIGUOUS_SEMANTICS = "ambiguous_semantics"
    INSUFFICIENT_SEMANTICS = "insufficient_semantics"
    LOW_SEMANTIC_CONFIDENCE = "low_semantic_confidence"
    UNKNOWN_MODEL_REFERENCE = "unknown_model_reference"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNRESOLVED_SIGNAL = "unresolved_signal"
    NO_DECISIVE_EVIDENCE = "no_decisive_evidence"


@dataclass(frozen=True, slots=True)
class IntentHypothesis:
    category: IntentCategory
    confidence: Decimal
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(x.strip() for x in self.evidence if x.strip()))


@dataclass(frozen=True, slots=True)
class OfferHypothesis:
    offer_id: str
    confidence: Decimal
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.offer_id.strip():
            raise ValueError("offer_id cannot be blank")
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(x.strip() for x in self.evidence if x.strip()))


@dataclass(frozen=True, slots=True)
class NonOfferHypothesis:
    exclusion_id: str
    confidence: Decimal
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.exclusion_id.strip():
            raise ValueError("exclusion_id cannot be blank")
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(x.strip() for x in self.evidence if x.strip()))


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    """Meaning-only interpretation of a search query.

    This object intentionally contains no spend, clicks, conversions, CPA, or revenue.
    Semantic interpretation must not be biased by downstream performance.
    `confidence` is interpreter confidence, not a calibrated statistical probability.
    """

    raw_query: str
    normalized_query: str
    status: AssessmentStatus
    language_code: str | None
    intents: tuple[IntentHypothesis, ...]
    offer_candidates: tuple[OfferHypothesis, ...]
    non_offer_candidates: tuple[NonOfferHypothesis, ...]
    unresolved_signals: tuple[str, ...]
    ambiguity_reason: str | None
    interpreter: str
    interpreter_version: str
    schema_version: int = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INTENT_SCHEMA_VERSION:
            raise ValueError(f"unsupported intent schema version: {self.schema_version}")
        expected = normalize_query(self.raw_query)
        if self.normalized_query != expected:
            raise ValueError("normalized_query must equal normalize_query(raw_query)")
        if not self.interpreter.strip() or not self.interpreter_version.strip():
            raise ValueError("interpreter and interpreter_version are required")
        if self.language_code is not None and not self.language_code.strip():
            raise ValueError("language_code cannot be blank")
        if self.status is AssessmentStatus.AMBIGUOUS:
            if self.ambiguity_reason is None or not self.ambiguity_reason.strip():
                raise ValueError("ambiguous assessment requires ambiguity_reason")
        if self.status is not AssessmentStatus.AMBIGUOUS and self.ambiguity_reason:
            raise ValueError("ambiguity_reason is only valid for ambiguous assessments")

        categories = [x.category for x in self.intents]
        if len(categories) != len(set(categories)):
            raise ValueError("intent categories must be unique within an assessment")
        offer_ids = [x.offer_id.casefold() for x in self.offer_candidates]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("offer candidates must be unique")
        exclusion_ids = [x.exclusion_id.casefold() for x in self.non_offer_candidates]
        if len(exclusion_ids) != len(set(exclusion_ids)):
            raise ValueError("non-offer candidates must be unique")
        signals = tuple(x.strip() for x in self.unresolved_signals if x.strip())
        if len({x.casefold() for x in signals}) != len(signals):
            raise ValueError("unresolved_signals must be unique")
        object.__setattr__(self, "unresolved_signals", signals)


class SearchIntentInterpreter(Protocol):
    def interpret(
        self, query: str, truth: BusinessTruthSnapshot
    ) -> SemanticAssessment: ...


@dataclass(frozen=True, slots=True)
class FitReason:
    code: FitReasonCode
    message: str
    decisive: bool


@dataclass(frozen=True, slots=True)
class BusinessFitDecision:
    raw_query: str
    disposition: FitDisposition
    semantic_status: AssessmentStatus
    truth_fingerprint: str
    reasons: tuple[FitReason, ...]
    decisive_intents: tuple[IntentCategory, ...] = ()
    decisive_offer_ids: tuple[str, ...] = ()
    decisive_non_offer_ids: tuple[str, ...] = ()

    @property
    def can_support_exclusion_candidate(self) -> bool:
        """Semantic eligibility only; Phase 4 must still add performance/evidence checks."""

        return self.disposition is FitDisposition.IRRELEVANT


class BusinessFitEvaluator:
    """Deterministically compare semantic meaning with confirmed business truth.

    The evaluator is deliberately asymmetric: it is easy to return UNKNOWN and hard
    to return IRRELEVANT. No negative keyword action is created here.
    """

    def __init__(self, *, minimum_confidence: Decimal = Decimal("0.95")) -> None:
        self.minimum_confidence = _confidence(minimum_confidence)

    def evaluate(
        self, assessment: SemanticAssessment, truth: BusinessTruthSnapshot
    ) -> BusinessFitDecision:
        reasons: list[FitReason] = []
        fingerprint = truth.fingerprint_sha256

        known_offers = {x.offer_id.casefold(): x for x in truth.offers}
        known_non_offers = {x.exclusion_id.casefold(): x for x in truth.explicit_non_offers}

        unknown_offer_refs = [
            x.offer_id for x in assessment.offer_candidates if x.offer_id.casefold() not in known_offers
        ]
        unknown_nonoffer_refs = [
            x.exclusion_id
            for x in assessment.non_offer_candidates
            if x.exclusion_id.casefold() not in known_non_offers
        ]
        if unknown_offer_refs or unknown_nonoffer_refs:
            reasons.append(
                FitReason(
                    FitReasonCode.UNKNOWN_MODEL_REFERENCE,
                    "Interpreter referenced business IDs that do not exist in this truth snapshot.",
                    True,
                )
            )
            return self._decision(
                assessment, fingerprint, FitDisposition.UNKNOWN, reasons
            )

        if assessment.status is AssessmentStatus.AMBIGUOUS:
            reasons.append(
                FitReason(
                    FitReasonCode.AMBIGUOUS_SEMANTICS,
                    assessment.ambiguity_reason or "Query meaning is ambiguous.",
                    True,
                )
            )
            return self._decision(assessment, fingerprint, FitDisposition.UNKNOWN, reasons)

        if assessment.status is AssessmentStatus.INSUFFICIENT:
            reasons.append(
                FitReason(
                    FitReasonCode.INSUFFICIENT_SEMANTICS,
                    "Interpreter could not establish enough meaning to judge business fit.",
                    True,
                )
            )
            return self._decision(assessment, fingerprint, FitDisposition.UNKNOWN, reasons)

        if assessment.unresolved_signals:
            reasons.append(
                FitReason(
                    FitReasonCode.UNRESOLVED_SIGNAL,
                    "Unresolved query modifier/entity could change whether this search is valuable.",
                    True,
                )
            )
            return self._decision(assessment, fingerprint, FitDisposition.UNKNOWN, reasons)

        high_offers = [
            x for x in assessment.offer_candidates if x.confidence >= self.minimum_confidence
        ]
        high_nonoffers = [
            x for x in assessment.non_offer_candidates if x.confidence >= self.minimum_confidence
        ]
        high_intents = [
            x for x in assessment.intents if x.confidence >= self.minimum_confidence
        ]

        low_only = bool(
            (assessment.offer_candidates or assessment.non_offer_candidates or assessment.intents)
            and not (high_offers or high_nonoffers or high_intents)
        )
        if low_only:
            reasons.append(
                FitReason(
                    FitReasonCode.LOW_SEMANTIC_CONFIDENCE,
                    "Semantic evidence exists but does not meet the configured decision threshold.",
                    True,
                )
            )
            return self._decision(assessment, fingerprint, FitDisposition.UNKNOWN, reasons)

        confirmed_active_offer_ids = {
            x.offer_id.casefold()
            for x in truth.offers
            if x.offer_status is OfferStatus.ACTIVE and x.basis.is_confirmed
        }
        confirmed_non_offer_ids = {
            x.exclusion_id.casefold()
            for x in truth.explicit_non_offers
            if x.basis.is_confirmed
        }

        decisive_offers = [
            x.offer_id
            for x in high_offers
            if x.offer_id.casefold() in confirmed_active_offer_ids
        ]
        decisive_nonoffers = [
            x.exclusion_id
            for x in high_nonoffers
            if x.exclusion_id.casefold() in confirmed_non_offer_ids
        ]

        # Simultaneously matching a confirmed offer and explicit non-offer is too risky
        # to resolve automatically even if each individual hypothesis is high-confidence.
        if decisive_offers and decisive_nonoffers:
            reasons.append(
                FitReason(
                    FitReasonCode.CONFLICTING_EVIDENCE,
                    "Query has high-confidence evidence for both a valid offer and an explicit non-offer.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.UNKNOWN,
                reasons,
                offer_ids=decisive_offers,
                non_offer_ids=decisive_nonoffers,
            )

        if decisive_nonoffers:
            reasons.append(
                FitReason(
                    FitReasonCode.EXPLICIT_NON_OFFER,
                    "Query confidently requests an item/service the business explicitly confirmed it does not offer.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.IRRELEVANT,
                reasons,
                non_offer_ids=decisive_nonoffers,
            )

        # If a query maps to one confirmed offer, offer-scoped intent policies may apply.
        # Multiple offers are not collapsed to one; only global policies may safely decide.
        scoped_offer_id = decisive_offers[0] if len(decisive_offers) == 1 else None
        denied: list[IntentCategory] = []
        allowed: list[IntentCategory] = []
        conditional: list[IntentCategory] = []
        missing: list[IntentCategory] = []

        for hypothesis in high_intents:
            policy = truth.confirmed_intent_policy(
                hypothesis.category, offer_id=scoped_offer_id
            )
            if policy is None or policy.disposition is PolicyDisposition.UNKNOWN:
                missing.append(hypothesis.category)
            elif policy.disposition is PolicyDisposition.DENY:
                denied.append(hypothesis.category)
            elif policy.disposition is PolicyDisposition.ALLOW:
                allowed.append(hypothesis.category)
            elif policy.disposition is PolicyDisposition.CONDITIONAL:
                conditional.append(hypothesis.category)

        if denied and allowed:
            reasons.append(
                FitReason(
                    FitReasonCode.CONFLICTING_EVIDENCE,
                    "The query contains separate high-confidence intents with conflicting confirmed business policies.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.CONDITIONAL,
                reasons,
                intents=(*denied, *allowed),
                offer_ids=decisive_offers,
            )

        if denied and (conditional or missing):
            reasons.append(
                FitReason(
                    FitReasonCode.CONFLICTING_EVIDENCE,
                    "A denied intent is present, but another material intent is conditional or undefined.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.CONDITIONAL,
                reasons,
                intents=(*denied, *conditional, *missing),
                offer_ids=decisive_offers,
            )

        if denied:
            reasons.append(
                FitReason(
                    FitReasonCode.DENIED_INTENT,
                    "Query has a high-confidence intent that the business explicitly denies for acquisition.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.IRRELEVANT,
                reasons,
                intents=denied,
                offer_ids=decisive_offers,
            )

        if conditional:
            reasons.append(
                FitReason(
                    FitReasonCode.CONDITIONAL_INTENT,
                    "Confirmed business policy requires contextual review for this intent.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.CONDITIONAL,
                reasons,
                intents=conditional,
                offer_ids=decisive_offers,
            )

        if missing:
            reasons.append(
                FitReason(
                    FitReasonCode.MISSING_INTENT_POLICY,
                    "Business truth has no confirmed policy for a material intent in this query.",
                    True,
                )
            )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.UNKNOWN,
                reasons,
                intents=missing,
                offer_ids=decisive_offers,
            )

        if decisive_offers:
            reasons.append(
                FitReason(
                    FitReasonCode.DIRECT_CONFIRMED_OFFER,
                    "Query confidently maps to an active operator-confirmed offer and no conflicting denied/unknown intent was found.",
                    True,
                )
            )
            if allowed:
                reasons.append(
                    FitReason(
                        FitReasonCode.ALLOWED_INTENT,
                        "Material query intent is explicitly allowed by confirmed business policy.",
                        False,
                    )
                )
            return self._decision(
                assessment,
                fingerprint,
                FitDisposition.RELEVANT,
                reasons,
                intents=allowed,
                offer_ids=decisive_offers,
            )

        if allowed:
            # An allowed generic intent without a known offer match does not prove the
            # underlying requested product/service belongs to the business.
            reasons.append(
                FitReason(
                    FitReasonCode.ALLOWED_INTENT,
                    "Intent itself is allowed, but the requested offering is not confidently resolved.",
                    False,
                )
            )

        reasons.append(
            FitReason(
                FitReasonCode.NO_DECISIVE_EVIDENCE,
                "No confirmed business fact is strong enough to decide relevance.",
                True,
            )
        )
        return self._decision(assessment, fingerprint, FitDisposition.UNKNOWN, reasons)

    @staticmethod
    def _decision(
        assessment: SemanticAssessment,
        fingerprint: str,
        disposition: FitDisposition,
        reasons: list[FitReason],
        *,
        intents: tuple[IntentCategory, ...] | list[IntentCategory] = (),
        offer_ids: tuple[str, ...] | list[str] = (),
        non_offer_ids: tuple[str, ...] | list[str] = (),
    ) -> BusinessFitDecision:
        return BusinessFitDecision(
            raw_query=assessment.raw_query,
            disposition=disposition,
            semantic_status=assessment.status,
            truth_fingerprint=fingerprint,
            reasons=tuple(reasons),
            decisive_intents=tuple(dict.fromkeys(intents)),
            decisive_offer_ids=tuple(dict.fromkeys(offer_ids)),
            decisive_non_offer_ids=tuple(dict.fromkeys(non_offer_ids)),
        )


def assessment_from_mapping(
    payload: Mapping[str, Any], truth: BusinessTruthSnapshot
) -> SemanticAssessment:
    """Strict boundary for future model/API output.

    Rejects hallucinated business IDs, unknown enum labels, malformed confidence
    values, duplicate hypotheses, and normalized-query drift before those values can
    influence a financial finding.
    """

    if int(payload.get("schema_version", INTENT_SCHEMA_VERSION)) != INTENT_SCHEMA_VERSION:
        raise ValueError("unsupported intent schema version")

    raw_query = str(payload["raw_query"])
    normalized = str(payload.get("normalized_query", normalize_query(raw_query)))
    status = AssessmentStatus(str(payload["status"]))

    intents = tuple(
        IntentHypothesis(
            category=IntentCategory(str(item["category"])),
            confidence=_confidence(item["confidence"]),
            evidence=tuple(str(x) for x in item.get("evidence", ())),
        )
        for item in payload.get("intents", ())
    )
    offers = tuple(
        OfferHypothesis(
            offer_id=str(item["offer_id"]),
            confidence=_confidence(item["confidence"]),
            evidence=tuple(str(x) for x in item.get("evidence", ())),
        )
        for item in payload.get("offer_candidates", ())
    )
    non_offers = tuple(
        NonOfferHypothesis(
            exclusion_id=str(item["exclusion_id"]),
            confidence=_confidence(item["confidence"]),
            evidence=tuple(str(x) for x in item.get("evidence", ())),
        )
        for item in payload.get("non_offer_candidates", ())
    )

    known_offer_ids = {x.offer_id.casefold() for x in truth.offers}
    known_nonoffer_ids = {x.exclusion_id.casefold() for x in truth.explicit_non_offers}
    hallucinated_offers = [x.offer_id for x in offers if x.offer_id.casefold() not in known_offer_ids]
    hallucinated_nonoffers = [
        x.exclusion_id for x in non_offers if x.exclusion_id.casefold() not in known_nonoffer_ids
    ]
    if hallucinated_offers or hallucinated_nonoffers:
        raise ValueError(
            "semantic output referenced unknown business IDs: "
            f"offers={hallucinated_offers}, non_offers={hallucinated_nonoffers}"
        )

    return SemanticAssessment(
        raw_query=raw_query,
        normalized_query=normalized,
        status=status,
        language_code=(
            str(payload["language_code"]) if payload.get("language_code") is not None else None
        ),
        intents=intents,
        offer_candidates=offers,
        non_offer_candidates=non_offers,
        unresolved_signals=tuple(str(x) for x in payload.get("unresolved_signals", ())),
        ambiguity_reason=(
            str(payload["ambiguity_reason"])
            if payload.get("ambiguity_reason") is not None
            else None
        ),
        interpreter=str(payload["interpreter"]),
        interpreter_version=str(payload["interpreter_version"]),
        schema_version=INTENT_SCHEMA_VERSION,
    )


def semantic_context_for_model(truth: BusinessTruthSnapshot) -> dict[str, Any]:
    """Minimum business context a future semantic model may use.

    We intentionally exclude spend/performance metrics and unconfirmed facts. The
    model receives stable IDs, confirmed active offerings/non-offerings, and confirmed
    intent policies. BusinessFitEvaluator remains the authority for policy resolution.
    """

    offers = [
        {
            "offer_id": x.offer_id,
            "name": x.name,
            "aliases": list(x.aliases),
            "description": x.description,
        }
        for x in truth.offers
        if x.offer_status is OfferStatus.ACTIVE and x.basis.is_confirmed
    ]
    non_offers = [
        {
            "exclusion_id": x.exclusion_id,
            "name": x.name,
            "aliases": list(x.aliases),
            "reason": x.reason,
        }
        for x in truth.explicit_non_offers
        if x.basis.is_confirmed
    ]
    policies = [
        {
            "policy_id": x.policy_id,
            "category": x.category.value,
            "disposition": x.disposition.value,
            "offer_ids": list(x.offer_ids),
            "reason": x.reason,
            "condition": x.condition,
        }
        for x in truth.intent_policies
        if x.basis.is_confirmed and x.disposition is not PolicyDisposition.UNKNOWN
    ]
    return {
        "business_id": truth.business_id,
        "business_name": truth.business_name,
        "truth_version": truth.version,
        "truth_fingerprint": truth.fingerprint_sha256,
        "offers": offers,
        "explicit_non_offers": non_offers,
        "intent_policies": policies,
        "forbidden_inputs": [
            "spend",
            "clicks",
            "conversions",
            "conversion_value",
            "cpa",
            "roas",
        ],
    }


class ConservativeLexicalInterpreter:
    """Deterministic smoke-test interpreter, not the production semantic AI.

    It only emits a category when an explicit high-precision lexical signal appears,
    and exact/phrase business-name matches. This makes the Phase-3 decision pipeline
    executable and testable without pretending regex is general semantic intelligence.
    """

    name = "conservative-lexical-baseline"
    version = "1.0"

    _SIGNALS: tuple[tuple[IntentCategory, tuple[str, ...]], ...] = (
        (IntentCategory.EMPLOYMENT, ("jobs", "job vacancy", "job vacancies", "careers")),
        (IntentCategory.DIY, ("diy", "do it yourself")),
        (IntentCategory.FREE, ("free",)),
        (IntentCategory.SECOND_HAND, ("second hand", "second-hand", "used")),
        (IntentCategory.RENTAL, ("rental", "rent")),
        (IntentCategory.TRAINING, ("course", "training", "certification")),
    )

    @staticmethod
    def _contains_phrase(normalized_query: str, phrase: str) -> bool:
        escaped = re.escape(normalize_query(phrase))
        return re.search(rf"(?<!\w){escaped}(?!\w)", normalized_query, flags=re.UNICODE) is not None

    def interpret(
        self, query: str, truth: BusinessTruthSnapshot
    ) -> SemanticAssessment:
        normalized = normalize_query(query)
        intents: list[IntentHypothesis] = []
        offers: list[OfferHypothesis] = []
        nonoffers: list[NonOfferHypothesis] = []

        for category, phrases in self._SIGNALS:
            hits = tuple(p for p in phrases if self._contains_phrase(normalized, p))
            if hits:
                intents.append(IntentHypothesis(category, Decimal("0.99"), hits))

        for offer in truth.offers:
            if not (offer.basis.is_confirmed and offer.offer_status is OfferStatus.ACTIVE):
                continue
            hits = tuple(
                name
                for name in offer.searchable_names
                if self._contains_phrase(normalized, name)
            )
            if hits:
                offers.append(OfferHypothesis(offer.offer_id, Decimal("0.99"), hits))

        for item in truth.explicit_non_offers:
            if not item.basis.is_confirmed:
                continue
            hits = tuple(
                name
                for name in item.searchable_names
                if self._contains_phrase(normalized, name)
            )
            if hits:
                nonoffers.append(NonOfferHypothesis(item.exclusion_id, Decimal("0.99"), hits))

        status = (
            AssessmentStatus.RESOLVED
            if intents or offers or nonoffers
            else AssessmentStatus.INSUFFICIENT
        )
        return SemanticAssessment(
            raw_query=query,
            normalized_query=normalized,
            status=status,
            language_code=None,
            intents=tuple(intents),
            offer_candidates=tuple(offers),
            non_offer_candidates=tuple(nonoffers),
            unresolved_signals=(),
            ambiguity_reason=None,
            interpreter=self.name,
            interpreter_version=self.version,
        )
