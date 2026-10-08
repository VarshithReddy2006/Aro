"""Security invariant tests for Aro persistence layer.

Verifies:
1. Cross-tenant read rejection (Org A cannot read Org B's case).
2. Cross-tenant write rejection (Org A cannot update Org B's case).
3. Optimistic locking prevents stale version overwrite.
4. Concurrent execution lock acquisition yields strictly one winner.
5. Duplicate idempotency keys prevent concurrent duplicate operations.
6. Audit timeline records are strictly immutable.
7. Completed actions cannot acquire execution locks.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.api.src.repositories import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    ConflictError,
    InMemoryActionRepository,
    InMemoryAuditRepository,
    InMemoryCaseRepository,
    InMemoryIdempotencyRepository,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)
from packages.contracts.enums import (
    ActionStatus,
    ActionType,
    AuditEventType,
    CaseStatus,
)
from packages.contracts.models import (
    Action,
    AuditEvent,
    Case,
)


def _sample_case(
    case_id: str, org_id: str, status: CaseStatus = CaseStatus.RECEIVED, version: int = 1
) -> Case:
    return Case(
        case_id=case_id,
        organization_id=org_id,
        location_id="loc_1",
        device_id="dev_front",
        event_id="evt_001",
        title="Possible after-hours delivery activity at designated entrance",
        status=status,
        version=version,
    )


# Security Test 1: Cross-organization read rejection
def test_organization_a_cannot_retrieve_organization_b_case():
    repo = InMemoryCaseRepository()
    case = _sample_case("case_tenant_b", "org_beta")
    repo.create_case(case)

    # Valid tenant can read
    assert repo.get_case("case_tenant_b", "org_beta").case_id == "case_tenant_b"

    # Attacker or misconfigured caller from org_alpha is denied
    with pytest.raises(OrganizationAccessDeniedError) as exc_info:
        repo.get_case("case_tenant_b", "org_alpha")
    assert "cross-organization access denied" in str(exc_info.value).lower()


# Security Test 2: Cross-organization update rejection
def test_organization_a_cannot_update_organization_b_case():
    repo = InMemoryCaseRepository()
    case = _sample_case("case_tenant_b", "org_beta")
    repo.create_case(case)

    malicious_update = case.model_copy(update={"status": CaseStatus.CLOSED})
    with pytest.raises(OrganizationAccessDeniedError):
        repo.update_case(malicious_update, "org_alpha", expected_version=1)

    # Confirm original state unchanged
    intact = repo.get_case("case_tenant_b", "org_beta")
    assert intact.status == CaseStatus.RECEIVED
    assert intact.version == 1


# Security Test 3: Stale case version cannot overwrite current state
def test_stale_case_version_cannot_overwrite_current_state():
    repo = InMemoryCaseRepository()
    case = _sample_case("case_v", "org_alpha", version=5)
    repo.create_case(case)

    # Process 1 updates to version 6
    p1_update = case.model_copy(update={"status": CaseStatus.VALIDATED})
    repo.update_case(p1_update, "org_alpha", expected_version=5)

    # Process 2 attempts update assuming version 5
    p2_update = case.model_copy(update={"status": CaseStatus.FAILED})
    with pytest.raises(VersionMismatchError) as exc_info:
        repo.update_case(p2_update, "org_alpha", expected_version=5)
    assert exc_info.value.expected_version == 5
    assert exc_info.value.actual_version == 6


# Security Test 4: Concurrent execution-lock requests result in only one winner
def test_concurrent_execution_lock_requests_result_in_only_one_winner():
    case_repo = InMemoryCaseRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)

    case = _sample_case("case_race", "org_alpha", status=CaseStatus.APPROVED, version=1)
    case_repo.create_case(case)

    # Spawn 10 concurrent threads attempting to acquire the execution lock
    num_threads = 10
    successes = 0
    failures = 0

    def attempt_lock(index: int) -> bool:
        action_id = f"act_thread_{index}"
        try:
            action_repo.acquire_execution_lock(
                "case_race", action_id, "org_alpha", expected_case_version=1
            )
            return True
        except (AlreadyExecutingError, VersionMismatchError):
            return False

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        results = list(executor.map(attempt_lock, range(num_threads)))

    successes = results.count(True)
    failures = results.count(False)

    # Strictly 1 winner, remaining 9 rejected
    assert successes == 1
    assert failures == num_threads - 1

    final_case = case_repo.get_case("case_race", "org_alpha")
    assert final_case.status == CaseStatus.EXECUTING
    assert final_case.version == 2


# Security Test 5: Duplicate idempotency key cannot create two operations
def test_duplicate_idempotency_key_cannot_create_two_operations():
    repo = InMemoryIdempotencyRepository()
    key = "idem_critical_op_001"

    num_callers = 8

    def attempt_acquire(_: int) -> bool:
        return repo.acquire_lock(key, "critical_action")

    with ThreadPoolExecutor(max_workers=num_callers) as executor:
        acquisitions = list(executor.map(attempt_acquire, range(num_callers)))

    # Exactly 1 caller succeeds in acquiring the lock
    assert acquisitions.count(True) == 1
    assert acquisitions.count(False) == num_callers - 1


# Security Test 6: Audit records cannot be updated through repository APIs
def test_audit_records_cannot_be_updated_through_repository():
    repo = InMemoryAuditRepository()
    event = AuditEvent(
        event_id="aud_tamper_target",
        case_id="case_tamper",
        actor_id="usr_admin",
        actor_type="HUMAN",
        action=AuditEventType.APPROVAL_RECORDED,
        previous_hash="prev_hash",
        current_hash="valid_hash",
    )
    repo.append_audit_event(event, "org_alpha")

    # Attempt to tamper with the audit event (e.g. rewrite current_hash or action)
    tampered_event = event.model_copy(update={"current_hash": "forged_hash"})
    with pytest.raises(ConflictError) as exc_info:
        repo.append_audit_event(tampered_event, "org_alpha")
    assert "immutability violation" in str(exc_info.value).lower()

    # Verify original record remains intact
    timeline = repo.get_case_timeline("case_tamper", "org_alpha")
    assert len(timeline) == 1
    assert timeline[0].current_hash == "valid_hash"


# Security Test 7: A completed action cannot acquire another execution lock
def test_completed_action_cannot_acquire_another_execution_lock():
    case_repo = InMemoryCaseRepository()
    action_repo = InMemoryActionRepository(case_repo=case_repo)

    case = _sample_case("case_done", "org_alpha", status=CaseStatus.APPROVED, version=1)
    case_repo.create_case(case)

    action = Action(
        action_id="act_complete_once",
        case_id="case_done",
        approval_id="appr_done",
        action_type=ActionType.NOTIFY_OPERATOR,
        parameters={},
        status=ActionStatus.PENDING,
        idempotency_key="idemp_done",
    )
    action_repo.save_action(action, "org_alpha")

    # Acquire lock and complete
    action_repo.acquire_execution_lock("case_done", "act_complete_once", "org_alpha", 1)
    action_repo.complete_action("case_done", "act_complete_once", "org_alpha", "Finished")

    # Attempt to re-lock the completed action
    with pytest.raises(AlreadyCompletedError):
        action_repo.acquire_execution_lock("case_done", "act_complete_once", "org_alpha", 2)
