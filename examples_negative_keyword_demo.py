from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from datetime import date, datetime, timezone
from decimal import Decimal

from recovery.evidence import (
    EvidenceDisposition,
    SearchTermEvidence,
    SearchTermEvidenceKey,
)
from recovery.domain import CoverageBand
from recovery.negative_keywords import (
    ApprovalRecord,
    SafeNegativeKeywordEngine,
    ScopeEvidenceBundle,
    build_mutation_plan,
)

finding = SearchTermEvidence(
    key=SearchTermEvidenceKey("1", "10", "20", "roof replacement jobs", "SEARCH"),
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

bundle = ScopeEvidenceBundle((finding,), True, "snapshot-2026-10-15")
proposal = SafeNegativeKeywordEngine().propose_exact_from_evidence(bundle=bundle)
print("Proposal:", proposal.candidate.match_type.value, proposal.candidate.text)
print("Scope:", proposal.candidate.scope.value, proposal.candidate.ad_group_id)
print("Disposition:", proposal.disposition.value)
print("Human approval required:", proposal.requires_human_approval)

approval = ApprovalRecord(
    proposal_id=proposal.proposal_id,
    proposal_fingerprint=proposal.fingerprint_sha256,
    approved_by="operator@example",
    approved_at=datetime.now(timezone.utc),
)
plan = build_mutation_plan(proposal, approval)
print("Validate only first:", plan.validate_only_first)
print("Service:", plan.service)
