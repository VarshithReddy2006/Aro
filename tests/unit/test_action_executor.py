"""Unit tests for ActionExecutor: allowlist enforcement, idempotency, and atomic locking."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.api.src.repositories.in_memory import (
    InMemoryActionRepository,
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryIdempotencyRepository,
    InMemoryProposalRepository,
)
from apps.api.src.services.action_executor import ActionExecutor
from apps.api.src.utils.audit_hasher import verify_audit_chain
from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    ApprovalDecision,
    CaseStatus,
    Role,
)
from packages.contracts.models import (
    Approval,
    Case,
    Proposal,
    User,
)
from packages.contracts.state_machine import (
    ApprovalExpiredError,
    DirectExecutionWithoutApprovalError,
    InvalidStateTransitionError,
    StateVersionMismatchError,
    UnauthorizedApproverError,
)


@pytest.fixture
def test_setup():
    case_repo = InMemoryCaseRepository()
    approval_repo = InMemoryApprovalRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)
    audit_repo = InMemoryAuditRepository()
    proposal_repo = InMemoryProposalRepository()
    idempotency_repo = InMemoryIdempotencyRepository()

    executor = ActionExecutor(
        case_repo=case_repo,
        approval_repo=approval_repo,
        action_repo=action_repo,
        audit_repo=audit_repo,
        proposal_repo=proposal_repo,
        idempotency_repo=idempotency_repo,
    )

    user = User(
        user_id="usr_op_1",
        organization_id="org_test",
        email="operator@test.com",
        name="Test Operator",
        role=Role.OPERATOR,
    )

    return {
        "case_repo": case_repo,
        "approval_repo": approval_repo,
        "action_repo": action_repo,
        "audit_repo": audit_repo,
        "proposal_repo": proposal_repo,
        "idempotency_repo": idempotency_repo,
        "executor": executor,
        "user": user,
    }


def _create_approved_case(
    setup,
    action_type: ActionType = ActionType.NOTIFY_OPERATOR,
    parameters: dict | None = None,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    expires_in_seconds: int = 1800,
):
    case_repo = setup["case_repo"]
    approval_repo = setup["approval_repo"]
    proposal_repo = setup["proposal_repo"]

    case_id = f"case_{datetime.now(UTC).timestamp()}"
    org_id = "org_test"
    params = parameters or {"message": "Test notification", "urgency": "normal"}

    h = calculate_proposal_hash(
        case_id=case_id,
        action_type=action_type,
        reason="Test action reason",
        parameters=params,
    )
    prop = Proposal(
        proposal_id=f"prop_{case_id}",
        case_id=case_id,
        action_type=action_type,
        reason="Test action reason",
        parameters=params,
        proposal_hash=h,
    )
    proposal_repo.save_proposal(prop, org_id)

    appr_id = f"appr_{case_id}"
    exp_iso = (datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).isoformat()
    approval = Approval(
        approval_id=appr_id,
        organization_id=org_id,
        case_id=case_id,
        proposal_id=prop.proposal_id,
        proposal_hash=h,
        approved_by=setup["user"].user_id,
        approved_at=datetime.now(UTC).isoformat(),
        expires_at=exp_iso,
        decision=decision,
        case_version=1,
    )
    approval_repo.save_approval(approval, org_id)

    # Initial case status: APPROVED for valid execution, version 2 (since approval incremented it)
    initial_status = (
        CaseStatus.APPROVED if decision == ApprovalDecision.APPROVED else CaseStatus.UNRESOLVED
    )
    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_1",
        device_id="dev_1",
        event_id="evt_1",
        title="Test Case",
        status=initial_status,
        version=2,
        active_proposal_id=prop.proposal_id,
        active_approval_id=appr_id,
    )
    case_repo.create_case(case)
    return case, approval, prop


@pytest.mark.parametrize(
    "action_type,params",
    [
        (ActionType.NOTIFY_OPERATOR, {"message": "Doorbell ring verified", "urgency": "normal"}),
        (ActionType.MARK_FOR_REVIEW, {"review_reason": "Suspicious movement", "priority": "high"}),
        (ActionType.REQUEST_OPERATOR_CONFIRMATION, {"confirmation_type": "delivery_dock_gate"}),
        (ActionType.RECORD_NO_ACTION, {"rationale": "Authorized vendor activity"}),
    ],
)
def test_execute_allowlisted_actions(test_setup, action_type, params):
    case, approval, prop = _create_approved_case(
        test_setup, action_type=action_type, parameters=params
    )
    executor = test_setup["executor"]
    user = test_setup["user"]

    result = executor.execute_action(
        case_id=case.case_id,
        approval_id=approval.approval_id,
        user=user,
        expected_case_version=2,
        proposal=prop,
    )

    assert result.action.status == ActionStatus.SUCCEEDED
    assert result.action.action_type == action_type
    assert result.was_idempotent is False
    assert result.case.status in (CaseStatus.COMPLETED, CaseStatus.CLOSED)

    # Verify audit chain
    timeline = test_setup["audit_repo"].get_case_timeline(case.case_id, "org_test")
    assert len(timeline) >= 2  # ACTION_STARTED, ACTION_COMPLETED (and optional CASE_CLOSED)
    assert verify_audit_chain(timeline)


def test_direct_execution_from_approval_pending_blocked(test_setup):
    case, approval, prop = _create_approved_case(test_setup)
    case_repo = test_setup["case_repo"]

    # Revert case status to APPROVAL_PENDING
    pending_case = case.model_copy(update={"status": CaseStatus.APPROVAL_PENDING})
    case_repo.update_case(pending_case, "org_test", expected_version=case.version)

    executor = test_setup["executor"]
    user = test_setup["user"]

    with pytest.raises(DirectExecutionWithoutApprovalError):
        executor.execute_action(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            user=user,
            expected_case_version=pending_case.version,
            proposal=prop,
        )


def test_execute_rejected_approval_blocked(test_setup):
    case, approval, prop = _create_approved_case(test_setup, decision=ApprovalDecision.REJECTED)
    executor = test_setup["executor"]
    user = test_setup["user"]

    with pytest.raises(InvalidStateTransitionError):
        executor.execute_action(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            user=user,
            expected_case_version=case.version,
            proposal=prop,
        )


def test_execute_expired_approval_blocked(test_setup):
    case, approval, prop = _create_approved_case(
        test_setup,
        expires_in_seconds=-100,  # Already expired
    )
    executor = test_setup["executor"]
    user = test_setup["user"]

    with pytest.raises(ApprovalExpiredError):
        executor.execute_action(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            user=user,
            expected_case_version=case.version,
            proposal=prop,
        )


def test_execute_stale_case_version_blocked(test_setup):
    case, approval, prop = _create_approved_case(test_setup)
    executor = test_setup["executor"]
    user = test_setup["user"]

    with pytest.raises(StateVersionMismatchError):
        executor.execute_action(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            user=user,
            expected_case_version=1,  # Stale, actual is 2
            proposal=prop,
        )


def test_execute_viewer_blocked(test_setup):
    case, approval, prop = _create_approved_case(test_setup)
    executor = test_setup["executor"]
    viewer = User(
        user_id="usr_view_1",
        organization_id="org_test",
        email="viewer@test.com",
        name="Viewer",
        role=Role.VIEWER,
    )

    with pytest.raises(UnauthorizedApproverError):
        executor.execute_action(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            user=viewer,
            expected_case_version=case.version,
            proposal=prop,
        )


def test_idempotent_reexecution_returns_cached_result(test_setup):
    case, approval, prop = _create_approved_case(test_setup)
    executor = test_setup["executor"]
    user = test_setup["user"]
    idemp_key = f"idemp_{case.case_id}"

    # First execution
    first_res = executor.execute_action(
        case_id=case.case_id,
        approval_id=approval.approval_id,
        user=user,
        expected_case_version=case.version,
        idempotency_key=idemp_key,
        proposal=prop,
    )
    assert first_res.was_idempotent is False

    # Second execution: replayed
    second_res = executor.execute_action(
        case_id=case.case_id,
        approval_id=approval.approval_id,
        user=user,
        expected_case_version=case.version,
        idempotency_key=idemp_key,
        proposal=prop,
    )
    assert second_res.was_idempotent is True
    assert second_res.action.action_id == first_res.action.action_id
