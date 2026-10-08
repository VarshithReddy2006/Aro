"""State machine transition policy for Aro cases.

Re-exports the canonical transition definitions and validation rules from packages.contracts.
"""

from packages.contracts.state_machine import (
    ALLOWED_TRANSITIONS,
    DirectExecutionWithoutApprovalError,
    InvalidStateTransitionError,
    StateMachineError,
    StateVersionMismatchError,
    TerminalStateError,
    can_transition,
    transition_case,
    validate_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "DirectExecutionWithoutApprovalError",
    "InvalidStateTransitionError",
    "StateMachineError",
    "StateVersionMismatchError",
    "TerminalStateError",
    "can_transition",
    "transition_case",
    "validate_transition",
]
