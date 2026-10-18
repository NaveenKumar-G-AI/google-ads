from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from .business_truth import BusinessTruthSnapshot
from .db.canonical import canonical_payload, payload_sha256
from .search_intent import (
    BusinessFitDecision,
    BusinessFitEvaluator,
    ConservativeLexicalInterpreter,
    FitDisposition,
    SemanticAssessment,
)
from .semantic_ai import CandidateSemanticAI, SemanticAIError
from .semantic_eval import wilson_upper

PHASE14_SCHEMA_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha_hex(value: str, name: str) -> str:
    value = str(value).strip().lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be SHA-256 hex")
    return value


class RouteSource(str, Enum):
    RELEASED_AI = "released_ai"
    BASELINE = "baseline"


class FallbackReason(str, Enum):
    NO_ACTIVE_RELEASE = "no_active_release"
    RELEASE_TRIPPED = "release_tripped"
    PROVIDER_ERROR = "provider_error"
    RELEASE_IDENTITY_MISMATCH = "release_identity_mismatch"
    PROVIDER_VERSION_MISMATCH = "provider_version_mismatch"
    LANGUAGE_UNAPPROVED = "language_unapproved"
    LANGUAGE_UNKNOWN = "language_unknown"
    CONFIDENCE_MISSING = "confidence_missing"
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    CANDIDATE_ABSTAINED = "candidate_abstained"


@dataclass(frozen=True, slots=True)
class ActiveSemanticRelease:
    release_definition_id: str
    release_fingerprint: str
    provider: str
    model: str
    provider_model_version: str
    thinking_level: str
    prompt_version: str
    candidate_contract_fingerprint: str
    semantic_schema_version: int
    selected_confidence_threshold: Decimal
    approved_languages: tuple[str, ...]
    tripped: bool = False
    trip_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.release_definition_id.strip():
            raise ValueError("release_definition_id is required")
        _sha_hex(self.release_fingerprint, "release_fingerprint")
        _sha_hex(self.candidate_contract_fingerprint, "candidate_contract_fingerprint")
        for name in ("provider", "model", "provider_model_version", "thinking_level", "prompt_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not Decimal(0) <= self.selected_confidence_threshold <= Decimal(1):
            raise ValueError("selected_confidence_threshold must be in [0,1]")
        langs = tuple(sorted({str(x).strip().casefold() for x in self.approved_languages if str(x).strip()}))
        if not langs:
            raise ValueError("approved_languages cannot be empty")
        object.__setattr__(self, "approved_languages", langs)
        if self.tripped and not (self.trip_reason and self.trip_reason.strip()):
            raise ValueError("tripped release requires trip_reason")


class SemanticReleaseResolver(Protocol):
    def active_release(self) -> ActiveSemanticRelease | None: ...


@dataclass(frozen=True, slots=True)
class SemanticRouteDecision:
    raw_query: str
    assessment: SemanticAssessment
    fit: BusinessFitDecision
    baseline_assessment: SemanticAssessment
    baseline_fit: BusinessFitDecision
    route_source: RouteSource
    fallback_reason: FallbackReason | None
    release_fingerprint: str | None
    release_definition_id: str | None
    declared_confidence: Decimal | None
    provider_model_version: str | None
    candidate_assessment: SemanticAssessment | None
    candidate_fit: BusinessFitDecision | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.assessment.raw_query != self.raw_query or self.baseline_assessment.raw_query != self.raw_query:
            raise ValueError("route decision query mismatch")
        if self.fit.raw_query != self.raw_query or self.baseline_fit.raw_query != self.raw_query:
            raise ValueError("route decision fit query mismatch")
        if self.route_source is RouteSource.RELEASED_AI:
            if self.fallback_reason is not None:
                raise ValueError("released AI route cannot have fallback_reason")
            if self.release_fingerprint is None or self.release_definition_id is None or self.candidate_assessment is None or self.candidate_fit is None:
                raise ValueError("released AI route requires release/candidate evidence")
        else:
            if self.fallback_reason is None:
                raise ValueError("baseline fallback requires a reason")
        if self.release_fingerprint is not None:
            _sha_hex(self.release_fingerprint, "release_fingerprint")

    @property
    def fingerprint_sha256(self) -> str:
        return payload_sha256({"schema_version": PHASE14_SCHEMA_VERSION, **canonical_payload(self)})


class ProductionSemanticRouter:
    """Fail-closed semantic router for one exact promoted release.

    Financial/performance data is not accepted by this API. The candidate sees only
    the raw query and Business Truth through CandidateSemanticAI.
    """

    def __init__(
        self,
        *,
        candidate: CandidateSemanticAI,
        release_resolver: SemanticReleaseResolver,
        baseline: ConservativeLexicalInterpreter | None = None,
        fit_evaluator: BusinessFitEvaluator | None = None,
        on_hard_release_failure: Callable[[ActiveSemanticRelease, str], None] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.candidate = candidate
        self.release_resolver = release_resolver
        self.baseline = baseline or ConservativeLexicalInterpreter()
        self.fit_evaluator = fit_evaluator or BusinessFitEvaluator()
        self.on_hard_release_failure = on_hard_release_failure
        self.clock = clock

    def route(self, *, query: str, truth: BusinessTruthSnapshot) -> SemanticRouteDecision:
        return self.route_many(queries=(query,), truth=truth)[0]

    def route_many(
        self, *, queries: Sequence[str], truth: BusinessTruthSnapshot
    ) -> tuple[SemanticRouteDecision, ...]:
        if not queries:
            return ()
        baseline_assessments = tuple(self.baseline.interpret(q, truth) for q in queries)
        baseline_fits = tuple(self.fit_evaluator.evaluate(a, truth) for a in baseline_assessments)
        release = self.release_resolver.active_release()
        if release is None:
            return tuple(
                self._baseline(q, a, f, FallbackReason.NO_ACTIVE_RELEASE, None)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )
        if release.tripped:
            return tuple(
                self._baseline(q, a, f, FallbackReason.RELEASE_TRIPPED, release)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )

        # Before calling the provider, verify every locally knowable part of the release identity.
        if (
            release.model != self.candidate.config.model
            or release.thinking_level != self.candidate.config.thinking_level.value
            or release.prompt_version != self.candidate.prompt_version
            or release.candidate_contract_fingerprint != self.candidate.contract_fingerprint
        ):
            self._trip(release, "configured candidate differs from promoted release identity")
            return tuple(
                self._baseline(q, a, f, FallbackReason.RELEASE_IDENTITY_MISMATCH, release)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )

        try:
            result = self.candidate.interpret_many(queries, truth)
        except SemanticAIError:
            return tuple(
                self._baseline(q, a, f, FallbackReason.PROVIDER_ERROR, release)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )

        if (
            result.provider != release.provider
            or result.model != release.model
            or result.candidate_contract_fingerprint != release.candidate_contract_fingerprint
        ):
            self._trip(release, "runtime provider/model/contract differs from promoted release")
            return tuple(
                self._baseline(q, a, f, FallbackReason.RELEASE_IDENTITY_MISMATCH, release)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )
        if result.provider_model_version != release.provider_model_version:
            self._trip(
                release,
                f"provider revision changed from {release.provider_model_version!r} to {result.provider_model_version!r}",
            )
            return tuple(
                self._baseline(q, a, f, FallbackReason.PROVIDER_VERSION_MISMATCH, release)
                for q, a, f in zip(queries, baseline_assessments, baseline_fits, strict=True)
            )

        decisions: list[SemanticRouteDecision] = []
        approved = set(release.approved_languages)
        for query, base_a, base_f, candidate_a, confidence in zip(
            queries, baseline_assessments, baseline_fits, result.assessments, result.declared_confidences, strict=True
        ):
            candidate_fit = self.fit_evaluator.evaluate(candidate_a, truth)
            language = candidate_a.language_code.casefold() if candidate_a.language_code else None
            if language is None:
                decisions.append(self._baseline(
                    query, base_a, base_f, FallbackReason.LANGUAGE_UNKNOWN, release,
                    candidate_a=candidate_a, candidate_fit=candidate_fit, confidence=confidence,
                    provider_version=result.provider_model_version,
                ))
            elif language not in approved:
                decisions.append(self._baseline(
                    query, base_a, base_f, FallbackReason.LANGUAGE_UNAPPROVED, release,
                    candidate_a=candidate_a, candidate_fit=candidate_fit, confidence=confidence,
                    provider_version=result.provider_model_version,
                ))
            elif confidence is None:
                decisions.append(self._baseline(
                    query, base_a, base_f, FallbackReason.CONFIDENCE_MISSING, release,
                    candidate_a=candidate_a, candidate_fit=candidate_fit, confidence=confidence,
                    provider_version=result.provider_model_version,
                ))
            elif confidence < release.selected_confidence_threshold:
                decisions.append(self._baseline(
                    query, base_a, base_f, FallbackReason.CONFIDENCE_BELOW_THRESHOLD, release,
                    candidate_a=candidate_a, candidate_fit=candidate_fit, confidence=confidence,
                    provider_version=result.provider_model_version,
                ))
            elif candidate_fit.disposition is FitDisposition.UNKNOWN:
                decisions.append(self._baseline(
                    query, base_a, base_f, FallbackReason.CANDIDATE_ABSTAINED, release,
                    candidate_a=candidate_a, candidate_fit=candidate_fit, confidence=confidence,
                    provider_version=result.provider_model_version,
                ))
            else:
                decisions.append(SemanticRouteDecision(
                    raw_query=query,
                    assessment=candidate_a,
                    fit=candidate_fit,
                    baseline_assessment=base_a,
                    baseline_fit=base_f,
                    route_source=RouteSource.RELEASED_AI,
                    fallback_reason=None,
                    release_fingerprint=release.release_fingerprint,
                    release_definition_id=release.release_definition_id,
                    declared_confidence=confidence,
                    provider_model_version=result.provider_model_version,
                    candidate_assessment=candidate_a,
                    candidate_fit=candidate_fit,
                    created_at=self.clock(),
                ))
        return tuple(decisions)

    def _baseline(
        self,
        query: str,
        assessment: SemanticAssessment,
        fit: BusinessFitDecision,
        reason: FallbackReason,
        release: ActiveSemanticRelease | None,
        *,
        candidate_a: SemanticAssessment | None = None,
        candidate_fit: BusinessFitDecision | None = None,
        confidence: Decimal | None = None,
        provider_version: str | None = None,
    ) -> SemanticRouteDecision:
        return SemanticRouteDecision(
            raw_query=query,
            assessment=assessment,
            fit=fit,
            baseline_assessment=assessment,
            baseline_fit=fit,
            route_source=RouteSource.BASELINE,
            fallback_reason=reason,
            release_fingerprint=release.release_fingerprint if release else None,
            release_definition_id=release.release_definition_id if release else None,
            declared_confidence=confidence,
            provider_model_version=provider_version,
            candidate_assessment=candidate_a,
            candidate_fit=candidate_fit,
            created_at=self.clock(),
        )

    def _trip(self, release: ActiveSemanticRelease, reason: str) -> None:
        if self.on_hard_release_failure is not None:
            self.on_hard_release_failure(release, reason)


@dataclass(frozen=True, slots=True)
class ReviewedProductionDecision:
    decision_fingerprint: str
    release_fingerprint: str
    route_source: RouteSource
    predicted_disposition: FitDisposition
    gold_disposition: FitDisposition

    def __post_init__(self) -> None:
        _sha_hex(self.decision_fingerprint, "decision_fingerprint")
        _sha_hex(self.release_fingerprint, "release_fingerprint")

    @property
    def actionable_irrelevant(self) -> bool:
        return self.route_source is RouteSource.RELEASED_AI and self.predicted_disposition is FitDisposition.IRRELEVANT

    @property
    def unsafe_false_exclusion(self) -> bool:
        return self.actionable_irrelevant and self.gold_disposition is not FitDisposition.IRRELEVANT


@dataclass(frozen=True, slots=True)
class DriftPolicy:
    minimum_reviewed_cases: int = 100
    minimum_actionable_irrelevant_cases: int = 30
    maximum_unsafe_false_exclusions: int = 0
    maximum_wilson_upper_unsafe_rate: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        if self.minimum_reviewed_cases < 1 or self.minimum_actionable_irrelevant_cases < 1:
            raise ValueError("drift minimum supports must be positive")
        if self.maximum_unsafe_false_exclusions < 0:
            raise ValueError("maximum_unsafe_false_exclusions cannot be negative")
        if not Decimal(0) <= self.maximum_wilson_upper_unsafe_rate <= Decimal(1):
            raise ValueError("maximum_wilson_upper_unsafe_rate must be in [0,1]")

    @property
    def fingerprint_sha256(self) -> str:
        return payload_sha256({"phase": 14, "policy": canonical_payload(self)})


@dataclass(frozen=True, slots=True)
class DriftEvaluation:
    release_fingerprint: str
    reviewed_cases: int
    actionable_irrelevant_cases: int
    unsafe_false_exclusions: int
    wilson_upper_unsafe_rate: Decimal | None
    sufficient_evidence: bool
    tripped: bool
    reasons: tuple[str, ...]
    policy_fingerprint: str

    @property
    def fingerprint_sha256(self) -> str:
        return payload_sha256({"schema_version": PHASE14_SCHEMA_VERSION, **canonical_payload(self)})


class SemanticDriftGuard:
    def __init__(self, policy: DriftPolicy = DriftPolicy()) -> None:
        self.policy = policy

    def evaluate(
        self, *, release_fingerprint: str, observations: Iterable[ReviewedProductionDecision]
    ) -> DriftEvaluation:
        release_fingerprint = _sha_hex(release_fingerprint, "release_fingerprint")
        rows = tuple(x for x in observations if x.release_fingerprint == release_fingerprint)
        actionable = tuple(x for x in rows if x.actionable_irrelevant)
        unsafe = sum(x.unsafe_false_exclusion for x in actionable)
        upper = wilson_upper(unsafe, len(actionable)) if actionable else None
        sufficient = (
            len(rows) >= self.policy.minimum_reviewed_cases
            and len(actionable) >= self.policy.minimum_actionable_irrelevant_cases
        )
        reasons: list[str] = []
        tripped = False
        if sufficient:
            if unsafe > self.policy.maximum_unsafe_false_exclusions:
                tripped = True
                reasons.append(
                    f"unsafe false exclusions={unsafe}, allowed<={self.policy.maximum_unsafe_false_exclusions}"
                )
            if upper is None or upper > self.policy.maximum_wilson_upper_unsafe_rate:
                tripped = True
                reasons.append(
                    f"95% Wilson unsafe upper={upper}, allowed<={self.policy.maximum_wilson_upper_unsafe_rate}"
                )
        else:
            reasons.append("insufficient reviewed production evidence; no automatic drift claim")
        return DriftEvaluation(
            release_fingerprint=release_fingerprint,
            reviewed_cases=len(rows),
            actionable_irrelevant_cases=len(actionable),
            unsafe_false_exclusions=unsafe,
            wilson_upper_unsafe_rate=upper,
            sufficient_evidence=sufficient,
            tripped=tripped,
            reasons=tuple(reasons),
            policy_fingerprint=self.policy.fingerprint_sha256,
        )
