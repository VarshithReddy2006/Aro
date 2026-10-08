"""Unit tests for deterministic proposal hashing."""

from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import ActionType


def test_t_proposal_hash_deterministic():
    # Same inputs must produce exact same SHA-256 hash
    h1 = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at entrance.",
        parameters={"message": "Review entrance", "urgency": "normal"},
    )
    h2 = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at entrance.",
        parameters={"urgency": "normal", "message": "Review entrance"},  # Different key order
    )
    assert h1 == h2
    assert len(h1) == 64


def test_t_proposal_mutation_produces_different_hash():
    base_hash = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at entrance.",
        parameters={"message": "Review entrance", "urgency": "normal"},
    )

    # Mutate parameters
    h_mutated_params = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at entrance.",
        parameters={"message": "Review entrance", "urgency": "urgent"},
    )
    assert base_hash != h_mutated_params

    # Mutate reason
    h_mutated_reason = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="Tampered reason text.",
        parameters={"message": "Review entrance", "urgency": "normal"},
    )
    assert base_hash != h_mutated_reason

    # Mutate action_type
    h_mutated_action = calculate_proposal_hash(
        case_id="case_01",
        action_type=ActionType.MARK_FOR_REVIEW,
        reason="After-hours activity observed at entrance.",
        parameters={"message": "Review entrance", "urgency": "normal"},
    )
    assert base_hash != h_mutated_action

    # Mutate case_id
    h_mutated_case = calculate_proposal_hash(
        case_id="case_99",
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed at entrance.",
        parameters={"message": "Review entrance", "urgency": "normal"},
    )
    assert base_hash != h_mutated_case
