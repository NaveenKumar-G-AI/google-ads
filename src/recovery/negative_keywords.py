from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
import unicodedata
from typing import Iterable, Sequence

from .evidence import EvidenceDisposition, SearchTermEvidence

NEGATIVE_ACTION_SCHEMA_VERSION = 1
MAX_KEYWORD_CHARS = 80
MAX_KEYWORD_WORDS = 10


class NegativeMatchType(str, Enum):
    BROAD = "BROAD"
    PHRASE = "PHRASE"
    EXACT = "EXACT"


class NegativeScope(str, Enum):
    AD_GROUP = "ad_group"
    CAMPAIGN = "campaign"
    SHARED_LIST = "shared_list"
    ACCOUNT = "account"


class ProposalDisposition(str, Enum):
    READY_FOR_APPROVAL = "ready_for_approval"
    REVIEW_REQUIRED = "review_required"
    ALREADY_COVERED = "already_covered"
    BLOCKED = "blocked"


class ProposalRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class ProposalReasonCode(str, Enum):
    EXACT_DEFAULT = "exact_default"
    NARROWEST_SCOPE_DEFAULT = "narrowest_scope_default"
    EVIDENCE_NOT_ELIGIBLE = "evidence_not_eligible"
    EVIDENCE_BUNDLE_INCOMPLETE = "evidence_bundle_incomplete"
    SCOPE_MISMATCH = "scope_mismatch"
    MIXED_EVIDENCE_DISPOSITION = "mixed_evidence_disposition"
    QUERY_TOO_LONG = "query_too_long"
    QUERY_TOO_MANY_WORDS = "query_too_many_words"
    EXISTING_NEGATIVE_COVERS_QUERY = "existing_negative_covers_query"
    POSITIVE_KEYWORD_COLLISION = "positive_keyword_collision"
    PROTECTED_QUERY_COLLISION = "protected_query_collision"
    BROADER_MATCH_REQUIRES_REVIEW = "broader_match_requires_review"
    BROADER_SCOPE_REQUIRES_REVIEW = "broader_scope_requires_review"
    SAFE_EXACT_CANDIDATE = "safe_exact_candidate"
    MUTATION_REQUIRES_HUMAN_APPROVAL = "mutation_requires_human_approval"
    VALIDATE_ONLY_REQUIRED = "validate_only_required"


@dataclass(frozen=True, slots=True)
class ProposalReason:
    code: ProposalReasonCode
    message: str
    decisive: bool


@dataclass(frozen=True, slots=True)
class ExistingNegativeKeyword:
    text: str
    match_type: NegativeMatchType
    scope: NegativeScope
    customer_id: str
    campaign_id: str | None = None
    ad_group_id: str | None = None
    shared_set_id: str | None = None
    applied_campaign_ids: tuple[str, ...] = ()
    resource_name: str | None = None

    def __post_init__(self) -> None:
        _validate_keyword_text(self.text)
        if self.scope is NegativeScope.AD_GROUP:
            if not self.campaign_id or not self.ad_group_id:
                raise ValueError("ad-group negative requires campaign_id and ad_group_id")
        elif self.scope is NegativeScope.CAMPAIGN:
            if not self.campaign_id:
                raise ValueError("campaign negative requires campaign_id")
        elif self.scope is NegativeScope.SHARED_LIST:
            if not self.shared_set_id:
                raise ValueError("shared-list negative requires shared_set_id")
            if not self.applied_campaign_ids:
                raise ValueError("shared-list negative requires applied_campaign_ids")
        elif self.scope is NegativeScope.ACCOUNT:
            if self.campaign_id or self.ad_group_id:
                raise ValueError("account negative cannot be scoped to campaign/ad group")


@dataclass(frozen=True, slots=True)
class PositiveKeyword:
    text: str
    match_type: str
    customer_id: str
    campaign_id: str
    ad_group_id: str
    status: str = "ENABLED"
    resource_name: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("positive keyword text cannot be blank")


@dataclass(frozen=True, slots=True)
class ProtectedQuery:
    """A query the operator/system has evidence should remain eligible.

    Phase 5 does not decide whether a query is valuable. It only consumes protected
    query facts produced elsewhere (for example, confirmed conversions, owner rules,
    or manually protected brand traffic).
    """

    query: str
    customer_id: str
    campaign_id: str
    ad_group_id: str | None
    reason: str
    source: str

    def __post_init__(self) -> None:
        if not self.query.strip() or not self.reason.strip() or not self.source.strip():
            raise ValueError("protected query, reason, and source are required")


@dataclass(frozen=True, slots=True)
class ScopeEvidenceBundle:
    """Evidence snapshot for one action scope.

    `complete_for_scope` must only be true when the caller built the bundle from the
    complete Phase-4 result set for this exact customer/campaign/ad-group/query scope.
    This prevents a single cherry-picked finding from authorizing an account change.
    """

    findings: tuple[SearchTermEvidence, ...]
    complete_for_scope: bool
    snapshot_id: str

    def __post_init__(self) -> None:
        if not self.findings:
            raise ValueError("evidence bundle requires at least one finding")
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id is required")


@dataclass(frozen=True, slots=True)
class NegativeKeywordCandidate:
    text: str
    match_type: NegativeMatchType
    scope: NegativeScope
    customer_id: str
    campaign_id: str | None
    ad_group_id: str | None

    def __post_init__(self) -> None:
        _validate_keyword_text(self.text)
        if self.scope is NegativeScope.AD_GROUP:
            if not self.campaign_id or not self.ad_group_id:
                raise ValueError("ad-group candidate requires campaign_id and ad_group_id")
        elif self.scope is NegativeScope.CAMPAIGN:
            if not self.campaign_id or self.ad_group_id is not None:
                raise ValueError("campaign candidate requires campaign_id and no ad_group_id")
        elif self.scope in {NegativeScope.ACCOUNT, NegativeScope.SHARED_LIST}:
            if self.ad_group_id is not None:
                raise ValueError("broad scope candidate cannot include ad_group_id")


@dataclass(frozen=True, slots=True)
class Collision:
    source: str
    text: str
    detail: str


@dataclass(frozen=True, slots=True)
class NegativeKeywordProposal:
    proposal_id: str
    candidate: NegativeKeywordCandidate
    truth_fingerprint: str
    evidence_snapshot_id: str
    evidence_observation_ids: tuple[str, ...]
    disposition: ProposalDisposition
    risk: ProposalRisk
    reasons: tuple[ProposalReason, ...]
    protected_query_collisions: tuple[Collision, ...]
    positive_keyword_collisions: tuple[Collision, ...]
    existing_covering_negative_resource_names: tuple[str, ...]
    potentially_avoidable_cost_micros: int
    currency_code: str
    schema_version: int = NEGATIVE_ACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != NEGATIVE_ACTION_SCHEMA_VERSION:
            raise ValueError("unsupported negative action schema version")
        if self.potentially_avoidable_cost_micros < 0:
            raise ValueError("potentially_avoidable_cost_micros cannot be negative")

    @property
    def requires_human_approval(self) -> bool:
        return self.disposition is ProposalDisposition.READY_FOR_APPROVAL

    @property
    def fingerprint_sha256(self) -> str:
        payload = {
            "proposal_id": self.proposal_id,
            "candidate": {
                "text": self.candidate.text,
                "match_type": self.candidate.match_type.value,
                "scope": self.candidate.scope.value,
                "customer_id": self.candidate.customer_id,
                "campaign_id": self.candidate.campaign_id,
                "ad_group_id": self.candidate.ad_group_id,
            },
            "truth_fingerprint": self.truth_fingerprint,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "evidence_observation_ids": self.evidence_observation_ids,
            "disposition": self.disposition.value,
            "risk": self.risk.value,
            "cost": self.potentially_avoidable_cost_micros,
            "currency": self.currency_code,
            "schema": self.schema_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    proposal_id: str
    proposal_fingerprint: str
    approved_by: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise ValueError("approved_by is required")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class NegativeMutationPlan:
    proposal_id: str
    customer_id: str
    service: str
    operation: str
    target_resource_parent: str
    keyword_text: str
    match_type: NegativeMatchType
    negative: bool
    validate_only_first: bool
    partial_failure: bool
    rollback_strategy: str


def _tokenize(text: str) -> tuple[str, ...]:
    """Conservative punctuation-insensitive tokenizer for collision analysis.

    This is intentionally an internal *risk screen*, not a claim that it reproduces
    Google's auction matcher. Removing punctuation can create extra false-positive
    collisions, which is safer than missing an obvious protected-query collision.
    """

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return tuple(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", normalized, flags=re.UNICODE))


def _validate_keyword_text(text: str) -> None:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("negative keyword text cannot be blank")
    if len(cleaned) > MAX_KEYWORD_CHARS:
        raise ValueError(f"negative keyword exceeds {MAX_KEYWORD_CHARS} characters")
    if len(_tokenize(cleaned)) > MAX_KEYWORD_WORDS:
        raise ValueError(f"negative keyword exceeds {MAX_KEYWORD_WORDS} words")


def negative_would_block_query(
    *, negative_text: str, match_type: NegativeMatchType, query: str
) -> bool:
    """Risk-screen approximation of documented Search negative match semantics.

    - BROAD: all negative terms appear in the query, any order.
    - PHRASE: all negative terms appear contiguously, same order.
    - EXACT: the query has exactly the same normalized token sequence.

    Google has additional normalization/misspelling behavior that is not exposed as a
    public deterministic matcher. We therefore use this only to detect known collisions;
    it is never treated as proof that no possible collision can occur.
    """

    neg = _tokenize(negative_text)
    q = _tokenize(query)
    if not neg or not q:
        return False
    if match_type is NegativeMatchType.EXACT:
        return q == neg
    if match_type is NegativeMatchType.PHRASE:
        n = len(neg)
        return any(q[i : i + n] == neg for i in range(0, len(q) - n + 1))
    if match_type is NegativeMatchType.BROAD:
        # Terms are treated as a multiset so repeated negative words remain meaningful.
        remaining = list(q)
        for term in neg:
            try:
                remaining.remove(term)
            except ValueError:
                return False
        return True
    raise ValueError(f"unsupported match type: {match_type}")


def _negative_applies_to(
    negative: ExistingNegativeKeyword,
    *,
    customer_id: str,
    campaign_id: str,
    ad_group_id: str,
) -> bool:
    if negative.customer_id != customer_id:
        return False
    if negative.scope is NegativeScope.ACCOUNT:
        return True
    if negative.scope is NegativeScope.CAMPAIGN:
        return negative.campaign_id == campaign_id
    if negative.scope is NegativeScope.AD_GROUP:
        return (
            negative.campaign_id == campaign_id and negative.ad_group_id == ad_group_id
        )
    if negative.scope is NegativeScope.SHARED_LIST:
        return campaign_id in negative.applied_campaign_ids
    return False


def _positive_applies_to_candidate(
    keyword: PositiveKeyword, candidate: NegativeKeywordCandidate
) -> bool:
    if keyword.customer_id != candidate.customer_id:
        return False
    if candidate.scope is NegativeScope.AD_GROUP:
        return (
            keyword.campaign_id == candidate.campaign_id
            and keyword.ad_group_id == candidate.ad_group_id
        )
    if candidate.scope is NegativeScope.CAMPAIGN:
        return keyword.campaign_id == candidate.campaign_id
    return candidate.scope in {NegativeScope.ACCOUNT, NegativeScope.SHARED_LIST}


def _protected_applies_to_candidate(
    item: ProtectedQuery, candidate: NegativeKeywordCandidate
) -> bool:
    if item.customer_id != candidate.customer_id:
        return False
    if candidate.scope is NegativeScope.AD_GROUP:
        return (
            item.campaign_id == candidate.campaign_id
            and (item.ad_group_id is None or item.ad_group_id == candidate.ad_group_id)
        )
    if candidate.scope is NegativeScope.CAMPAIGN:
        return item.campaign_id == candidate.campaign_id
    return candidate.scope in {NegativeScope.ACCOUNT, NegativeScope.SHARED_LIST}


class SafeNegativeKeywordEngine:
    """Build human-approval-ready negative proposals without mutating Google Ads.

    V1 automatic generation is deliberately restricted to negative EXACT at the
    source ad-group. Broader match types/scopes can be *evaluated* but are never
    promoted to low-risk auto-generated actions here.
    """

    def propose_exact_from_evidence(
        self,
        *,
        bundle: ScopeEvidenceBundle,
        existing_negatives: Sequence[ExistingNegativeKeyword] = (),
        positive_keywords: Sequence[PositiveKeyword] = (),
        protected_queries: Sequence[ProtectedQuery] = (),
    ) -> NegativeKeywordProposal:
        findings = bundle.findings
        first = findings[0]
        query = first.key.normalized_query
        customer_id = first.key.customer_id
        campaign_id = first.key.campaign_id
        ad_group_id = first.key.ad_group_id

        # All evidence in this bundle must describe the same action scope/query.
        for finding in findings:
            if (
                finding.key.customer_id != customer_id
                or finding.key.campaign_id != campaign_id
                or finding.key.ad_group_id != ad_group_id
                or finding.key.normalized_query != query
            ):
                return self._blocked_from_scope_mismatch(bundle)

        candidate = NegativeKeywordCandidate(
            text=query,
            match_type=NegativeMatchType.EXACT,
            scope=NegativeScope.AD_GROUP,
            customer_id=customer_id,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
        )
        return self.assess_candidate(
            candidate=candidate,
            bundle=bundle,
            existing_negatives=existing_negatives,
            positive_keywords=positive_keywords,
            protected_queries=protected_queries,
            generated_by_default=True,
        )

    def assess_candidate(
        self,
        *,
        candidate: NegativeKeywordCandidate,
        bundle: ScopeEvidenceBundle,
        existing_negatives: Sequence[ExistingNegativeKeyword] = (),
        positive_keywords: Sequence[PositiveKeyword] = (),
        protected_queries: Sequence[ProtectedQuery] = (),
        generated_by_default: bool = False,
    ) -> NegativeKeywordProposal:
        findings = bundle.findings
        first = findings[0]
        reasons: list[ProposalReason] = []

        same_truth = {x.truth_fingerprint for x in findings}
        same_currency = {x.currency_code for x in findings}
        all_observation_ids = tuple(
            sorted({oid for finding in findings for oid in finding.observation_ids})
        )
        potentially_avoidable = sum(
            finding.potentially_avoidable_cost_micros for finding in findings
        )

        if len(same_truth) != 1 or len(same_currency) != 1:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.SCOPE_MISMATCH,
                    "Evidence bundle mixes incompatible truth snapshots or currencies.",
                    True,
                )
            )
            return self._proposal(
                candidate,
                bundle,
                first.truth_fingerprint,
                first.currency_code,
                all_observation_ids,
                0,
                ProposalDisposition.BLOCKED,
                ProposalRisk.BLOCKED,
                reasons,
                (),
                (),
                (),
            )

        if not bundle.complete_for_scope:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.EVIDENCE_BUNDLE_INCOMPLETE,
                    "Action scope was not evaluated from a complete evidence snapshot.",
                    True,
                )
            )
            return self._proposal(
                candidate,
                bundle,
                first.truth_fingerprint,
                first.currency_code,
                all_observation_ids,
                0,
                ProposalDisposition.BLOCKED,
                ProposalRisk.BLOCKED,
                reasons,
                (),
                (),
                (),
            )

        if any(
            x.key.customer_id != candidate.customer_id
            or x.key.campaign_id != candidate.campaign_id
            or (
                candidate.scope is NegativeScope.AD_GROUP
                and x.key.ad_group_id != candidate.ad_group_id
            )
            for x in findings
        ):
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.SCOPE_MISMATCH,
                    "Candidate target scope does not match its Phase-4 evidence scope.",
                    True,
                )
            )
            return self._proposal(
                candidate,
                bundle,
                first.truth_fingerprint,
                first.currency_code,
                all_observation_ids,
                0,
                ProposalDisposition.BLOCKED,
                ProposalRisk.BLOCKED,
                reasons,
                (),
                (),
                (),
            )

        if any(x.key.normalized_query != first.key.normalized_query for x in findings):
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.SCOPE_MISMATCH,
                    "One action proposal cannot combine different observed queries.",
                    True,
                )
            )
            return self._proposal(
                candidate,
                bundle,
                first.truth_fingerprint,
                first.currency_code,
                all_observation_ids,
                0,
                ProposalDisposition.BLOCKED,
                ProposalRisk.BLOCKED,
                reasons,
                (),
                (),
                (),
            )

        if any(x.disposition is not EvidenceDisposition.POTENTIALLY_AVOIDABLE for x in findings):
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.MIXED_EVIDENCE_DISPOSITION,
                    "At least one scoped Phase-4 finding requires review or is not a new recovery opportunity.",
                    True,
                )
            )
            return self._proposal(
                candidate,
                bundle,
                first.truth_fingerprint,
                first.currency_code,
                all_observation_ids,
                0,
                ProposalDisposition.BLOCKED,
                ProposalRisk.BLOCKED,
                reasons,
                (),
                (),
                (),
            )

        if generated_by_default:
            reasons.extend(
                [
                    ProposalReason(
                        ProposalReasonCode.EXACT_DEFAULT,
                        "Generated from an observed query as negative EXACT, matching Google Ads' conservative Search Terms workflow default.",
                        False,
                    ),
                    ProposalReason(
                        ProposalReasonCode.NARROWEST_SCOPE_DEFAULT,
                        "Generated at the source ad-group, the narrowest V1 action scope.",
                        False,
                    ),
                ]
            )

        if candidate.match_type is not NegativeMatchType.EXACT:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.BROADER_MATCH_REQUIRES_REVIEW,
                    "Phrase/broad negatives can block additional searches and are not low-risk V1 generated actions.",
                    True,
                )
            )

        if candidate.scope is not NegativeScope.AD_GROUP:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.BROADER_SCOPE_REQUIRES_REVIEW,
                    "Campaign/shared/account scope can affect additional ad groups and is not a low-risk V1 generated action.",
                    True,
                )
            )

        covering = tuple(
            sorted(
                {
                    n.resource_name or f"{n.scope.value}:{n.text}:{n.match_type.value}"
                    for n in existing_negatives
                    if _negative_applies_to(
                        n,
                        customer_id=candidate.customer_id,
                        campaign_id=candidate.campaign_id or "",
                        ad_group_id=candidate.ad_group_id or "",
                    )
                    and negative_would_block_query(
                        negative_text=n.text,
                        match_type=n.match_type,
                        query=first.key.normalized_query,
                    )
                }
            )
        )
        if covering:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.EXISTING_NEGATIVE_COVERS_QUERY,
                    "An existing effective negative already appears to block this observed query.",
                    True,
                )
            )

        positive_collisions = tuple(
            Collision(
                source="positive_keyword",
                text=k.text,
                detail=f"{k.match_type} positive keyword in campaign {k.campaign_id}, ad group {k.ad_group_id}",
            )
            for k in positive_keywords
            if k.status.upper() not in {"REMOVED"}
            and _positive_applies_to_candidate(k, candidate)
            and negative_would_block_query(
                negative_text=candidate.text,
                match_type=candidate.match_type,
                query=k.text,
            )
        )
        if positive_collisions:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.POSITIVE_KEYWORD_COLLISION,
                    "Candidate would collide with at least one current positive keyword text; operator review is required.",
                    True,
                )
            )

        protected_collisions = tuple(
            Collision(source=p.source, text=p.query, detail=p.reason)
            for p in protected_queries
            if _protected_applies_to_candidate(p, candidate)
            and negative_would_block_query(
                negative_text=candidate.text,
                match_type=candidate.match_type,
                query=p.query,
            )
        )
        if protected_collisions:
            reasons.append(
                ProposalReason(
                    ProposalReasonCode.PROTECTED_QUERY_COLLISION,
                    "Candidate would block a query explicitly marked as protected/valuable.",
                    True,
                )
            )

        if covering:
            disposition = ProposalDisposition.ALREADY_COVERED
            risk = ProposalRisk.LOW
        elif protected_collisions:
            disposition = ProposalDisposition.BLOCKED
            risk = ProposalRisk.BLOCKED
        elif positive_collisions:
            disposition = ProposalDisposition.REVIEW_REQUIRED
            risk = ProposalRisk.HIGH
        elif candidate.match_type is not NegativeMatchType.EXACT or candidate.scope is not NegativeScope.AD_GROUP:
            disposition = ProposalDisposition.REVIEW_REQUIRED
            risk = ProposalRisk.MEDIUM
        else:
            disposition = ProposalDisposition.READY_FOR_APPROVAL
            risk = ProposalRisk.LOW
            reasons.extend(
                [
                    ProposalReason(
                        ProposalReasonCode.SAFE_EXACT_CANDIDATE,
                        "No known existing-negative, protected-query, or positive-keyword collision was found for the exact ad-group candidate.",
                        False,
                    ),
                    ProposalReason(
                        ProposalReasonCode.MUTATION_REQUIRES_HUMAN_APPROVAL,
                        "No Google Ads mutation may be created until a human approves this exact proposal fingerprint.",
                        True,
                    ),
                ]
            )

        return self._proposal(
            candidate,
            bundle,
            first.truth_fingerprint,
            first.currency_code,
            all_observation_ids,
            potentially_avoidable,
            disposition,
            risk,
            reasons,
            protected_collisions,
            positive_collisions,
            covering,
        )

    def _blocked_from_scope_mismatch(
        self, bundle: ScopeEvidenceBundle
    ) -> NegativeKeywordProposal:
        first = bundle.findings[0]
        candidate = NegativeKeywordCandidate(
            text=first.key.normalized_query,
            match_type=NegativeMatchType.EXACT,
            scope=NegativeScope.AD_GROUP,
            customer_id=first.key.customer_id,
            campaign_id=first.key.campaign_id,
            ad_group_id=first.key.ad_group_id,
        )
        return self._proposal(
            candidate,
            bundle,
            first.truth_fingerprint,
            first.currency_code,
            tuple(sorted({oid for f in bundle.findings for oid in f.observation_ids})),
            0,
            ProposalDisposition.BLOCKED,
            ProposalRisk.BLOCKED,
            [
                ProposalReason(
                    ProposalReasonCode.SCOPE_MISMATCH,
                    "Evidence bundle mixes different customer/campaign/ad-group/query scopes.",
                    True,
                )
            ],
            (),
            (),
            (),
        )

    @staticmethod
    def _proposal(
        candidate: NegativeKeywordCandidate,
        bundle: ScopeEvidenceBundle,
        truth_fingerprint: str,
        currency_code: str,
        observation_ids: tuple[str, ...],
        cost_micros: int,
        disposition: ProposalDisposition,
        risk: ProposalRisk,
        reasons: Iterable[ProposalReason],
        protected_collisions: tuple[Collision, ...],
        positive_collisions: tuple[Collision, ...],
        covering: tuple[str, ...],
    ) -> NegativeKeywordProposal:
        seed = "\x1f".join(
            [
                candidate.customer_id,
                candidate.campaign_id or "",
                candidate.ad_group_id or "",
                candidate.scope.value,
                candidate.match_type.value,
                candidate.text.casefold(),
                truth_fingerprint,
                bundle.snapshot_id,
                *observation_ids,
            ]
        ).encode()
        proposal_id = hashlib.sha256(seed).hexdigest()[:24]
        return NegativeKeywordProposal(
            proposal_id=proposal_id,
            candidate=candidate,
            truth_fingerprint=truth_fingerprint,
            evidence_snapshot_id=bundle.snapshot_id,
            evidence_observation_ids=observation_ids,
            disposition=disposition,
            risk=risk,
            reasons=tuple(reasons),
            protected_query_collisions=protected_collisions,
            positive_keyword_collisions=positive_collisions,
            existing_covering_negative_resource_names=covering,
            potentially_avoidable_cost_micros=cost_micros,
            currency_code=currency_code,
        )


def build_mutation_plan(
    proposal: NegativeKeywordProposal, approval: ApprovalRecord
) -> NegativeMutationPlan:
    """Create an execution plan only after exact-fingerprint human approval.

    The plan deliberately requires a Google Ads `validate_only` pass before execution.
    This function still does not call Google Ads.
    """

    if proposal.disposition is not ProposalDisposition.READY_FOR_APPROVAL:
        raise ValueError("only READY_FOR_APPROVAL proposals can become mutation plans")
    if proposal.candidate.scope is not NegativeScope.AD_GROUP:
        raise ValueError("Phase 5 mutation planning only supports ad-group scope")
    if approval.proposal_id != proposal.proposal_id:
        raise ValueError("approval references a different proposal")
    if approval.proposal_fingerprint != proposal.fingerprint_sha256:
        raise ValueError("proposal changed after approval")

    target = (
        f"customers/{proposal.candidate.customer_id}/adGroups/"
        f"{proposal.candidate.ad_group_id}"
    )
    return NegativeMutationPlan(
        proposal_id=proposal.proposal_id,
        customer_id=proposal.candidate.customer_id,
        service="AdGroupCriterionService.MutateAdGroupCriteria",
        operation="CREATE_NEGATIVE_KEYWORD",
        target_resource_parent=target,
        keyword_text=proposal.candidate.text,
        match_type=proposal.candidate.match_type,
        negative=True,
        validate_only_first=True,
        partial_failure=False,
        rollback_strategy=(
            "After creation, persist the returned ad_group_criterion resource_name; "
            "rollback removes that exact created resource."
        ),
    )
