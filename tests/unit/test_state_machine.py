from apps.api.src.models.domain import CaseStatus
from apps.api.src.policies.transitions import can_transition

def test_approval_cannot_jump_to_executing():
    assert not can_transition(CaseStatus.APPROVAL_PENDING, CaseStatus.EXECUTING)

def test_approved_can_execute():
    assert can_transition(CaseStatus.APPROVED, CaseStatus.EXECUTING)

def test_completed_can_close():
    assert can_transition(CaseStatus.COMPLETED, CaseStatus.CLOSED)
