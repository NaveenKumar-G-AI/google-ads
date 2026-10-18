from datetime import datetime,timezone
from recovery.recovery_cases import derive_case_projection,RecoveryCaseState
NOW=datetime(2026,10,16,tzinfo=timezone.utc)

def base(**kw):
    data=dict(proposal={'truth_fingerprint':'a'*64,'disposition':'ready_for_approval'},proposal_analysis_run_id='run-1',latest_completed_analysis_run_id='run-1',latest_truth_fingerprint='a'*64,decision=None,mutation_events=[],ledger_entries=[],case_events=[],queued_execution=False)
    data.update(kw);return derive_case_projection(**data)

def test_ready_case_is_reviewable_but_not_executable_without_approval():
    p=base();assert p.state is RecoveryCaseState.READY_FOR_REVIEW;assert p.execution_allowed is False

def test_approved_fresh_case_is_executable():
    p=base(decision={'decision':'approved'});assert p.state is RecoveryCaseState.APPROVED;assert p.execution_allowed is True

def test_truth_change_marks_case_stale_and_blocks_execution():
    p=base(decision={'decision':'approved'},latest_truth_fingerprint='b'*64);assert p.stale is True;assert 'business_truth_changed' in p.stale_reasons;assert p.execution_allowed is False

def test_newer_analysis_marks_case_stale():
    p=base(decision={'decision':'approved'},latest_completed_analysis_run_id='run-2');assert p.stale is True;assert 'newer_analysis_available' in p.stale_reasons

def test_applied_case_with_verified_ledger_becomes_verified():
    p=base(decision={'decision':'approved'},mutation_events=[{'id':'m','event_type':'applied','occurred_at':NOW}],ledger_entries=[{'id':'l','causal_status':'verified','created_at':NOW}]);assert p.state is RecoveryCaseState.VERIFIED;assert p.rollback_allowed is True

def test_closed_event_overrides_operational_state_until_reopened():
    p=base(decision={'decision':'approved'},case_events=[{'id':'c','event_type':'closed','occurred_at':NOW,'payload':{}}]);assert p.state is RecoveryCaseState.CLOSED;assert p.execution_allowed is False

def test_assignment_is_projected_from_append_only_events():
    p=base(case_events=[{'id':'a','event_type':'assigned','occurred_at':NOW,'payload':{'assigned_to':'u1'}}]);assert p.assigned_to=='u1'

def test_needs_reconciliation_is_first_class_case_state():
    p=base(decision={'decision':'approved'},execution_job_status='needs_reconciliation',external_effect_state='ambiguous')
    assert p.state is RecoveryCaseState.NEEDS_RECONCILIATION
    assert p.execution_allowed is False

def test_closed_applied_case_still_allows_exact_rollback_escape_hatch():
    p=base(decision={'decision':'approved'},mutation_events=[{'id':'m','event_type':'applied','occurred_at':NOW}],case_events=[{'id':'c','event_type':'closed','occurred_at':NOW,'payload':{}}])
    assert p.state is RecoveryCaseState.CLOSED
    assert p.rollback_allowed is True
