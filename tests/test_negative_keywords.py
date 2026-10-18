from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from recovery.domain import CoverageBand
from recovery.evidence import EvidenceDisposition, SearchTermEvidence, SearchTermEvidenceKey
from recovery.negative_keywords import (
    ApprovalRecord,
    ExistingNegativeKeyword,
    NegativeKeywordCandidate,
    NegativeMatchType,
    NegativeScope,
    PositiveKeyword,
    ProposalDisposition,
    ProtectedQuery,
    SafeNegativeKeywordEngine,
    ScopeEvidenceBundle,
    build_mutation_plan,
    negative_would_block_query,
)


def finding(*, network="SEARCH", disposition=EvidenceDisposition.POTENTIALLY_AVOIDABLE, query="roof replacement jobs"):
    return SearchTermEvidence(
        key=SearchTermEvidenceKey("1", "10", "20", query, network),
        raw_query_examples=(query,),
        truth_fingerprint="a" * 64,
        disposition=disposition,
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
        observation_ids=(f"obs-{network}",),
        targeting_statuses=("NONE",),
    )


def bundle(*items, complete=True):
    return ScopeEvidenceBundle(tuple(items or (finding(),)), complete, "snap-1")


def test_negative_exact_only_blocks_same_token_sequence():
    assert negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.EXACT, query="running shoes")
    assert not negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.EXACT, query="blue running shoes")


def test_negative_phrase_requires_same_order_contiguous():
    assert negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.PHRASE, query="blue running shoes sale")
    assert not negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.PHRASE, query="shoes for running")


def test_negative_broad_requires_all_terms_any_order():
    assert negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.BROAD, query="cheap shoes for running")
    assert not negative_would_block_query(negative_text="running shoes", match_type=NegativeMatchType.BROAD, query="running socks")


def test_plural_is_not_silently_treated_as_same_variant():
    assert not negative_would_block_query(negative_text="house", match_type=NegativeMatchType.BROAD, query="houses")


def test_default_proposal_is_exact_at_source_ad_group():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle(finding()))
    assert p.candidate.match_type is NegativeMatchType.EXACT
    assert p.candidate.scope is NegativeScope.AD_GROUP
    assert p.candidate.ad_group_id == "20"
    assert p.disposition is ProposalDisposition.READY_FOR_APPROVAL
    assert p.requires_human_approval


def test_incomplete_evidence_snapshot_blocks_action():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle(finding(), complete=False))
    assert p.disposition is ProposalDisposition.BLOCKED


def test_review_required_phase4_evidence_cannot_authorize_negative():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding(disposition=EvidenceDisposition.REVIEW_REQUIRED))
    )
    assert p.disposition is ProposalDisposition.BLOCKED


def test_mixed_network_findings_can_share_exact_action_only_if_all_are_candidates():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding(network="SEARCH"), finding(network="SEARCH_PARTNERS"))
    )
    assert p.disposition is ProposalDisposition.READY_FOR_APPROVAL
    assert p.potentially_avoidable_cost_micros == 17_000_000


def test_one_network_with_conversion_review_blocks_combined_action():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(
            finding(network="SEARCH"),
            finding(network="SEARCH_PARTNERS", disposition=EvidenceDisposition.REVIEW_REQUIRED),
        )
    )
    assert p.disposition is ProposalDisposition.BLOCKED


def test_existing_broader_negative_marks_candidate_already_covered():
    existing = ExistingNegativeKeyword(
        text="jobs",
        match_type=NegativeMatchType.BROAD,
        scope=NegativeScope.CAMPAIGN,
        customer_id="1",
        campaign_id="10",
        resource_name="customers/1/campaignCriteria/10~99",
    )
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), existing_negatives=(existing,)
    )
    assert p.disposition is ProposalDisposition.ALREADY_COVERED
    assert p.potentially_avoidable_cost_micros == 8_500_000


def test_unrelated_existing_negative_does_not_cover_query():
    existing = ExistingNegativeKeyword(
        text="salary",
        match_type=NegativeMatchType.BROAD,
        scope=NegativeScope.CAMPAIGN,
        customer_id="1",
        campaign_id="10",
    )
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), existing_negatives=(existing,)
    )
    assert p.disposition is ProposalDisposition.READY_FOR_APPROVAL


def test_protected_query_collision_blocks_action():
    protected = ProtectedQuery(
        query="roof replacement jobs",
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
        reason="Owner explicitly protects this query",
        source="operator",
    )
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), protected_queries=(protected,)
    )
    assert p.disposition is ProposalDisposition.BLOCKED


def test_positive_keyword_collision_routes_to_review():
    kw = PositiveKeyword(
        text="roof replacement jobs",
        match_type="EXACT",
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), positive_keywords=(kw,)
    )
    assert p.disposition is ProposalDisposition.REVIEW_REQUIRED


def test_positive_keyword_in_other_ad_group_does_not_collide_with_ad_group_negative():
    kw = PositiveKeyword(
        text="roof replacement jobs",
        match_type="EXACT",
        customer_id="1",
        campaign_id="10",
        ad_group_id="999",
    )
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), positive_keywords=(kw,)
    )
    assert p.disposition is ProposalDisposition.READY_FOR_APPROVAL


def test_broad_candidate_is_review_only_even_without_known_collision():
    candidate = NegativeKeywordCandidate(
        text="jobs",
        match_type=NegativeMatchType.BROAD,
        scope=NegativeScope.AD_GROUP,
        customer_id="1",
        campaign_id="10",
        ad_group_id="20",
    )
    p = SafeNegativeKeywordEngine().assess_candidate(candidate=candidate, bundle=bundle(finding()))
    assert p.disposition is ProposalDisposition.REVIEW_REQUIRED


def test_campaign_scope_candidate_is_review_only():
    candidate = NegativeKeywordCandidate(
        text="roof replacement jobs",
        match_type=NegativeMatchType.EXACT,
        scope=NegativeScope.CAMPAIGN,
        customer_id="1",
        campaign_id="10",
        ad_group_id=None,
    )
    p = SafeNegativeKeywordEngine().assess_candidate(candidate=candidate, bundle=bundle(finding()))
    assert p.disposition is ProposalDisposition.REVIEW_REQUIRED


def test_keyword_limit_rejected_before_action():
    with pytest.raises(ValueError, match="80 characters"):
        NegativeKeywordCandidate(
            text="x" * 81,
            match_type=NegativeMatchType.EXACT,
            scope=NegativeScope.AD_GROUP,
            customer_id="1",
            campaign_id="10",
            ad_group_id="20",
        )


def test_more_than_ten_words_rejected():
    with pytest.raises(ValueError, match="10 words"):
        NegativeKeywordCandidate(
            text="one two three four five six seven eight nine ten eleven",
            match_type=NegativeMatchType.EXACT,
            scope=NegativeScope.AD_GROUP,
            customer_id="1",
            campaign_id="10",
            ad_group_id="20",
        )


def test_mutation_plan_requires_human_approval_fingerprint_and_validate_only():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle(finding()))
    approval = ApprovalRecord(
        proposal_id=p.proposal_id,
        proposal_fingerprint=p.fingerprint_sha256,
        approved_by="owner",
        approved_at=datetime.now(timezone.utc),
    )
    plan = build_mutation_plan(p, approval)
    assert plan.validate_only_first is True
    assert plan.partial_failure is False
    assert plan.negative is True
    assert plan.match_type is NegativeMatchType.EXACT


def test_changed_proposal_cannot_reuse_old_approval():
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle(finding()))
    approval = ApprovalRecord(
        proposal_id=p.proposal_id,
        proposal_fingerprint="0" * 64,
        approved_by="owner",
        approved_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="changed after approval"):
        build_mutation_plan(p, approval)


def test_review_proposal_cannot_create_mutation_plan():
    kw = PositiveKeyword("roof replacement jobs", "EXACT", "1", "10", "20")
    p = SafeNegativeKeywordEngine().propose_exact_from_evidence(
        bundle=bundle(finding()), positive_keywords=(kw,)
    )
    approval = ApprovalRecord(
        proposal_id=p.proposal_id,
        proposal_fingerprint=p.fingerprint_sha256,
        approved_by="owner",
        approved_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="READY_FOR_APPROVAL"):
        build_mutation_plan(p, approval)
