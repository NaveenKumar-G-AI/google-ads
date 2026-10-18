from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .business_truth import BusinessTruthSnapshot
from .db.canonical import canonical_payload, payload_sha256
from .search_intent import (
    AssessmentStatus,
    BusinessFitDecision,
    BusinessFitEvaluator,
    ConservativeLexicalInterpreter,
    FitDisposition,
    SemanticAssessment,
    normalize_query,
)
from .semantic_ai import (
    CandidateReleaseEvaluation,
    CandidateSemanticAI,
    ModelUsage,
    SemanticAIContractError,
)
from .semantic_eval import (
    DatasetSplit,
    GoldSemanticCase,
    LabelSource,
    ReleasePolicy,
    evaluation_report_to_dict,
)

PHASE13_SCHEMA_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _sha(value: object) -> str:
    return payload_sha256(value)


def _sha_hex(value: str, name: str) -> str:
    value = value.strip().lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be SHA-256 hex")
    return value


@dataclass(frozen=True, slots=True)
class ShadowInput:
    """Semantic-only representation of one real query scope.

    No cost/click/conversion fields exist in this type by design. Shadow mode may retain
    opaque source observation IDs for traceability but cannot use performance to influence
    interpretation.
    """

    source_identity: str
    raw_query: str
    customer_id: str
    campaign_id: str
    ad_group_id: str
    network: str
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_identity", _sha_hex(self.source_identity, "source_identity"))
        if not self.raw_query.strip():
            raise ValueError("raw_query is required")
        for name in ("customer_id", "campaign_id", "ad_group_id", "network"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        cleaned = tuple(x.strip() for x in self.observation_ids if x.strip())
        if not cleaned or len(set(cleaned)) != len(cleaned):
            raise ValueError("observation_ids must be non-empty and unique")
        object.__setattr__(self, "observation_ids", cleaned)

    @classmethod
    def create(
        cls,
        *,
        raw_query: str,
        customer_id: str,
        campaign_id: str,
        ad_group_id: str,
        network: str,
        observation_ids: Iterable[str],
        truth_fingerprint: str,
    ) -> "ShadowInput":
        truth_fingerprint = _sha_hex(truth_fingerprint, "truth_fingerprint")
        obs = tuple(sorted({str(x).strip() for x in observation_ids if str(x).strip()}))
        if not obs:
            raise ValueError("observation_ids are required")
        source_identity = _sha({
            "customer_id": customer_id,
            "campaign_id": campaign_id,
            "ad_group_id": ad_group_id,
            "network": network.upper(),
            "normalized_query": normalize_query(raw_query),
            "truth_fingerprint": truth_fingerprint,
            "observation_ids": obs,
        })
        return cls(
            source_identity=source_identity,
            raw_query=raw_query,
            customer_id=customer_id,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
            network=network.upper(),
            observation_ids=obs,
        )


@dataclass(frozen=True, slots=True)
class ShadowPrediction:
    source: ShadowInput
    truth_fingerprint: str
    candidate_assessment: SemanticAssessment
    candidate_fit: BusinessFitDecision
    baseline_assessment: SemanticAssessment
    baseline_fit: BusinessFitDecision
    declared_confidence: Decimal | None
    provider: str
    model: str
    provider_model_version: str | None
    candidate_contract_fingerprint: str
    request_prompt_fingerprint: str
    request_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        _sha_hex(self.truth_fingerprint, "truth_fingerprint")
        _sha_hex(self.candidate_contract_fingerprint, "candidate_contract_fingerprint")
        _sha_hex(self.request_prompt_fingerprint, "request_prompt_fingerprint")
        _require_aware(self.created_at, "created_at")
        if self.candidate_assessment.raw_query != self.source.raw_query:
            raise ValueError("candidate assessment query must equal source query")
        if self.baseline_assessment.raw_query != self.source.raw_query:
            raise ValueError("baseline assessment query must equal source query")
        if self.candidate_fit.truth_fingerprint != self.truth_fingerprint:
            raise ValueError("candidate fit truth fingerprint mismatch")
        if self.baseline_fit.truth_fingerprint != self.truth_fingerprint:
            raise ValueError("baseline fit truth fingerprint mismatch")
        if self.declared_confidence is not None and not Decimal(0) <= self.declared_confidence <= Decimal(1):
            raise ValueError("declared_confidence must be in [0,1]")

    @property
    def production_effect_allowed(self) -> bool:
        # Shadow predictions are evidence/monitoring only. This property is intentionally
        # not configurable; production routing is a separate release-registry concern.
        return False

    @property
    def disagrees_with_baseline(self) -> bool:
        return self.candidate_fit.disposition is not self.baseline_fit.disposition

    @property
    def fingerprint_sha256(self) -> str:
        return _sha({
            "schema_version": PHASE13_SCHEMA_VERSION,
            "source_identity": self.source.source_identity,
            "truth": self.truth_fingerprint,
            "candidate_assessment": self.candidate_assessment,
            "candidate_fit": self.candidate_fit,
            "baseline_assessment": self.baseline_assessment,
            "baseline_fit": self.baseline_fit,
            "declared_confidence": self.declared_confidence,
            "provider": self.provider,
            "model": self.model,
            "provider_model_version": self.provider_model_version,
            "candidate_contract_fingerprint": self.candidate_contract_fingerprint,
            "request_prompt_fingerprint": self.request_prompt_fingerprint,
            "request_id": self.request_id,
        })


@dataclass(frozen=True, slots=True)
class ShadowRunResult:
    predictions: tuple[ShadowPrediction, ...]
    provider: str
    model: str
    provider_model_version: str | None
    candidate_contract_fingerprint: str
    truth_fingerprint: str
    usage: ModelUsage

    @property
    def prediction_count(self) -> int:
        return len(self.predictions)

    @property
    def disagreement_count(self) -> int:
        return sum(x.disagrees_with_baseline for x in self.predictions)

    @property
    def irrelevant_candidate_count(self) -> int:
        return sum(x.candidate_fit.disposition is FitDisposition.IRRELEVANT for x in self.predictions)


class ShadowSemanticRunner:
    """Run a candidate against real queries without allowing financial/action effects."""

    def __init__(
        self,
        candidate: CandidateSemanticAI,
        *,
        baseline: ConservativeLexicalInterpreter | None = None,
        fit_evaluator: BusinessFitEvaluator | None = None,
        clock=_utcnow,
    ) -> None:
        self.candidate = candidate
        self.baseline = baseline or ConservativeLexicalInterpreter()
        self.fit_evaluator = fit_evaluator or BusinessFitEvaluator()
        self.clock = clock

    def run(self, *, inputs: Sequence[ShadowInput], truth: BusinessTruthSnapshot) -> ShadowRunResult:
        if not inputs:
            raise ValueError("shadow inputs cannot be empty")
        identities = [x.source_identity for x in inputs]
        if len(set(identities)) != len(identities):
            raise ValueError("shadow inputs must have unique source_identity values")
        ordered = sorted(inputs, key=lambda x: x.source_identity)
        step = self.candidate.config.maximum_batch_queries
        predictions: list[ShadowPrediction] = []
        provider_versions: set[str] = set()
        providers: set[str] = set()
        models: set[str] = set()
        contract_fps: set[str] = set()
        usages: list[ModelUsage] = []

        for start in range(0, len(ordered), step):
            batch = ordered[start:start + step]
            result = self.candidate.interpret_many(tuple(x.raw_query for x in batch), truth)
            if result.truth_fingerprint != truth.fingerprint_sha256:
                raise SemanticAIContractError("shadow result truth fingerprint mismatch")
            providers.add(result.provider)
            models.add(result.model)
            contract_fps.add(result.candidate_contract_fingerprint)
            if result.provider_model_version:
                provider_versions.add(result.provider_model_version)
            if len(providers) != 1 or len(models) != 1 or len(contract_fps) != 1 or len(provider_versions) > 1:
                raise SemanticAIContractError("shadow run mixed provider/model/contract revisions")
            usages.append(result.usage)

            for source, assessment, confidence in zip(
                batch, result.assessments, result.declared_confidences, strict=True
            ):
                baseline_assessment = self.baseline.interpret(source.raw_query, truth)
                predictions.append(ShadowPrediction(
                    source=source,
                    truth_fingerprint=truth.fingerprint_sha256,
                    candidate_assessment=assessment,
                    candidate_fit=self.fit_evaluator.evaluate(assessment, truth),
                    baseline_assessment=baseline_assessment,
                    baseline_fit=self.fit_evaluator.evaluate(baseline_assessment, truth),
                    declared_confidence=confidence,
                    provider=result.provider,
                    model=result.model,
                    provider_model_version=result.provider_model_version,
                    candidate_contract_fingerprint=result.candidate_contract_fingerprint,
                    request_prompt_fingerprint=result.prompt_fingerprint,
                    request_id=result.request_id,
                    created_at=self.clock(),
                ))

        def total(name: str) -> int | None:
            vals = [getattr(x, name) for x in usages if getattr(x, name) is not None]
            return sum(vals) if vals else None

        return ShadowRunResult(
            predictions=tuple(sorted(predictions, key=lambda x: x.source.source_identity)),
            provider=next(iter(providers)),
            model=next(iter(models)),
            provider_model_version=next(iter(provider_versions), None),
            candidate_contract_fingerprint=next(iter(contract_fps)),
            truth_fingerprint=truth.fingerprint_sha256,
            usage=ModelUsage(
                input_tokens=total("input_tokens"),
                output_tokens=total("output_tokens"),
                thinking_tokens=total("thinking_tokens"),
                total_tokens=total("total_tokens"),
            ),
        )


@dataclass(frozen=True, slots=True)
class BlindHumanReview:
    """A gold-label review deliberately detached from candidate prediction data."""

    raw_query: str
    truth_fingerprint: str
    reviewer_id: str
    expected_disposition: FitDisposition
    expected_status: AssessmentStatus
    language_code: str
    submitted_at: datetime
    blinded_to_candidate: bool = True
    adjudicator: bool = False
    tags: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        _sha_hex(self.truth_fingerprint, "truth_fingerprint")
        if not self.raw_query.strip() or not self.reviewer_id.strip() or not self.language_code.strip():
            raise ValueError("query, reviewer_id and language_code are required")
        _require_aware(self.submitted_at, "submitted_at")
        tags = tuple(sorted({x.strip().casefold() for x in self.tags if x.strip()}))
        object.__setattr__(self, "tags", tags)

    @property
    def case_key(self) -> str:
        return _sha({
            "raw_query": self.raw_query,
            "truth_fingerprint": self.truth_fingerprint,
        })

    @property
    def review_fingerprint(self) -> str:
        return _sha({
            "schema_version": PHASE13_SCHEMA_VERSION,
            "case_key": self.case_key,
            "reviewer_id": self.reviewer_id,
            "expected_disposition": self.expected_disposition.value,
            "expected_status": self.expected_status.value,
            "language_code": self.language_code,
            "blinded": self.blinded_to_candidate,
            "adjudicator": self.adjudicator,
            "tags": self.tags,
            "notes": self.notes,
            "submitted_at": self.submitted_at,
        })


class GoldAdjudicationError(ValueError):
    pass


def _assign_split(*, identity: str, dataset_salt: str, calibration_fraction: Decimal) -> DatasetSplit:
    if not dataset_salt:
        raise ValueError("dataset_salt is required")
    if calibration_fraction <= 0 or calibration_fraction >= 1:
        raise ValueError("calibration_fraction must be strictly between 0 and 1")
    digest = hmac.new(dataset_salt.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256).digest()
    # 64-bit bucket gives stable assignment without exposing candidate behavior.
    value = int.from_bytes(digest[:8], "big")
    ratio = Decimal(value) / Decimal(2**64)
    return DatasetSplit.CALIBRATION if ratio < calibration_fraction else DatasetSplit.TEST


def adjudicate_gold_case(
    reviews: Sequence[BlindHumanReview],
    *,
    dataset_salt: str,
    calibration_fraction: Decimal = Decimal("0.40"),
) -> GoldSemanticCase:
    if len(reviews) < 2:
        raise GoldAdjudicationError("release-quality gold requires at least two human reviewers")
    first = reviews[0]
    if any(r.case_key != first.case_key for r in reviews):
        raise GoldAdjudicationError("reviews do not refer to the same query + Business Truth")
    reviewer_ids = [r.reviewer_id for r in reviews]
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise GoldAdjudicationError("reviewers must be distinct")
    if not all(r.blinded_to_candidate for r in reviews):
        raise GoldAdjudicationError("release-quality gold labels must be blinded to candidate predictions")

    labels = {(r.expected_disposition, r.expected_status, r.language_code.casefold()) for r in reviews}
    if len(labels) == 1:
        chosen = first
        source = LabelSource.DOUBLE_REVIEW
        common_tags = set(first.tags)
        for r in reviews[1:]:
            common_tags &= set(r.tags)
        tags = tuple(sorted(common_tags))
    else:
        adjudicators = [r for r in reviews if r.adjudicator]
        if len(adjudicators) != 1:
            raise GoldAdjudicationError(
                "disagreeing reviews require exactly one blinded adjudicator decision"
            )
        chosen = adjudicators[0]
        source = LabelSource.ADJUDICATED
        tags = chosen.tags

    identity = _sha({
        "raw_query": chosen.raw_query,
        "truth_fingerprint": chosen.truth_fingerprint,
        "language_code": chosen.language_code.casefold(),
    })
    split = _assign_split(
        identity=identity,
        dataset_salt=dataset_salt,
        calibration_fraction=calibration_fraction,
    )
    case_id = f"gold-{_sha({'identity': identity, 'label': chosen.expected_disposition.value, 'status': chosen.expected_status.value})[:24]}"
    return GoldSemanticCase(
        case_id=case_id,
        raw_query=chosen.raw_query,
        truth_fingerprint=chosen.truth_fingerprint,
        expected_disposition=chosen.expected_disposition,
        expected_status=chosen.expected_status,
        language_code=chosen.language_code.casefold(),
        split=split,
        label_source=source,
        reviewer_count=len(reviews),
        notes=(
            f"Phase13 blinded human adjudication; review_fingerprints="
            f"{','.join(sorted(r.review_fingerprint for r in reviews))}"
        ),
        tags=tags,
    )


@dataclass(frozen=True, slots=True)
class CandidateReleaseIdentity:
    provider: str
    model: str
    provider_model_version: str
    thinking_level: str
    prompt_version: str
    candidate_contract_fingerprint: str
    semantic_schema_version: int

    def __post_init__(self) -> None:
        for name in ("provider", "model", "provider_model_version", "thinking_level", "prompt_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required for a promotable release")
        _sha_hex(self.candidate_contract_fingerprint, "candidate_contract_fingerprint")
        if self.semantic_schema_version < 1:
            raise ValueError("semantic_schema_version must be positive")

    @property
    def fingerprint_sha256(self) -> str:
        return _sha({"schema_version": PHASE13_SCHEMA_VERSION, **canonical_payload(self)})

    @classmethod
    def from_evaluation(cls, evaluation: CandidateReleaseEvaluation) -> "CandidateReleaseIdentity":
        if not evaluation.provider_model_version:
            raise ValueError("provider-reported model version is required before promotion")
        return cls(
            provider=evaluation.provider,
            model=evaluation.model,
            provider_model_version=evaluation.provider_model_version,
            thinking_level=evaluation.thinking_level,
            prompt_version=evaluation.prompt_version,
            candidate_contract_fingerprint=evaluation.candidate_contract_fingerprint,
            semantic_schema_version=evaluation.semantic_schema_version,
        )


class ReleaseEventType(str, Enum):
    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True)
class SemanticReleaseDefinition:
    candidate: CandidateReleaseIdentity
    selected_confidence_threshold: Decimal
    evaluation_candidate_fingerprint: str
    evaluation_report_fingerprint: str
    dataset_fingerprint: str
    release_policy_fingerprint: str
    approved_languages: tuple[str, ...]
    created_by: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.selected_confidence_threshold < 0 or self.selected_confidence_threshold > 1:
            raise ValueError("selected_confidence_threshold must be in [0,1]")
        for name in (
            "evaluation_candidate_fingerprint", "evaluation_report_fingerprint",
            "dataset_fingerprint", "release_policy_fingerprint",
        ):
            _sha_hex(str(getattr(self, name)), name)
        langs = tuple(sorted({x.strip().casefold() for x in self.approved_languages if x.strip()}))
        if not langs:
            raise ValueError("at least one approved language is required")
        object.__setattr__(self, "approved_languages", langs)
        if not self.created_by.strip():
            raise ValueError("created_by is required")
        _require_aware(self.created_at, "created_at")

    @property
    def release_fingerprint(self) -> str:
        return _sha({"schema_version": PHASE13_SCHEMA_VERSION, **canonical_payload(self)})


def release_policy_fingerprint(policy: ReleasePolicy) -> str:
    return _sha({"phase": 13, "release_policy": policy})


def evaluation_report_fingerprint(evaluation: CandidateReleaseEvaluation) -> str:
    return _sha({
        "calibration": evaluation_report_to_dict(evaluation.calibration_report),
        "test": evaluation_report_to_dict(evaluation.test_report),
        "gate": evaluation.gate_result,
        "selected_threshold": evaluation.selected_confidence_threshold,
        "candidate_fingerprint": evaluation.candidate_fingerprint,
    })


def build_release_definition(
    evaluation: CandidateReleaseEvaluation,
    *,
    policy: ReleasePolicy,
    approved_languages: Sequence[str],
    created_by: str,
    created_at: datetime | None = None,
) -> SemanticReleaseDefinition:
    if not evaluation.gate_result.passed:
        raise ValueError("candidate cannot be promoted because the Phase-11 release gate failed")
    if evaluation.selected_confidence_threshold is None:
        raise ValueError("candidate cannot be promoted without a calibration-selected threshold")
    candidate = CandidateReleaseIdentity.from_evaluation(evaluation)
    requested = tuple(sorted({x.strip().casefold() for x in approved_languages if x.strip()}))
    if not requested:
        raise ValueError("approved_languages cannot be empty")

    required = {x.casefold() for x in policy.required_language_slices}
    missing_gate_languages = [x for x in requested if x not in required]
    if missing_gate_languages:
        raise ValueError(
            "every approved language must be an explicit required_language_slice in the release policy: "
            + ",".join(missing_gate_languages)
        )

    test_languages = {x.name.casefold(): x for x in evaluation.test_report.language_slices}
    threshold = evaluation.selected_confidence_threshold
    for lang in requested:
        item = test_languages.get(lang)
        if item is None or item.support < policy.minimum_cases_per_required_language:
            raise ValueError(f"approved language {lang} lacks required holdout support")
        thresholded = [
            x for x in evaluation.test_report.cases
            if x.gold.language_code.casefold() == lang
            and x.predicted_irrelevant
            and x.prediction.declared_confidence is not None
            and x.prediction.declared_confidence >= threshold
        ]
        if any(x.unsafe_false_exclusion for x in thresholded):
            raise ValueError(f"approved language {lang} has an unsafe thresholded false exclusion")

    return SemanticReleaseDefinition(
        candidate=candidate,
        selected_confidence_threshold=threshold,
        evaluation_candidate_fingerprint=_sha_hex(evaluation.candidate_fingerprint, "candidate_fingerprint"),
        evaluation_report_fingerprint=evaluation_report_fingerprint(evaluation),
        dataset_fingerprint=_sha_hex(evaluation.test_report.dataset_fingerprint, "dataset_fingerprint"),
        release_policy_fingerprint=release_policy_fingerprint(policy),
        approved_languages=requested,
        created_by=created_by,
        created_at=created_at or _utcnow(),
    )


@dataclass(frozen=True, slots=True)
class SemanticReleaseEvent:
    release_fingerprint: str
    event_type: ReleaseEventType
    actor: str
    occurred_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        _sha_hex(self.release_fingerprint, "release_fingerprint")
        if not self.actor.strip():
            raise ValueError("actor is required")
        _require_aware(self.occurred_at, "occurred_at")
        if self.event_type is ReleaseEventType.REVOKE and not (self.reason and self.reason.strip()):
            raise ValueError("revocation requires a reason")

    @property
    def event_fingerprint(self) -> str:
        return _sha({"schema_version": PHASE13_SCHEMA_VERSION, **canonical_payload(self)})


@dataclass(slots=True)
class ReleaseStateMachine:
    definition: SemanticReleaseDefinition
    events: list[SemanticReleaseEvent] = field(default_factory=list)

    @property
    def revoked(self) -> bool:
        return any(x.event_type is ReleaseEventType.REVOKE for x in self.events)

    @property
    def active(self) -> bool:
        if self.revoked:
            return False
        active = False
        for event in self.events:
            if event.event_type is ReleaseEventType.ACTIVATE:
                active = True
            elif event.event_type is ReleaseEventType.DEACTIVATE:
                active = False
        return active

    def apply(self, event: SemanticReleaseEvent) -> None:
        if event.release_fingerprint != self.definition.release_fingerprint:
            raise ValueError("release event targets a different release definition")
        if self.revoked:
            raise ValueError("revoked releases cannot transition again")
        if self.events and event.occurred_at < self.events[-1].occurred_at:
            raise ValueError("release event occurred_at cannot move backwards")
        if event.event_type is ReleaseEventType.ACTIVATE and self.active:
            raise ValueError("release is already active")
        if event.event_type is ReleaseEventType.DEACTIVATE and not self.active:
            raise ValueError("release is not active")
        self.events.append(event)

    def permits_candidate_for_language(self, language_code: str) -> bool:
        return self.active and language_code.casefold() in set(self.definition.approved_languages)
