"""Comprehensive test suite for Aro repository implementations."""

import pytest

from apps.api.src.repositories import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    ConflictError,
    InMemoryActionRepository,
    InMemoryApprovalRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryEventRepository,
    InMemoryExpectedDeliveryRepository,
    InMemoryIdempotencyRepository,
    InMemoryPolicyRepository,
    NotFoundError,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)
from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseStatus,
    ExpectedDeliveryStatus,
    Provenance,
    Role,
)
from packages.contracts.models import (
    Action,
    Approval,
    AuditEvent,
    Case,
    ExpectedDelivery,
    NormalizedEvent,
    Policy,
    RingEvent,
)


def _sample_case(
    case_id: str = "case_001",
    org_id: str = "org_alpha",
    status: CaseStatus = CaseStatus.RECEIVED,
    version: int = 1,
) -> Case:
    return Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_alpha",
        device_id="dev_front",
        event_id="evt_001",
        title="Possible after-hours delivery activity at front door",
        status=status,
        version=version,
    )


# 1. Case Repository Tests
def test_case_create_and_retrieve():
    repo = InMemoryCaseRepository()
    case = _sample_case()
    created = repo.create_case(case)
    assert created.case_id == "case_001"

    retrieved = repo.get_case("case_001", "org_alpha")
    assert retrieved.case_id == "case_001"
    assert retrieved.version == 1

    # Duplicate creation raises ConflictError
    with pytest.raises(ConflictError):
        repo.create_case(case)


def test_case_get_not_found():
    repo = InMemoryCaseRepository()
    with pytest.raises(NotFoundError):
        repo.get_case("non_existent", "org_alpha")


def test_case_optimistic_locking_and_version_increment():
    repo = InMemoryCaseRepository()
    case = _sample_case()
    repo.create_case(case)

    # Valid update with expected version 1 increments to 2
    updated_case = case.model_copy(update={"status": CaseStatus.VALIDATED})
    result = repo.update_case(updated_case, "org_alpha", expected_version=1)
    assert result.version == 2
    assert result.status == CaseStatus.VALIDATED

    # Stale version update fails
    with pytest.raises(VersionMismatchError) as exc_info:
        repo.update_case(result, "org_alpha", expected_version=1)
    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2


def test_case_listing_and_filtering():
    repo = InMemoryCaseRepository()
    c1 = _sample_case(case_id="c1", status=CaseStatus.RECEIVED)
    c2 = _sample_case(case_id="c2", status=CaseStatus.APPROVED)
    c3 = _sample_case(case_id="c3", org_id="org_beta", status=CaseStatus.APPROVED)
    repo.create_case(c1)
    repo.create_case(c2)
    repo.create_case(c3)

    # List for org_alpha returns only c1, c2
    alpha_cases = repo.list_cases("org_alpha")
    assert len(alpha_cases) == 2
    assert {c.case_id for c in alpha_cases} == {"c1", "c2"}

    # Filter by status
    approved = repo.list_cases("org_alpha", status=CaseStatus.APPROVED)
    assert len(approved) == 1
    assert approved[0].case_id == "c2"


# 2. Event Repository & Deduplication
def test_event_persistence_and_webhook_dedup():
    repo = InMemoryEventRepository()
    evt = RingEvent(
        event_id="evt_100",
        request_id="req_999",
        device_id="dev_front",
        event_type="motion",
        occurred_at="2026-10-08T22:00:00Z",
        provenance=Provenance.RING_SIGNED,
        payload={},
    )
    repo.save_ring_event(evt)
    retrieved = repo.get_ring_event("evt_100")
    assert retrieved is not None
    assert retrieved.request_id == "req_999"

    # Deduplication
    first_seen = repo.record_webhook_dedup("req_999", "evt_100")
    assert first_seen is True

    # Duplicate request returns False
    duplicate_seen = repo.record_webhook_dedup("req_999", "evt_100")
    assert duplicate_seen is False


def test_normalized_event_case_association():
    repo = InMemoryEventRepository()
    norm = NormalizedEvent(
        normalized_event_id="norm_1",
        source_event_id="evt_1",
        device_id="dev_front",
        location_id="loc_1",
        event_type="motion",
        occurred_at="2026-10-08T22:00:00Z",
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,
        is_designated_door=True,
        description="Possible after-hours delivery activity observed",
    )
    repo.save_normalized_event(norm, case_id="case_1")
    events = repo.get_case_events("case_1")
    assert len(events) == 1
    assert events[0].normalized_event_id == "norm_1"


# 3. Approval Repository
def test_approval_lifecycle():
    repo = InMemoryApprovalRepository()
    approval = Approval(
        approval_id="appr_001",
        case_id="case_001",
        case_version=3,
        proposal_id="prop_001",
        proposal_hash="hash_abc",
        approver_user_id="usr_admin",
        approver_role=Role.ADMIN,
        expires_at="2026-10-08T23:00:00Z",
    )
    repo.save_approval(approval, organization_id="org_alpha")

    fetched = repo.get_approval("case_001", "appr_001", "org_alpha")
    assert fetched.approval_id == "appr_001"
    assert fetched.proposal_hash == "hash_abc"

    # Cross org access blocked
    with pytest.raises(OrganizationAccessDeniedError):
        repo.get_approval("case_001", "appr_001", "org_beta")


# 4. Action Execution Lock
def test_action_execution_lock_flow():
    case_repo = InMemoryCaseRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)

    case = _sample_case(status=CaseStatus.APPROVED, version=2)
    case_repo.create_case(case)

    action = Action(
        action_id="act_001",
        case_id="case_001",
        approval_id="appr_001",
        action_type=ActionType.NOTIFY_OPERATOR,
        parameters={},
        status=ActionStatus.PENDING,
        idempotency_key="idemp_act_1",
    )
    action_repo.save_action(action, "org_alpha")

    # Acquire lock transitions case to EXECUTING
    action_repo.acquire_execution_lock("case_001", "act_001", "org_alpha", expected_case_version=2)
    case_after_lock = case_repo.get_case("case_001", "org_alpha")
    assert case_after_lock.status == CaseStatus.EXECUTING
    assert case_after_lock.version == 3

    # Subsequent lock attempt on the same case raises AlreadyExecutingError
    with pytest.raises(AlreadyExecutingError):
        action_repo.acquire_execution_lock(
            "case_001", "act_002", "org_alpha", expected_case_version=3
        )

    # Complete action
    completed = action_repo.complete_action("case_001", "act_001", "org_alpha", "Notification sent")
    assert completed.status == ActionStatus.SUCCEEDED

    # Cannot acquire lock on completed action
    with pytest.raises(AlreadyCompletedError):
        action_repo.acquire_execution_lock(
            "case_001", "act_001", "org_alpha", expected_case_version=3
        )


# 5. Audit Timeline & Hash Chaining
def test_audit_timeline_immutability():
    repo = InMemoryAuditRepository()
    e1 = AuditEvent(
        event_id="aud_1",
        case_id="c_1",
        actor_id="sys",
        actor_type="SYSTEM",
        action=AuditEventType.CASE_CREATED,
        previous_hash="0" * 64,
        current_hash="hash_1",
    )
    e2 = AuditEvent(
        event_id="aud_2",
        case_id="c_1",
        actor_id="usr_admin",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash="hash_1",
        current_hash="hash_2",
    )
    repo.append_audit_event(e1, "org_alpha")
    repo.append_audit_event(e2, "org_alpha")

    timeline = repo.get_case_timeline("c_1", "org_alpha")
    assert len(timeline) == 2
    assert timeline[0].event_id == "aud_1"
    assert timeline[1].event_id == "aud_2"
    assert timeline[1].previous_hash == timeline[0].current_hash

    # Attempt to overwrite existing audit event is strictly forbidden
    with pytest.raises(ConflictError) as exc_info:
        repo.append_audit_event(e1, "org_alpha")
    assert "immutability violation" in str(exc_info.value).lower()


# 6. Idempotency Lock
def test_idempotency_locking():
    repo = InMemoryIdempotencyRepository()
    key = "idem_test_99"

    # First acquisition succeeds
    assert repo.acquire_lock(key, "test_op") is True
    rec = repo.get_record(key)
    assert rec is not None
    assert rec["status"] == "IN_PROGRESS"

    # Second acquisition fails
    assert repo.acquire_lock(key, "test_op") is False

    # Complete operation
    repo.complete_operation(key, {"outcome": "success"})
    completed = repo.get_record(key)
    assert completed["status"] == "COMPLETED"
    assert completed["result"] == {"outcome": "success"}


# 7. Expected Delivery & Tracking
def test_expected_delivery_query_and_tracking():
    repo = InMemoryExpectedDeliveryRepository()
    deliv = ExpectedDelivery(
        delivery_id="del_1",
        organization_id="org_alpha",
        location_id="loc_1",
        carrier="FedEx",
        tracking_number="TRACK123",
        status=ExpectedDeliveryStatus.TRUE,
        expected_window_start="2026-10-08T20:00:00Z",
        expected_window_end="2026-10-08T23:59:59Z",
    )
    repo.save_expected_delivery(deliv)

    # Window query
    matches = repo.find_deliveries_for_window(
        location_id="loc_1",
        organization_id="org_alpha",
        window_start="2026-10-08T21:00:00Z",
        window_end="2026-10-08T22:00:00Z",
    )
    assert len(matches) == 1
    assert matches[0].delivery_id == "del_1"

    # Tracking lookup
    found = repo.get_by_tracking("org_alpha", "TRACK123")
    assert found is not None
    assert found.carrier == "FedEx"

    # Cross org tracking lookup returns None
    assert repo.get_by_tracking("org_beta", "TRACK123") is None


# 8. Policy Repository
def test_policy_persistence():
    repo = InMemoryPolicyRepository()
    policy = Policy(
        policy_id="pol_1",
        organization_id="org_alpha",
        allowed_actions=[ActionType.NOTIFY_OPERATOR, ActionType.MARK_FOR_REVIEW],
    )
    repo.save_policy(policy)

    retrieved = repo.get_policy("org_alpha")
    assert retrieved is not None
    assert len(retrieved.allowed_actions) == 2
    assert repo.get_policy("org_unknown") is None
