from recovery.db.canonical import canonical_payload
from recovery.negative_keywords import (
    Collision, NegativeKeywordCandidate, NegativeKeywordProposal, NegativeMatchType,
    NegativeScope, ProposalDisposition, ProposalReason, ProposalReasonCode, ProposalRisk,
)
from recovery.worker.google_jobs import parse_negative_keyword_proposal


def proposal():
    return NegativeKeywordProposal(
        proposal_id="p1",
        candidate=NegativeKeywordCandidate(
            text="roof jobs", match_type=NegativeMatchType.EXACT, scope=NegativeScope.AD_GROUP,
            customer_id="1234567890", campaign_id="10", ad_group_id="20",
        ),
        truth_fingerprint="a"*64, evidence_snapshot_id="snap",
        evidence_observation_ids=("o1",), disposition=ProposalDisposition.READY_FOR_APPROVAL,
        risk=ProposalRisk.LOW,
        reasons=(ProposalReason(ProposalReasonCode.SAFE_EXACT_CANDIDATE,"safe",False),),
        protected_query_collisions=(), positive_keyword_collisions=(),
        existing_covering_negative_resource_names=(), potentially_avoidable_cost_micros=1000,
        currency_code="USD",
    )


def test_stored_proposal_roundtrips_without_fingerprint_drift():
    p=proposal(); parsed=parse_negative_keyword_proposal(canonical_payload(p))
    assert parsed==p
    assert parsed.fingerprint_sha256==p.fingerprint_sha256
