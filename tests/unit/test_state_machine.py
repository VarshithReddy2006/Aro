"""Comprehensive unit tests for the Aro case state machine.

Covers:
- Full happy path sequence
- Critical security invariant: APPROVAL_PENDING -> EXECUTING rejection
- Approval rejection and expiry paths
- Execution failure, retries, and unresolved triage
- Terminal behavior of CLOSED state
- Exhaustive validation of all permitted and prohibited transitions
- Optimistic locking and version increments
"""

import pytest

from packages.contracts.enums import CaseStatus
from packages.contracts.models import Case
from packages.contracts.state_machine import (
    ALLOWED_TRANSITIONS,
    DirectExecutionWithoutApprovalError,
    InvalidStateTransitionError,
    StateVersionMismatchError,
    TerminalStateError,
    can_transition,
    transition_case,
    validate_transition,
)


def _make_sample_case(status: CaseStatus = CaseStatus.RECEIVED, version: int = 1) -> Case:
    """Helper to instantiate a test Case model."""
    return Case(
        case_id="case_test_001",
        organization_id="org_test_001",
        location_id="loc_test_001",
        device_id="dev_front_door",
        event_id="evt_test_001",
        title="Possible after-hours delivery activity at front door",
        status=status,
        version=version,
    )


# 1. Critical Security Invariant Tests
def test_approval_pending_cannot_jump_to_executing():
    """Security Invariant: APPROVAL_PENDING -> EXECUTING must be strictly rejected."""
    assert not can_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.EXECUTING)
    with pytest.raises(DirectExecutionWithoutApprovalError) as exc_info:
        validate_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.EXECUTING)
    assert "strictly prohibited" in str(exc_info.value)
    assert "APPROVED state" in str(exc_info.value)


def test_transition_case_rejects_unapproved_execution():
    """Direct execution attempt on a Case instance raises security exception."""
    case = _make_sample_case(status=CaseStatus.APPROVAL_PENDING)
    with pytest.raises(DirectExecutionWithoutApprovalError):
        transition_case(case, CaseStatus.EXECUTING)


# 2. Happy Path Progression
def test_complete_happy_path_sequence():
    """Verify the full operational lifecycle from ingestion to evidence-backed closure."""
    happy_path = [
        CaseStatus.RECEIVED,
        CaseStatus.VALIDATED,
        CaseStatus.CASE_CREATED,
        CaseStatus.CONTEXT_READY,
        CaseStatus.PROPOSAL_READY,
        CaseStatus.APPROVAL_PENDING,
        CaseStatus.APPROVED,
        CaseStatus.EXECUTING,
        CaseStatus.COMPLETED,
        CaseStatus.CLOSED,
    ]

    current_case = _make_sample_case(status=happy_path[0], version=1)

    for i in range(len(happy_path) - 1):
        from_state = happy_path[i]
        to_state = happy_path[i + 1]

        assert can_transition(from_state, to_state)
        validate_transition(from_state, to_state)

        next_case = transition_case(current_case, to_state, expected_version=current_case.version)
        assert next_case.status == to_state
        assert next_case.version == current_case.version + 1
        current_case = next_case

    assert current_case.status == CaseStatus.CLOSED
    assert current_case.version == len(happy_path)
    assert current_case.closed_at is not None


# 3. Approval Rejection & Expiry Paths
def test_operator_rejection_transitions_to_unresolved():
    """Operator rejection of a proposal moves the case to UNRESOLVED."""
    case = _make_sample_case(status=CaseStatus.APPROVAL_PENDING)
    updated = transition_case(case, CaseStatus.UNRESOLVED)
    assert updated.status == CaseStatus.UNRESOLVED

    # Unresolved can be closed
    closed = transition_case(
        updated, CaseStatus.CLOSED, closure_reason="Operator rejected proposed action"
    )
    assert closed.status == CaseStatus.CLOSED
    assert closed.closure_reason == "Operator rejected proposed action"


def test_approval_expiry_transitions_to_unresolved():
    """Expired approval window moves case to UNRESOLVED."""
    assert can_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.UNRESOLVED)
    validate_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.UNRESOLVED)


# 4. Action Execution Failure & Retries
def test_transient_action_failure_with_retry_and_success():
    """Transient action execution failure enters RETRYING, re-executes, and succeeds."""
    case = _make_sample_case(status=CaseStatus.APPROVED)

    executing = transition_case(case, CaseStatus.EXECUTING)
    assert executing.status == CaseStatus.EXECUTING

    retrying = transition_case(executing, CaseStatus.RETRYING)
    assert retrying.status == CaseStatus.RETRYING

    re_executing = transition_case(retrying, CaseStatus.EXECUTING)
    assert re_executing.status == CaseStatus.EXECUTING

    completed = transition_case(re_executing, CaseStatus.COMPLETED)
    assert completed.status == CaseStatus.COMPLETED

    closed = transition_case(completed, CaseStatus.CLOSED)
    assert closed.status == CaseStatus.CLOSED


def test_retry_exhaustion_moves_to_unresolved_or_failed():
    """Repeated failures can lead to UNRESOLVED triage or FAILED."""
    case = _make_sample_case(status=CaseStatus.RETRYING)

    unresolved = transition_case(case, CaseStatus.UNRESOLVED)
    assert unresolved.status == CaseStatus.UNRESOLVED

    # Also test from FAILED
    failed_case = _make_sample_case(status=CaseStatus.FAILED)
    retrying_from_failed = transition_case(failed_case, CaseStatus.RETRYING)
    assert retrying_from_failed.status == CaseStatus.RETRYING
    assert can_transition(CaseStatus.FAILED, CaseStatus.UNRESOLVED)
    assert can_transition(CaseStatus.FAILED, CaseStatus.CLOSED)


# 5. Closed Terminal Behavior
def test_closed_state_is_strictly_terminal():
    """No transition may originate from the CLOSED state."""
    closed_case = _make_sample_case(status=CaseStatus.CLOSED)

    for target in CaseStatus:
        assert not can_transition(CaseStatus.CLOSED, target)
        with pytest.raises(TerminalStateError) as exc_info:
            validate_transition(CaseStatus.CLOSED, target)
        assert "terminal state" in str(exc_info.value).lower()

        with pytest.raises(TerminalStateError):
            transition_case(closed_case, target)


# 6. Exhaustive Transition Matrix Testing
def test_every_permitted_transition_succeeds():
    """Verify that every transition explicitly listed in ALLOWED_TRANSITIONS passes validation."""
    for current, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert can_transition(current, target), f"Expected {current} -> {target} to be valid"
            # Should not raise
            validate_transition(current, target)


def test_every_prohibited_transition_is_rejected():
    """Exhaustively verify every non-permitted state transition raises InvalidStateTransitionError."""
    all_statuses = list(CaseStatus)
    for current in all_statuses:
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        for target in all_statuses:
            if target not in allowed:
                assert not can_transition(current, target), (
                    f"Expected {current} -> {target} to be prohibited"
                )
                with pytest.raises(InvalidStateTransitionError):
                    validate_transition(current, target)


# 7. Optimistic Locking & Version Guards
def test_state_version_guard_detects_conflict():
    """If expected_version differs from case.version, StateVersionMismatchError is raised."""
    case = _make_sample_case(status=CaseStatus.RECEIVED, version=3)

    # Correct version succeeds
    updated = transition_case(case, CaseStatus.VALIDATED, expected_version=3)
    assert updated.version == 4

    # Stale version raises error
    with pytest.raises(StateVersionMismatchError) as exc_info:
        transition_case(updated, CaseStatus.CASE_CREATED, expected_version=3)
    assert "version conflict" in str(exc_info.value).lower()
    assert exc_info.value.expected == 3
    assert exc_info.value.actual == 4


# 8. Reopening Unresolved Cases
def test_unresolved_case_reopening():
    """An UNRESOLVED case may be reopened back to CONTEXT_READY if new context emerges."""
    case = _make_sample_case(status=CaseStatus.UNRESOLVED)
    reopened = transition_case(case, CaseStatus.CONTEXT_READY)
    assert reopened.status == CaseStatus.CONTEXT_READY
