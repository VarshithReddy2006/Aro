"""Unit tests for ApprovalService: RBAC, optimistic locking, and proposal hash binding."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.api.src.repositories.errors import (
    OrganizationAccessDeniedError,
)
from apps.api.src.repositories.in_memory import (
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryProposalRepository,
)
from apps.api.src.services.approval_service import ApprovalService
from apps.api.src.utils.proposal_hash import calculate_proposal_hash
from packages.contracts.enums import (
    ActionType,
    ApprovalDecision,
    AuditEventType,
    CaseStatus,
    Role,
)
from packages.contracts.models import (
    Case,
    Proposal,
    User,
)
from packages.contracts.state_machine import (
    ApprovalExpiredError,
    ProposalHashMismatchError,
    StateVersionMismatchError,
    UnauthorizedApproverError,
)


@pytest.fixture
def repos():
    case_repo = InMemoryCaseRepository()
    approval_repo = InMemoryApprovalRepository()
    audit_repo = InMemoryAuditRepository()
    proposal_repo = InMemoryProposalRepository()
    return case_repo, approval_repo, audit_repo, proposal_repo


@pytest.fixture
def service(repos):
    case_repo, approval_repo, audit_repo, proposal_repo = repos
    return ApprovalService(
        case_repo=case_repo,
        approval_repo=approval_repo,
        audit_repo=audit_repo,
        proposal_repo=proposal_repo,
    )


@pytest.fixture
def operator_user():
    return User(
        user_id="usr_op_1",
        organization_id="org_test",
        email="operator@test.com",
        name="Test Operator",
        role=Role.OPERATOR,
    )


@pytest.fixture
def sample_case_and_proposal(repos):
    case_repo, _, _, proposal_repo = repos
    case_id = "case_appr_01"
    org_id = "org_test"

    h = calculate_proposal_hash(
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed",
        parameters={"message": "Alert operator", "urgency": "normal"},
    )
    prop = Proposal(
        proposal_id="prop_01",
        case_id=case_id,
        action_type=ActionType.NOTIFY_OPERATOR,
        reason="After-hours activity observed",
        parameters={"message": "Alert operator", "urgency": "normal"},
        proposal_hash=h,
    )
    proposal_repo.save_proposal(prop, org_id)

    case = Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_1",
        device_id="dev_1",
        event_id="evt_1",
        title="Sample Case",
        status=CaseStatus.APPROVAL_PENDING,
        version=1,
        active_proposal_id=prop.proposal_id,
    )
    case_repo.create_case(case)
    return case, prop


def test_approve_case_happy_path(service, repos, operator_user, sample_case_and_proposal):
    case_repo, _approval_repo, audit_repo, _ = repos
    case, prop = sample_case_and_proposal

    approval = service.approve_case(
        case_id=case.case_id,
        proposal_id=prop.proposal_id,
        proposal_hash=prop.proposal_hash,
        user=operator_user,
        expected_case_version=1,
    )

    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.proposal_hash == prop.proposal_hash
    assert approval.approved_by == operator_user.user_id
    assert approval.case_version == 1

    # Verify case status and version transition
    updated_case = case_repo.get_case(case.case_id, "org_test")
    assert updated_case.status == CaseStatus.APPROVED
    assert updated_case.version == 2
    assert updated_case.active_approval_id == approval.approval_id

    # Verify audit event recorded
    timeline = audit_repo.get_case_timeline(case.case_id, "org_test")
    assert len(timeline) == 1
    assert timeline[0].action == AuditEventType.APPROVAL_RECORDED
    assert timeline[0].actor_id == operator_user.user_id


def test_approve_case_proposal_hash_mismatch(service, operator_user, sample_case_and_proposal):
    case, prop = sample_case_and_proposal

    with pytest.raises(ProposalHashMismatchError):
        service.approve_case(
            case_id=case.case_id,
            proposal_id=prop.proposal_id,
            proposal_hash="tampered_hash_value_12345678",
            user=operator_user,
            expected_case_version=1,
        )


def test_approve_case_stale_version_mismatch(
    service, repos, operator_user, sample_case_and_proposal
):
    case_repo, _, _, _ = repos
    case, prop = sample_case_and_proposal

    # Advance case version
    updated = case.model_copy(update={"version": 2})
    case_repo.update_case(updated, "org_test", expected_version=1)

    with pytest.raises(StateVersionMismatchError) as exc_info:
        service.approve_case(
            case_id=case.case_id,
            proposal_id=prop.proposal_id,
            proposal_hash=prop.proposal_hash,
            user=operator_user,
            expected_case_version=1,
        )
    assert exc_info.value.expected == 1
    assert exc_info.value.actual == 2


def test_approve_case_unauthorized_role(service, sample_case_and_proposal):
    case, prop = sample_case_and_proposal
    viewer = User(
        user_id="usr_viewer",
        organization_id="org_test",
        email="viewer@test.com",
        name="Viewer",
        role=Role.VIEWER,
    )

    with pytest.raises(UnauthorizedApproverError):
        service.approve_case(
            case_id=case.case_id,
            proposal_id=prop.proposal_id,
            proposal_hash=prop.proposal_hash,
            user=viewer,
            expected_case_version=1,
        )


def test_approve_case_tenant_isolation(service, sample_case_and_proposal):
    case, prop = sample_case_and_proposal
    alien_user = User(
        user_id="usr_alien",
        organization_id="org_other",
        email="alien@test.com",
        name="Alien",
        role=Role.ADMIN,
    )

    with pytest.raises(OrganizationAccessDeniedError):
        service.approve_case(
            case_id=case.case_id,
            proposal_id=prop.proposal_id,
            proposal_hash=prop.proposal_hash,
            user=alien_user,
            expected_case_version=1,
            organization_id="org_test",
        )


def test_approve_case_expired_rejection(service, operator_user, sample_case_and_proposal):
    case, prop = sample_case_and_proposal
    past_ts = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()

    with pytest.raises(ApprovalExpiredError):
        service.approve_case(
            case_id=case.case_id,
            proposal_id=prop.proposal_id,
            proposal_hash=prop.proposal_hash,
            user=operator_user,
            expected_case_version=1,
            expires_at=past_ts,
        )


def test_reject_case_happy_path(service, repos, operator_user, sample_case_and_proposal):
    case_repo, _approval_repo, audit_repo, _ = repos
    case, prop = sample_case_and_proposal

    rejection = service.reject_case(
        case_id=case.case_id,
        proposal_id=prop.proposal_id,
        proposal_hash=prop.proposal_hash,
        user=operator_user,
        reason="Expected maintenance worker on site",
        expected_case_version=1,
    )

    assert rejection.decision == ApprovalDecision.REJECTED
    assert rejection.approved_by == operator_user.user_id

    # Case transitions to UNRESOLVED
    updated_case = case_repo.get_case(case.case_id, "org_test")
    assert updated_case.status == CaseStatus.UNRESOLVED
    assert updated_case.version == 2
    assert "Expected maintenance worker" in (updated_case.closure_reason or "")

    # Audit event logged
    timeline = audit_repo.get_case_timeline(case.case_id, "org_test")
    assert len(timeline) == 1
    assert timeline[0].action == AuditEventType.APPROVAL_REJECTED


def test_expire_case_approval(service, repos, sample_case_and_proposal):
    _case_repo, _, audit_repo, _ = repos
    case, _ = sample_case_and_proposal

    expired_case = service.expire_case_approval(
        case_id=case.case_id,
        expected_case_version=1,
        organization_id="org_test",
    )

    assert expired_case.status == CaseStatus.UNRESOLVED
    assert expired_case.version == 2

    timeline = audit_repo.get_case_timeline(case.case_id, "org_test")
    assert len(timeline) == 1
    assert timeline[0].action == AuditEventType.APPROVAL_EXPIRED
