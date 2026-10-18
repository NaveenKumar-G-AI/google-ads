from recovery.recovery_ledger import CausalVerificationStatus, RecoveryLedgerSummary
import pytest


def test_nonzero_verified_recovery_cannot_exist_without_verified_causal_status():
    with pytest.raises(ValueError, match="VERIFIED"):
        RecoveryLedgerSummary(
            currency_code="USD",
            historical_candidate_micros=100,
            projected_prevented_micros=80,
            observed_post_action_query_spend_micros=0,
            verified_recovery_micros=50,
            action_configuration_verified=True,
            causal_status=CausalVerificationStatus.INCONCLUSIVE,
        )


def test_nonzero_verified_recovery_requires_verified_live_configuration():
    with pytest.raises(ValueError, match="configuration"):
        RecoveryLedgerSummary(
            currency_code="USD",
            historical_candidate_micros=100,
            projected_prevented_micros=80,
            observed_post_action_query_spend_micros=0,
            verified_recovery_micros=50,
            action_configuration_verified=False,
            causal_status=CausalVerificationStatus.VERIFIED,
        )
