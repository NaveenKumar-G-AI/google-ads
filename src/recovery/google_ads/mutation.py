from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from recovery.negative_keywords import (
    ApprovalRecord,
    NegativeKeywordProposal,
    NegativeMutationPlan,
    ProposalDisposition,
)

from .adapter import GOOGLE_ADS_API_VERSION, GoogleAdsV26Adapter
from .auth import normalize_customer_id


@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    proposal_id: str
    plan_fingerprint: str
    validated_at: datetime
    api_version: str

    def __post_init__(self) -> None:
        if self.validated_at.tzinfo is None or self.validated_at.utcoffset() is None:
            raise ValueError("validated_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    proposal_id: str
    plan_fingerprint: str
    resource_name: str
    applied_at: datetime
    api_version: str
    readback_verified: bool

    def __post_init__(self) -> None:
        if self.applied_at.tzinfo is None or self.applied_at.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")


def mutation_plan_fingerprint(plan: NegativeMutationPlan) -> str:
    payload = asdict(plan)
    payload["match_type"] = plan.match_type.value
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class GoogleAdsNegativeMutationExecutor:
    """Executes only Phase-5 approved ad-group negative-keyword plans.

    Safety boundary:
      1) exact proposal/approval/plan consistency,
      2) Google validate_only call,
      3) short-lived validation receipt,
      4) live mutate,
      5) exact resource read-back.

    No method accepts arbitrary keyword text + ad group IDs as a shortcut.
    """

    RESOURCE_RE = re.compile(
        r"^customers/(?P<customer>\d{10})/adGroupCriteria/(?P<adgroup>\d+)~(?P<criterion>\d+)$"
    )

    def __init__(
        self,
        *,
        client: Any,
        adapter: GoogleAdsV26Adapter,
        validation_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self.client = client
        self.adapter = adapter
        if validation_ttl <= timedelta(0):
            raise ValueError("validation_ttl must be positive")
        self.validation_ttl = validation_ttl

    @staticmethod
    def _assert_approved(
        proposal: NegativeKeywordProposal,
        approval: ApprovalRecord,
        plan: NegativeMutationPlan,
    ) -> None:
        if proposal.disposition is not ProposalDisposition.READY_FOR_APPROVAL:
            raise ValueError("proposal is not eligible for live mutation")
        if approval.proposal_id != proposal.proposal_id:
            raise ValueError("approval references another proposal")
        if approval.proposal_fingerprint != proposal.fingerprint_sha256:
            raise ValueError("proposal changed after human approval")
        if plan.proposal_id != proposal.proposal_id:
            raise ValueError("mutation plan references another proposal")
        if plan.customer_id != proposal.candidate.customer_id:
            raise ValueError("mutation plan customer differs from proposal")
        if not plan.validate_only_first:
            raise ValueError("live execution requires validate_only_first")
        if plan.partial_failure:
            raise ValueError("single V1 safety mutation must not use partial_failure")

    def _operation(self, plan: NegativeMutationPlan) -> Any:
        customer_id = normalize_customer_id(plan.customer_id)
        target_parts = plan.target_resource_parent.split("/")
        if (
            len(target_parts) != 4
            or target_parts[0] != "customers"
            or target_parts[1] != customer_id
            or target_parts[2] != "adGroups"
            or not target_parts[3].isdigit()
        ):
            raise ValueError("invalid or mismatched ad-group target resource")

        operation = self.client.get_type(
            "AdGroupCriterionOperation", version=GOOGLE_ADS_API_VERSION
        )
        criterion = operation.create
        criterion.ad_group = plan.target_resource_parent
        criterion.negative = True
        criterion.keyword.text = plan.keyword_text
        try:
            criterion.keyword.match_type = getattr(
                self.client.enums.KeywordMatchTypeEnum, plan.match_type.value
            )
        except AttributeError as exc:
            raise ValueError(f"unsupported keyword match type: {plan.match_type.value}") from exc
        return operation

    def validate(
        self,
        *,
        proposal: NegativeKeywordProposal,
        approval: ApprovalRecord,
        plan: NegativeMutationPlan,
        now: datetime | None = None,
    ) -> ValidationReceipt:
        self._assert_approved(proposal, approval, plan)
        service = self.client.get_service(
            "AdGroupCriterionService", version=GOOGLE_ADS_API_VERSION
        )
        service.mutate_ad_group_criteria(
            customer_id=normalize_customer_id(plan.customer_id),
            operations=[self._operation(plan)],
            partial_failure=False,
            validate_only=True,
        )
        return ValidationReceipt(
            proposal_id=proposal.proposal_id,
            plan_fingerprint=mutation_plan_fingerprint(plan),
            validated_at=now or datetime.now(timezone.utc),
            api_version=GOOGLE_ADS_API_VERSION,
        )

    def apply(
        self,
        *,
        proposal: NegativeKeywordProposal,
        approval: ApprovalRecord,
        plan: NegativeMutationPlan,
        validation: ValidationReceipt,
        now: datetime | None = None,
    ) -> MutationReceipt:
        self._assert_approved(proposal, approval, plan)
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if validation.proposal_id != proposal.proposal_id:
            raise ValueError("validation receipt references another proposal")
        if validation.api_version != GOOGLE_ADS_API_VERSION:
            raise ValueError("validation receipt belongs to another API version")
        if validation.plan_fingerprint != mutation_plan_fingerprint(plan):
            raise ValueError("mutation plan changed after Google validation")
        if now < validation.validated_at:
            raise ValueError("application time cannot precede validation")
        if now - validation.validated_at > self.validation_ttl:
            raise ValueError("Google validation receipt is stale; validate again")

        service = self.client.get_service(
            "AdGroupCriterionService", version=GOOGLE_ADS_API_VERSION
        )
        response = service.mutate_ad_group_criteria(
            customer_id=normalize_customer_id(plan.customer_id),
            operations=[self._operation(plan)],
            partial_failure=False,
            validate_only=False,
        )
        results = tuple(response.results)
        if len(results) != 1:
            raise ValueError(f"expected one mutation result, got {len(results)}")
        resource_name = str(results[0].resource_name)
        match = self.RESOURCE_RE.fullmatch(resource_name)
        if not match:
            raise ValueError(f"unexpected ad-group criterion resource name: {resource_name}")
        expected_ad_group = plan.target_resource_parent.rsplit("/", 1)[-1]
        if (
            match.group("customer") != normalize_customer_id(plan.customer_id)
            or match.group("adgroup") != expected_ad_group
        ):
            raise ValueError("Google returned a resource outside the approved target scope")

        readback = self.adapter.find_applied_ad_group_negative(
            customer_id=normalize_customer_id(plan.customer_id),
            ad_group_id=expected_ad_group,
            resource_name=resource_name,
        )
        verified = bool(
            readback is not None
            and readback.text == plan.keyword_text
            and readback.match_type is plan.match_type
            and readback.resource_name == resource_name
        )
        if not verified:
            raise RuntimeError(
                "mutation returned success but exact live negative could not be verified by read-back"
            )
        return MutationReceipt(
            proposal_id=proposal.proposal_id,
            plan_fingerprint=mutation_plan_fingerprint(plan),
            resource_name=resource_name,
            applied_at=now,
            api_version=GOOGLE_ADS_API_VERSION,
            readback_verified=True,
        )

    def rollback(self, *, receipt: MutationReceipt) -> None:
        """Remove only the exact resource created by this executor receipt."""

        match = self.RESOURCE_RE.fullmatch(receipt.resource_name)
        if not match:
            raise ValueError("invalid ad-group criterion resource name")
        operation = self.client.get_type(
            "AdGroupCriterionOperation", version=GOOGLE_ADS_API_VERSION
        )
        operation.remove = receipt.resource_name
        service = self.client.get_service(
            "AdGroupCriterionService", version=GOOGLE_ADS_API_VERSION
        )
        response = service.mutate_ad_group_criteria(
            customer_id=match.group("customer"),
            operations=[operation],
            partial_failure=False,
            validate_only=False,
        )
        results = tuple(response.results)
        if len(results) != 1:
            raise RuntimeError("rollback did not return exactly one result")
