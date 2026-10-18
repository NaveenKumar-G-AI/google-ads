from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from recovery.domain import CoverageBand
from recovery.evidence import EvidenceDisposition, SearchTermEvidence, SearchTermEvidenceKey
from recovery.google_ads.mutation import GoogleAdsNegativeMutationExecutor
from recovery.negative_keywords import (
    ApprovalRecord,
    ExistingNegativeKeyword,
    NegativeMatchType,
    NegativeScope,
    SafeNegativeKeywordEngine,
    ScopeEvidenceBundle,
    build_mutation_plan,
)


CUSTOMER = "1234567890"


def approved_objects():
    finding = SearchTermEvidence(
        key=SearchTermEvidenceKey(CUSTOMER, "10", "20", "roof replacement jobs", "SEARCH"),
        raw_query_examples=("roof replacement jobs",),
        truth_fingerprint="a" * 64,
        disposition=EvidenceDisposition.POTENTIALLY_AVOIDABLE,
        reasons=(),
        coverage_band=CoverageBand.HIGH,
        semantic_support=Decimal("0.99"),
        currency_code="USD",
        mature_cost_micros=8_500_000,
        immature_cost_micros=0,
        mature_clicks=12,
        immature_clicks=0,
        mature_conversions=Decimal("0"),
        mature_conversion_value=Decimal("0"),
        mature_all_conversions=Decimal("0"),
        mature_all_conversion_value=Decimal("0"),
        first_observation_date=date(2026, 9, 1),
        last_observation_date=date(2026, 9, 30),
        observation_ids=("obs-1",),
        targeting_statuses=("NONE",),
    )
    proposal = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=ScopeEvidenceBundle((finding,), True, "snap-1")
    )
    approval = ApprovalRecord(
        proposal_id=proposal.proposal_id,
        proposal_fingerprint=proposal.fingerprint_sha256,
        approved_by="owner",
        approved_at=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
    )
    return proposal, approval, build_mutation_plan(proposal, approval)


class FakeOperation:
    def __init__(self):
        self.create = SimpleNamespace(
            ad_group="",
            negative=False,
            keyword=SimpleNamespace(text="", match_type=None),
        )
        self.remove = ""


class FakeMutateService:
    def __init__(self):
        self.calls = []

    def mutate_ad_group_criteria(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["validate_only"]:
            return SimpleNamespace(results=[])
        if kwargs["operations"][0].remove:
            return SimpleNamespace(results=[SimpleNamespace(resource_name=kwargs["operations"][0].remove)])
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    resource_name=f"customers/{CUSTOMER}/adGroupCriteria/20~777"
                )
            ]
        )


class FakeEnums:
    class KeywordMatchTypeEnum:
        EXACT = "EXACT_ENUM"
        PHRASE = "PHRASE_ENUM"
        BROAD = "BROAD_ENUM"


class FakeClient:
    def __init__(self):
        self.enums = FakeEnums()
        self.service = FakeMutateService()

    def get_type(self, name, version=None):
        assert name == "AdGroupCriterionOperation"
        assert version == "v26"
        return FakeOperation()

    def get_service(self, name, version=None):
        assert name == "AdGroupCriterionService"
        assert version == "v26"
        return self.service


class FakeAdapter:
    def find_applied_ad_group_negative(self, *, customer_id, ad_group_id, resource_name):
        return ExistingNegativeKeyword(
            text="roof replacement jobs",
            match_type=NegativeMatchType.EXACT,
            scope=NegativeScope.AD_GROUP,
            customer_id=CUSTOMER,
            campaign_id="10",
            ad_group_id="20",
            resource_name=resource_name,
        )


def test_live_mutation_requires_validate_only_then_exact_readback():
    proposal, approval, plan = approved_objects()
    client = FakeClient()
    executor = GoogleAdsNegativeMutationExecutor(client=client, adapter=FakeAdapter())
    validation = executor.validate(
        proposal=proposal,
        approval=approval,
        plan=plan,
        now=datetime(2026, 10, 15, 10, 1, tzinfo=timezone.utc),
    )
    receipt = executor.apply(
        proposal=proposal,
        approval=approval,
        plan=plan,
        validation=validation,
        now=datetime(2026, 10, 15, 10, 2, tzinfo=timezone.utc),
    )
    assert [c["validate_only"] for c in client.service.calls] == [True, False]
    create = client.service.calls[1]["operations"][0].create
    assert create.negative is True
    assert create.keyword.text == "roof replacement jobs"
    assert create.keyword.match_type == "EXACT_ENUM"
    assert receipt.readback_verified is True
    assert receipt.resource_name.endswith("20~777")


def test_stale_validation_cannot_be_used_for_live_change():
    proposal, approval, plan = approved_objects()
    executor = GoogleAdsNegativeMutationExecutor(client=FakeClient(), adapter=FakeAdapter())
    validation = executor.validate(
        proposal=proposal,
        approval=approval,
        plan=plan,
        now=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="stale"):
        executor.apply(
            proposal=proposal,
            approval=approval,
            plan=plan,
            validation=validation,
            now=datetime(2026, 10, 15, 10, 16, tzinfo=timezone.utc),
        )


def test_rollback_removes_only_resource_from_receipt():
    proposal, approval, plan = approved_objects()
    client = FakeClient()
    executor = GoogleAdsNegativeMutationExecutor(client=client, adapter=FakeAdapter())
    validation = executor.validate(
        proposal=proposal,
        approval=approval,
        plan=plan,
        now=datetime(2026, 10, 15, 10, 1, tzinfo=timezone.utc),
    )
    receipt = executor.apply(
        proposal=proposal,
        approval=approval,
        plan=plan,
        validation=validation,
        now=datetime(2026, 10, 15, 10, 2, tzinfo=timezone.utc),
    )
    executor.rollback(receipt=receipt)
    rollback_call = client.service.calls[-1]
    assert rollback_call["operations"][0].remove == receipt.resource_name
    assert rollback_call["validate_only"] is False
