from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .business_truth import BusinessTruthSnapshot
from .search_intent import (
    AssessmentStatus,
    BusinessFitDecision,
    BusinessFitEvaluator,
    FitDisposition,
    SemanticAssessment,
)

EVAL_SCHEMA_VERSION = 1


def _prob(value: Decimal | str | float | int | None) -> Decimal | None:
    if value is None:
        return None
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if result < 0 or result > 1:
        raise ValueError("confidence must be in [0,1]")
    return result


def _sha(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DatasetSplit(str, Enum):
    CALIBRATION = "calibration"
    TEST = "test"


class LabelSource(str, Enum):
    DOUBLE_REVIEW = "double_review"
    ADJUDICATED = "adjudicated"
    SINGLE_REVIEW = "single_review"


@dataclass(frozen=True, slots=True)
class GoldSemanticCase:
    """Human-labelled semantic truth for one query under one Business Truth snapshot.

    Search intent is contextual. The same query may receive a different label under a
    different truth snapshot, so truth_fingerprint is part of case identity.
    """

    case_id: str
    raw_query: str
    truth_fingerprint: str
    expected_disposition: FitDisposition
    expected_status: AssessmentStatus
    language_code: str
    split: DatasetSplit
    label_source: LabelSource
    reviewer_count: int
    notes: str = ""
    tags: tuple[str, ...] = ()
    schema_version: int = EVAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVAL_SCHEMA_VERSION:
            raise ValueError("unsupported evaluation schema version")
        if not self.case_id.strip() or not self.raw_query.strip():
            raise ValueError("case_id and raw_query are required")
        if len(self.truth_fingerprint) != 64:
            raise ValueError("truth_fingerprint must be a SHA-256 hex digest")
        if not self.language_code.strip():
            raise ValueError("language_code is required; use 'und' only when truly unknown")
        if self.reviewer_count < 1:
            raise ValueError("reviewer_count must be >= 1")
        cleaned_tags = tuple(x.strip().casefold() for x in self.tags if x.strip())
        if len(set(cleaned_tags)) != len(cleaned_tags):
            raise ValueError("tags must be unique")
        object.__setattr__(self, "tags", cleaned_tags)
        if self.label_source in {LabelSource.DOUBLE_REVIEW, LabelSource.ADJUDICATED} and self.reviewer_count < 2:
            raise ValueError("double-reviewed/adjudicated cases require at least two reviewers")
        # Exclusion-critical gold must never rest on a single reviewer.
        if self.expected_disposition is FitDisposition.IRRELEVANT and self.reviewer_count < 2:
            raise ValueError("IRRELEVANT gold labels require at least two reviewers")

    @property
    def identity_fingerprint(self) -> str:
        return _sha({
            "query": self.raw_query,
            "truth": self.truth_fingerprint,
            "language": self.language_code,
        })


@dataclass(frozen=True, slots=True)
class CandidatePrediction:
    case_id: str
    assessment: SemanticAssessment
    declared_confidence: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        object.__setattr__(self, "declared_confidence", _prob(self.declared_confidence))


@dataclass(frozen=True, slots=True)
class EvaluatedCase:
    gold: GoldSemanticCase
    prediction: CandidatePrediction
    decision: BusinessFitDecision

    @property
    def exact_disposition_correct(self) -> bool:
        return self.decision.disposition is self.gold.expected_disposition

    @property
    def semantic_status_correct(self) -> bool:
        return self.decision.semantic_status is self.gold.expected_status

    @property
    def predicted_irrelevant(self) -> bool:
        return self.decision.disposition is FitDisposition.IRRELEVANT

    @property
    def gold_irrelevant(self) -> bool:
        return self.gold.expected_disposition is FitDisposition.IRRELEVANT

    @property
    def unsafe_false_exclusion(self) -> bool:
        return self.predicted_irrelevant and not self.gold_irrelevant

    @property
    def abstained(self) -> bool:
        return self.decision.disposition in {FitDisposition.UNKNOWN, FitDisposition.CONDITIONAL}


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: Decimal
    upper: Decimal
    count: int
    mean_confidence: Decimal
    empirical_accuracy: Decimal


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    support: int
    brier_score: Decimal | None
    expected_calibration_error: Decimal | None
    bins: tuple[CalibrationBin, ...]


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    threshold: Decimal
    eligible: int
    predicted_irrelevant: int
    correct_irrelevant: int
    unsafe_false_exclusions: int
    irrelevant_precision: Decimal | None
    unsafe_rate: Decimal | None
    dataset_coverage: Decimal


@dataclass(frozen=True, slots=True)
class SliceReport:
    name: str
    support: int
    exact_accuracy: Decimal
    abstention_rate: Decimal
    predicted_irrelevant: int
    gold_irrelevant: int
    unsafe_false_exclusions: int
    irrelevant_precision: Decimal | None
    unsafe_rate_among_negative_actions: Decimal | None


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    model_id: str
    model_version: str
    dataset_fingerprint: str
    support: int
    exact_accuracy: Decimal
    abstention_rate: Decimal
    predicted_irrelevant: int
    gold_irrelevant: int
    unsafe_false_exclusions: int
    irrelevant_precision: Decimal | None
    unsafe_rate_among_negative_actions: Decimal | None
    calibration: CalibrationReport
    risk_coverage: tuple[RiskCoveragePoint, ...]
    language_slices: tuple[SliceReport, ...]
    tag_slices: tuple[SliceReport, ...]
    cases: tuple[EvaluatedCase, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ReleasePolicy:
    """Product policy, not a universal statistical truth.

    The defaults are intentionally conservative for V1. They can only be changed by
    an explicit versioned policy decision; the evaluator does not silently optimize
    them against the holdout test set.
    """

    minimum_test_cases: int = 500
    minimum_safety_cases: int = 200
    maximum_unsafe_false_exclusions: int = 0
    minimum_irrelevant_precision: Decimal = Decimal("0.995")
    maximum_ece: Decimal = Decimal("0.05")
    minimum_calibration_support: int = 200
    required_language_slices: tuple[str, ...] = ()
    minimum_cases_per_required_language: int = 50
    required_tag_slices: tuple[str, ...] = ()
    minimum_cases_per_required_tag: int = 25
    maximum_wilson_upper_unsafe_rate: Decimal = Decimal("0.02")
    confidence_level_z: Decimal = Decimal("1.959963984540054")  # 95% two-sided normal approximation

    def __post_init__(self) -> None:
        if self.minimum_test_cases < 1 or self.minimum_safety_cases < 1:
            raise ValueError("minimum supports must be positive")
        for name in (
            "minimum_irrelevant_precision",
            "maximum_ece",
            "maximum_wilson_upper_unsafe_rate",
        ):
            value = getattr(self, name)
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be in [0,1]")


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ReleaseGateResult:
    passed: bool
    checks: tuple[GateCheck, ...]
    selected_confidence_threshold: Decimal | None


def dataset_fingerprint(cases: Sequence[GoldSemanticCase]) -> str:
    if not cases:
        raise ValueError("dataset cannot be empty")
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case_id")
    return _sha([
        {
            "case_id": c.case_id,
            "query": c.raw_query,
            "truth": c.truth_fingerprint,
            "expected_disposition": c.expected_disposition.value,
            "expected_status": c.expected_status.value,
            "language": c.language_code,
            "split": c.split.value,
            "source": c.label_source.value,
            "reviewers": c.reviewer_count,
            "tags": list(c.tags),
        }
        for c in sorted(cases, key=lambda x: x.case_id)
    ])


def validate_split_isolation(cases: Sequence[GoldSemanticCase]) -> None:
    """Prevent calibration/test leakage by query + truth identity, not merely case ID."""
    seen: dict[str, DatasetSplit] = {}
    for case in cases:
        key = case.identity_fingerprint
        prior = seen.get(key)
        if prior is not None and prior is not case.split:
            raise ValueError(
                "calibration/test leakage: same query + Business Truth appears in both splits"
            )
        seen[key] = case.split


def _ratio(n: int, d: int) -> Decimal:
    return Decimal(n) / Decimal(d) if d else Decimal(0)


def wilson_upper(successes: int, trials: int, z: Decimal = Decimal("1.959963984540054")) -> Decimal | None:
    """Upper Wilson score bound for a Bernoulli rate.

    Here `successes` can mean unsafe failures. Returning an uncertainty bound prevents
    zero observed errors on a tiny sample from being presented as proof of zero risk.
    """
    if trials <= 0:
        return None
    p = Decimal(successes) / Decimal(trials)
    z2 = z * z
    n = Decimal(trials)
    denom = Decimal(1) + z2 / n
    center = p + z2 / (Decimal(2) * n)
    variance = (p * (Decimal(1) - p) / n) + (z2 / (Decimal(4) * n * n))
    margin = z * Decimal(str(math.sqrt(float(variance))))
    upper = (center + margin) / denom
    return min(Decimal(1), max(Decimal(0), upper))


def _calibration(evaluated: Sequence[EvaluatedCase], *, bin_count: int = 10) -> CalibrationReport:
    points = [x for x in evaluated if x.prediction.declared_confidence is not None]
    if not points:
        return CalibrationReport(0, None, None, ())

    brier = sum(
        (x.prediction.declared_confidence - (Decimal(1) if x.exact_disposition_correct else Decimal(0))) ** 2
        for x in points
    ) / Decimal(len(points))

    bins: list[CalibrationBin] = []
    ece = Decimal(0)
    for i in range(bin_count):
        lo = Decimal(i) / Decimal(bin_count)
        hi = Decimal(i + 1) / Decimal(bin_count)
        bucket = [
            x for x in points
            if x.prediction.declared_confidence is not None
            and x.prediction.declared_confidence >= lo
            and (x.prediction.declared_confidence < hi or (i == bin_count - 1 and x.prediction.declared_confidence <= hi))
        ]
        if not bucket:
            continue
        mean_conf = sum(x.prediction.declared_confidence for x in bucket if x.prediction.declared_confidence is not None) / Decimal(len(bucket))
        accuracy = _ratio(sum(1 for x in bucket if x.exact_disposition_correct), len(bucket))
        bins.append(CalibrationBin(lo, hi, len(bucket), mean_conf, accuracy))
        ece += (Decimal(len(bucket)) / Decimal(len(points))) * abs(mean_conf - accuracy)

    return CalibrationReport(len(points), brier, ece, tuple(bins))


def _slice(name: str, items: Sequence[EvaluatedCase]) -> SliceReport:
    support = len(items)
    predicted_irrelevant = sum(x.predicted_irrelevant for x in items)
    gold_irrelevant = sum(x.gold_irrelevant for x in items)
    unsafe = sum(x.unsafe_false_exclusion for x in items)
    true_irrelevant = sum(x.predicted_irrelevant and x.gold_irrelevant for x in items)
    return SliceReport(
        name=name,
        support=support,
        exact_accuracy=_ratio(sum(x.exact_disposition_correct for x in items), support),
        abstention_rate=_ratio(sum(x.abstained for x in items), support),
        predicted_irrelevant=predicted_irrelevant,
        gold_irrelevant=gold_irrelevant,
        unsafe_false_exclusions=unsafe,
        irrelevant_precision=(
            Decimal(true_irrelevant) / Decimal(predicted_irrelevant)
            if predicted_irrelevant else None
        ),
        unsafe_rate_among_negative_actions=(
            Decimal(unsafe) / Decimal(predicted_irrelevant)
            if predicted_irrelevant else None
        ),
    )


def _risk_coverage(evaluated: Sequence[EvaluatedCase], thresholds: Sequence[Decimal]) -> tuple[RiskCoveragePoint, ...]:
    result: list[RiskCoveragePoint] = []
    for threshold in thresholds:
        eligible = [
            x for x in evaluated
            if x.prediction.declared_confidence is not None
            and x.prediction.declared_confidence >= threshold
        ]
        negatives = [x for x in eligible if x.predicted_irrelevant]
        correct = sum(x.gold_irrelevant for x in negatives)
        unsafe = sum(x.unsafe_false_exclusion for x in negatives)
        result.append(
            RiskCoveragePoint(
                threshold=threshold,
                eligible=len(eligible),
                predicted_irrelevant=len(negatives),
                correct_irrelevant=correct,
                unsafe_false_exclusions=unsafe,
                irrelevant_precision=(Decimal(correct) / Decimal(len(negatives)) if negatives else None),
                unsafe_rate=(Decimal(unsafe) / Decimal(len(negatives)) if negatives else None),
                dataset_coverage=_ratio(len(eligible), len(evaluated)),
            )
        )
    return tuple(result)


class SemanticEvaluator:
    def __init__(self, *, fit_evaluator: BusinessFitEvaluator | None = None) -> None:
        self.fit_evaluator = fit_evaluator or BusinessFitEvaluator()

    def evaluate(
        self,
        *,
        model_id: str,
        model_version: str,
        cases: Sequence[GoldSemanticCase],
        predictions: Sequence[CandidatePrediction],
        truths: Mapping[str, BusinessTruthSnapshot],
        split: DatasetSplit = DatasetSplit.TEST,
    ) -> EvaluationReport:
        if not model_id.strip() or not model_version.strip():
            raise ValueError("model_id and model_version are required")
        validate_split_isolation(cases)
        selected = [c for c in cases if c.split is split]
        if not selected:
            raise ValueError(f"no cases in split {split.value}")
        prediction_map = {p.case_id: p for p in predictions}
        if len(prediction_map) != len(predictions):
            raise ValueError("duplicate candidate prediction case_id")
        missing = [c.case_id for c in selected if c.case_id not in prediction_map]
        if missing:
            raise ValueError(f"missing predictions for cases: {missing[:5]}")

        evaluated: list[EvaluatedCase] = []
        for gold in selected:
            truth = truths.get(gold.truth_fingerprint)
            if truth is None:
                raise ValueError(f"missing Business Truth snapshot {gold.truth_fingerprint}")
            if truth.fingerprint_sha256 != gold.truth_fingerprint:
                raise ValueError("Business Truth registry key/fingerprint mismatch")
            pred = prediction_map[gold.case_id]
            if pred.assessment.raw_query != gold.raw_query:
                raise ValueError(f"prediction query mismatch for {gold.case_id}")
            decision = self.fit_evaluator.evaluate(pred.assessment, truth)
            evaluated.append(EvaluatedCase(gold, pred, decision))

        base = _slice("all", evaluated)
        languages = tuple(
            _slice(language, [x for x in evaluated if x.gold.language_code.casefold() == language.casefold()])
            for language in sorted({x.gold.language_code for x in evaluated})
        )
        tags = tuple(
            _slice(tag, [x for x in evaluated if tag in x.gold.tags])
            for tag in sorted({tag for x in evaluated for tag in x.gold.tags})
        )
        thresholds = tuple(Decimal(x) for x in ("0.50", "0.70", "0.80", "0.90", "0.95", "0.97", "0.99"))
        return EvaluationReport(
            model_id=model_id,
            model_version=model_version,
            dataset_fingerprint=dataset_fingerprint(cases),
            support=base.support,
            exact_accuracy=base.exact_accuracy,
            abstention_rate=base.abstention_rate,
            predicted_irrelevant=base.predicted_irrelevant,
            gold_irrelevant=base.gold_irrelevant,
            unsafe_false_exclusions=base.unsafe_false_exclusions,
            irrelevant_precision=base.irrelevant_precision,
            unsafe_rate_among_negative_actions=base.unsafe_rate_among_negative_actions,
            calibration=_calibration(evaluated),
            risk_coverage=_risk_coverage(evaluated, thresholds),
            language_slices=languages,
            tag_slices=tags,
            cases=tuple(evaluated),
        )


def choose_threshold_from_calibration(
    report: EvaluationReport,
    *,
    maximum_unsafe_false_exclusions: int = 0,
    minimum_irrelevant_precision: Decimal = Decimal("0.995"),
    minimum_negative_actions: int = 25,
) -> Decimal | None:
    """Choose using CALIBRATION results only; never tune on the holdout test split."""
    viable = [
        point for point in report.risk_coverage
        if point.predicted_irrelevant >= minimum_negative_actions
        and point.unsafe_false_exclusions <= maximum_unsafe_false_exclusions
        and point.irrelevant_precision is not None
        and point.irrelevant_precision >= minimum_irrelevant_precision
    ]
    if not viable:
        return None
    # Prefer the lowest viable threshold to retain coverage after safety is satisfied.
    return min(point.threshold for point in viable)


def gate_release(
    report: EvaluationReport,
    *,
    policy: ReleasePolicy,
    selected_confidence_threshold: Decimal | None,
) -> ReleaseGateResult:
    checks: list[GateCheck] = []

    checks.append(GateCheck(
        "test_support",
        report.support >= policy.minimum_test_cases,
        f"support={report.support}, required>={policy.minimum_test_cases}",
    ))

    thresholded = [
        x for x in report.cases
        if x.predicted_irrelevant
        and selected_confidence_threshold is not None
        and x.prediction.declared_confidence is not None
        and x.prediction.declared_confidence >= selected_confidence_threshold
    ]
    safety_support = len(thresholded)
    unsafe_thresholded = sum(x.unsafe_false_exclusion for x in thresholded)
    correct_thresholded = sum(x.gold_irrelevant for x in thresholded)
    precision = (
        Decimal(correct_thresholded) / Decimal(safety_support) if safety_support else None
    )
    checks.append(GateCheck(
        "negative_action_support",
        safety_support >= policy.minimum_safety_cases,
        f"thresholded_predicted_irrelevant={safety_support}, required>={policy.minimum_safety_cases}",
    ))

    checks.append(GateCheck(
        "zero_or_bounded_unsafe_false_exclusions",
        unsafe_thresholded <= policy.maximum_unsafe_false_exclusions,
        f"thresholded_unsafe={unsafe_thresholded}, allowed<={policy.maximum_unsafe_false_exclusions}",
    ))

    checks.append(GateCheck(
        "irrelevant_precision",
        precision is not None and precision >= policy.minimum_irrelevant_precision,
        f"precision={precision}, required>={policy.minimum_irrelevant_precision}",
    ))

    upper = wilson_upper(
        unsafe_thresholded,
        safety_support,
        policy.confidence_level_z,
    )
    checks.append(GateCheck(
        "unsafe_rate_uncertainty_bound",
        upper is not None and upper <= policy.maximum_wilson_upper_unsafe_rate,
        f"95% Wilson upper={upper}, required<={policy.maximum_wilson_upper_unsafe_rate}",
    ))

    cal = report.calibration
    checks.append(GateCheck(
        "calibration_support",
        cal.support >= policy.minimum_calibration_support,
        f"confidence-labelled support={cal.support}, required>={policy.minimum_calibration_support}",
    ))
    checks.append(GateCheck(
        "calibration_error",
        cal.expected_calibration_error is not None and cal.expected_calibration_error <= policy.maximum_ece,
        f"ECE={cal.expected_calibration_error}, required<={policy.maximum_ece}",
    ))

    by_language = {x.name.casefold(): x for x in report.language_slices}
    for language in policy.required_language_slices:
        item = by_language.get(language.casefold())
        checks.append(GateCheck(
            f"language_support:{language}",
            item is not None and item.support >= policy.minimum_cases_per_required_language,
            f"support={item.support if item else 0}, required>={policy.minimum_cases_per_required_language}",
        ))
        language_thresholded = [
            x for x in thresholded if x.gold.language_code.casefold() == language.casefold()
        ]
        if language_thresholded:
            language_unsafe = sum(x.unsafe_false_exclusion for x in language_thresholded)
            checks.append(GateCheck(
                f"language_false_exclusion:{language}",
                language_unsafe == 0,
                f"thresholded_unsafe={language_unsafe}",
            ))

    by_tag = {x.name.casefold(): x for x in report.tag_slices}
    for tag in policy.required_tag_slices:
        item = by_tag.get(tag.casefold())
        checks.append(GateCheck(
            f"tag_support:{tag}",
            item is not None and item.support >= policy.minimum_cases_per_required_tag,
            f"support={item.support if item else 0}, required>={policy.minimum_cases_per_required_tag}",
        ))
        tag_thresholded = [x for x in thresholded if tag.casefold() in x.gold.tags]
        if tag_thresholded:
            tag_unsafe = sum(x.unsafe_false_exclusion for x in tag_thresholded)
            checks.append(GateCheck(
                f"tag_false_exclusion:{tag}",
                tag_unsafe == 0,
                f"thresholded_unsafe={tag_unsafe}",
            ))

    checks.append(GateCheck(
        "calibrated_threshold_selected",
        selected_confidence_threshold is not None,
        f"threshold={selected_confidence_threshold}",
    ))

    return ReleaseGateResult(
        passed=all(x.passed for x in checks),
        checks=tuple(checks),
        selected_confidence_threshold=selected_confidence_threshold,
    )


def evaluation_report_to_dict(report: EvaluationReport) -> dict[str, object]:
    return {
        "model_id": report.model_id,
        "model_version": report.model_version,
        "dataset_fingerprint": report.dataset_fingerprint,
        "support": report.support,
        "exact_accuracy": str(report.exact_accuracy),
        "abstention_rate": str(report.abstention_rate),
        "predicted_irrelevant": report.predicted_irrelevant,
        "gold_irrelevant": report.gold_irrelevant,
        "unsafe_false_exclusions": report.unsafe_false_exclusions,
        "irrelevant_precision": str(report.irrelevant_precision) if report.irrelevant_precision is not None else None,
        "unsafe_rate_among_negative_actions": (
            str(report.unsafe_rate_among_negative_actions)
            if report.unsafe_rate_among_negative_actions is not None else None
        ),
        "calibration": {
            "support": report.calibration.support,
            "brier_score": str(report.calibration.brier_score) if report.calibration.brier_score is not None else None,
            "ece": (
                str(report.calibration.expected_calibration_error)
                if report.calibration.expected_calibration_error is not None else None
            ),
        },
        "languages": [
            {
                "language": x.name,
                "support": x.support,
                "accuracy": str(x.exact_accuracy),
                "abstention_rate": str(x.abstention_rate),
                "unsafe_false_exclusions": x.unsafe_false_exclusions,
                "irrelevant_precision": str(x.irrelevant_precision) if x.irrelevant_precision is not None else None,
            }
            for x in report.language_slices
        ],
        "tags": [
            {
                "tag": x.name,
                "support": x.support,
                "accuracy": str(x.exact_accuracy),
                "abstention_rate": str(x.abstention_rate),
                "unsafe_false_exclusions": x.unsafe_false_exclusions,
            }
            for x in report.tag_slices
        ],
    }


def gold_cases_to_jsonl(cases: Sequence[GoldSemanticCase]) -> str:
    """Canonical JSONL export for human-reviewed gold labels."""
    lines: list[str] = []
    for c in sorted(cases, key=lambda x: x.case_id):
        payload = {
            "schema_version": c.schema_version,
            "case_id": c.case_id,
            "raw_query": c.raw_query,
            "truth_fingerprint": c.truth_fingerprint,
            "expected_disposition": c.expected_disposition.value,
            "expected_status": c.expected_status.value,
            "language_code": c.language_code,
            "split": c.split.value,
            "label_source": c.label_source.value,
            "reviewer_count": c.reviewer_count,
            "notes": c.notes,
            "tags": list(c.tags),
        }
        lines.append(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")


def gold_cases_from_jsonl(text: str) -> tuple[GoldSemanticCase, ...]:
    cases: list[GoldSemanticCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            cases.append(
                GoldSemanticCase(
                    case_id=str(item["case_id"]),
                    raw_query=str(item["raw_query"]),
                    truth_fingerprint=str(item["truth_fingerprint"]),
                    expected_disposition=FitDisposition(str(item["expected_disposition"])),
                    expected_status=AssessmentStatus(str(item["expected_status"])),
                    language_code=str(item["language_code"]),
                    split=DatasetSplit(str(item["split"])),
                    label_source=LabelSource(str(item["label_source"])),
                    reviewer_count=int(item["reviewer_count"]),
                    notes=str(item.get("notes", "")),
                    tags=tuple(str(x) for x in item.get("tags", ())),
                    schema_version=int(item.get("schema_version", EVAL_SCHEMA_VERSION)),
                )
            )
        except Exception as exc:
            raise ValueError(f"invalid gold JSONL at line {line_number}: {exc}") from exc
    if not cases:
        raise ValueError("gold JSONL contained no cases")
    dataset_fingerprint(cases)
    validate_split_isolation(cases)
    return tuple(cases)
