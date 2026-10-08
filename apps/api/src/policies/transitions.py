from ..models.domain import CaseStatus
ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {CaseStatus.VALIDATED, CaseStatus.FAILED},
    CaseStatus.VALIDATED: {CaseStatus.CASE_CREATED, CaseStatus.FAILED},
    CaseStatus.CASE_CREATED: {CaseStatus.CONTEXT_READY, CaseStatus.FAILED},
    CaseStatus.CONTEXT_READY: {CaseStatus.PROPOSAL_READY, CaseStatus.UNRESOLVED},
    CaseStatus.PROPOSAL_READY: {CaseStatus.APPROVAL_PENDING, CaseStatus.FAILED},
    CaseStatus.APPROVAL_PENDING: {CaseStatus.APPROVED, CaseStatus.UNRESOLVED},
    CaseStatus.APPROVED: {CaseStatus.EXECUTING, CaseStatus.UNRESOLVED},
    CaseStatus.EXECUTING: {CaseStatus.COMPLETED, CaseStatus.RETRYING, CaseStatus.FAILED},
    CaseStatus.RETRYING: {CaseStatus.EXECUTING, CaseStatus.FAILED, CaseStatus.UNRESOLVED},
    CaseStatus.COMPLETED: {CaseStatus.CLOSED},
    CaseStatus.CLOSED: set(),
    CaseStatus.FAILED: {CaseStatus.RETRYING, CaseStatus.UNRESOLVED},
    CaseStatus.UNRESOLVED: {CaseStatus.CLOSED},
}
def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
