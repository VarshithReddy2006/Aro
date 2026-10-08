"""Deterministic lifecycle state machine for Aro operational cases.

Core Security Invariant:
- APPROVAL_PENDING -> EXECUTING is strictly prohibited.
- Execution requires an explicit APPROVED state.
- CLOSED is an immutable terminal state.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from .enums import CaseStatus
from .models import Case


class StateMachineError(Exception):
    """Base exception for state machine violations."""


class InvalidStateTransitionError(StateMachineError):
    """Raised when an illegal or unauthorized lifecycle transition is attempted."""

    def __init__(self, current: CaseStatus, target: CaseStatus, reason: str | None = None) -> None:
        self.current = current
        self.target = target
        self.reason = reason or f"Transition from {current} to {target} is not permitted"
        super().__init__(self.reason)


class StateVersionMismatchError(StateMachineError):
    """Raised when optimistic concurrency guard detects a stale case version."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Case version conflict: expected version {expected}, but found version {actual}"
        )


class TerminalStateError(InvalidStateTransitionError):
    """Raised when attempting to transition out of a terminal state."""

    def __init__(self, current: CaseStatus, target: CaseStatus) -> None:
        super().__init__(
            current,
            target,
            f"Terminal state violation: Cannot transition out of terminal state {current} to {target}",
        )


class DirectExecutionWithoutApprovalError(InvalidStateTransitionError):
    """Security violation: attempted execution without human approval."""

    def __init__(self) -> None:
        super().__init__(
            CaseStatus.APPROVAL_PENDING,
            CaseStatus.EXECUTING,
            "Security violation: Direct transition from APPROVAL_PENDING to EXECUTING is strictly prohibited. "
            "Consequential action execution requires prior human approval (APPROVED state).",
        )


class ProposalHashMismatchError(StateMachineError):
    """Security violation: Human approval hash does not match the exact proposal hash."""

    def __init__(self, expected_hash: str, provided_hash: str) -> None:
        self.expected_hash = expected_hash
        self.provided_hash = provided_hash
        super().__init__(
            f"Proposal hash mismatch: expected '{expected_hash}', but received '{provided_hash}'."
        )


class ApprovalExpiredError(StateMachineError):
    """Security violation: Attempted approval or execution with an expired approval."""

    def __init__(self, expires_at: str, current_time: str) -> None:
        self.expires_at = expires_at
        self.current_time = current_time
        super().__init__(
            f"Approval expired: valid until {expires_at}, current time is {current_time}."
        )


class UnauthorizedApproverError(StateMachineError):
    """Authorization violation: User role is not permitted to approve operational cases."""

    def __init__(self, user_id: str, role: str) -> None:
        self.user_id = user_id
        self.role = role
        super().__init__(
            f"Unauthorized approver '{user_id}' with role '{role}'. Only ADMIN or OPERATOR may approve."
        )


class ActionNotAllowlistedError(StateMachineError):
    """Security violation: Attempted execution of an action not on the strict allowlist."""

    def __init__(self, action_type: str) -> None:
        self.action_type = action_type
        super().__init__(f"Action '{action_type}' is not in the allowlist of permissible actions.")


# Comprehensive deterministic transition table

ALLOWED_TRANSITIONS: Mapping[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {
        CaseStatus.VALIDATED,
        CaseStatus.FAILED,
    },
    CaseStatus.VALIDATED: {
        CaseStatus.CASE_CREATED,
        CaseStatus.FAILED,
    },
    CaseStatus.CASE_CREATED: {
        CaseStatus.CONTEXT_READY,
        CaseStatus.FAILED,
    },
    CaseStatus.CONTEXT_READY: {
        CaseStatus.PROPOSAL_READY,
        CaseStatus.UNRESOLVED,
        CaseStatus.FAILED,
    },
    CaseStatus.PROPOSAL_READY: {
        CaseStatus.APPROVAL_PENDING,
        CaseStatus.UNRESOLVED,
        CaseStatus.FAILED,
    },
    CaseStatus.APPROVAL_PENDING: {
        CaseStatus.APPROVED,
        CaseStatus.UNRESOLVED,
        CaseStatus.FAILED,
    },
    CaseStatus.APPROVED: {
        CaseStatus.EXECUTING,
        CaseStatus.UNRESOLVED,
        CaseStatus.FAILED,
    },
    CaseStatus.EXECUTING: {
        CaseStatus.COMPLETED,
        CaseStatus.RETRYING,
        CaseStatus.FAILED,
    },
    CaseStatus.RETRYING: {
        CaseStatus.EXECUTING,
        CaseStatus.UNRESOLVED,
        CaseStatus.FAILED,
    },
    CaseStatus.COMPLETED: {
        CaseStatus.CLOSED,
    },
    CaseStatus.FAILED: {
        CaseStatus.RETRYING,
        CaseStatus.UNRESOLVED,
        CaseStatus.CLOSED,
    },
    CaseStatus.UNRESOLVED: {
        CaseStatus.CLOSED,
        CaseStatus.CONTEXT_READY,
    },
    CaseStatus.CLOSED: set(),  # Terminal state: no outbound transitions
}


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    """Return True if the state transition is valid, False otherwise."""
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current: CaseStatus, target: CaseStatus) -> None:
    """Validate a requested state transition, raising explicit errors on violation.

    Guarantees:
    - Rejects APPROVAL_PENDING -> EXECUTING with DirectExecutionWithoutApprovalError.
    - Rejects transitions out of CLOSED with TerminalStateError.
    - Rejects all other disallowed transitions with InvalidStateTransitionError.
    """
    if current == CaseStatus.APPROVAL_PENDING and target == CaseStatus.EXECUTING:
        raise DirectExecutionWithoutApprovalError()

    if current == CaseStatus.CLOSED:
        raise TerminalStateError(current, target)

    if not can_transition(current, target):
        raise InvalidStateTransitionError(current, target)


def transition_case(
    case: Case,
    target_status: CaseStatus,
    *,
    expected_version: int | None = None,
    closure_reason: str | None = None,
) -> Case:
    """Apply a validated state transition to a Case model, returning the updated instance.

    Enforces:
    - Transition validity rules.
    - Optimistic locking version guard if expected_version is provided.
    - Version increment.
    - Updated timestamp maintenance.
    - Terminal closure timestamp recording if target is CLOSED.
    """
    if expected_version is not None and case.version != expected_version:
        raise StateVersionMismatchError(expected=expected_version, actual=case.version)

    validate_transition(case.status, target_status)

    now_iso = datetime.now(UTC).isoformat()
    new_version = case.version + 1

    updates = {
        "status": target_status,
        "version": new_version,
        "updated_at": now_iso,
    }

    if target_status == CaseStatus.CLOSED:
        updates["closed_at"] = now_iso

    if closure_reason is not None:
        updates["closure_reason"] = closure_reason

    return case.model_copy(update=updates)
