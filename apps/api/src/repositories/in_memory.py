"""In-memory reference repository implementations for Aro domain testing.

Provides fast, deterministic, offline execution with zero AWS dependencies while
faithfully enforcing all security invariants:
- Multi-tenant organization isolation
- Optimistic concurrency version guards
- Atomic execution locking
- Audit timeline append immutability
- Idempotency token locking
"""

from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from packages.contracts.enums import ActionStatus, CaseStatus, EventProcessingStatus
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

from .errors import (
    AlreadyCompletedError,
    AlreadyExecutingError,
    ConflictError,
    NotFoundError,
    OrganizationAccessDeniedError,
    VersionMismatchError,
)


class InMemoryCaseRepository:
    """Thread-safe in-memory Case repository enforcing optimistic concurrency and tenant isolation."""

    def __init__(self) -> None:
        self._cases: dict[str, Case] = {}
        self._lock = Lock()

    def create_case(self, case: Case) -> Case:
        with self._lock:
            if case.case_id in self._cases:
                raise ConflictError(f"Case with ID '{case.case_id}' already exists.")
            stored = case.model_copy()
            self._cases[case.case_id] = stored
            return deepcopy(stored)

    def get_case(self, case_id: str, organization_id: str) -> Case:
        with self._lock:
            case = self._cases.get(case_id)
            if not case:
                raise NotFoundError("Case", case_id)
            if case.organization_id != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Case/{case_id}",
                    expected_org_id=organization_id,
                    actual_org_id=case.organization_id,
                )
            return deepcopy(case)

    def update_case(self, case: Case, organization_id: str, expected_version: int) -> Case:
        with self._lock:
            existing = self._cases.get(case.case_id)
            if not existing:
                raise NotFoundError("Case", case.case_id)
            if existing.organization_id != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Case/{case.case_id}",
                    expected_org_id=organization_id,
                    actual_org_id=existing.organization_id,
                )
            if existing.version != expected_version:
                raise VersionMismatchError(
                    case_id=case.case_id,
                    expected_version=expected_version,
                    actual_version=existing.version,
                )

            updated = case.model_copy(
                update={
                    "version": expected_version + 1,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            self._cases[case.case_id] = updated
            return deepcopy(updated)

    def list_cases(
        self,
        organization_id: str,
        status: CaseStatus | None = None,
        location_id: str | None = None,
        limit: int = 50,
    ) -> list[Case]:
        with self._lock:
            matched = [
                c
                for c in self._cases.values()
                if c.organization_id == organization_id
                and (status is None or c.status == status)
                and (location_id is None or c.location_id == location_id)
            ]
            # Chronological order by updated_at descending
            matched.sort(key=lambda x: x.updated_at, reverse=True)
            return [deepcopy(c) for c in matched[:limit]]


class InMemoryEventRepository:
    """Thread-safe in-memory Event repository for raw and normalized Ring events."""

    def __init__(self) -> None:
        self._ring_events: dict[str, RingEvent] = {}
        self._webhook_dedup: dict[str, str] = {}  # request_id -> event_id
        self._case_events: dict[str, list[NormalizedEvent]] = {}
        self._lock = Lock()

    def save_ring_event(self, event: RingEvent) -> RingEvent:
        with self._lock:
            self._ring_events[event.event_id] = deepcopy(event)
            return deepcopy(event)

    def get_ring_event(self, event_id: str) -> RingEvent | None:
        with self._lock:
            evt = self._ring_events.get(event_id)
            return deepcopy(evt) if evt else None

    def quarantine_event(self, event_id: str, reason: str) -> RingEvent:
        with self._lock:
            evt = self._ring_events.get(event_id)
            if not evt:
                raise NotFoundError("RingEvent", event_id)
            updated = evt.model_copy(
                update={
                    "processing_status": EventProcessingStatus.QUARANTINED,
                    "quarantine_reason": reason,
                }
            )
            self._ring_events[event_id] = updated
            return deepcopy(updated)

    def correlate_event_to_case(self, event_id: str, case_id: str) -> RingEvent:
        with self._lock:
            evt = self._ring_events.get(event_id)
            if not evt:
                raise NotFoundError("RingEvent", event_id)
            updated = evt.model_copy(
                update={
                    "case_id": case_id,
                    "processing_status": EventProcessingStatus.CORRELATED,
                }
            )
            self._ring_events[event_id] = updated
            return deepcopy(updated)

    def record_webhook_dedup(
        self, request_id: str, event_id: str, ttl_seconds: int = 86400
    ) -> bool:
        with self._lock:
            if request_id in self._webhook_dedup:
                return False
            self._webhook_dedup[request_id] = event_id
            return True

    def save_normalized_event(self, event: NormalizedEvent, case_id: str) -> NormalizedEvent:
        with self._lock:
            if case_id not in self._case_events:
                self._case_events[case_id] = []
            self._case_events[case_id].append(deepcopy(event))
            return deepcopy(event)

    def get_case_events(self, case_id: str) -> list[NormalizedEvent]:
        with self._lock:
            events = self._case_events.get(case_id, [])
            return [deepcopy(e) for e in events]


class InMemoryApprovalRepository:
    """Thread-safe in-memory Approval repository."""

    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}  # approval_id -> Approval
        self._approval_orgs: dict[str, str] = {}  # approval_id -> org_id
        self._lock = Lock()

    def save_approval(self, approval: Approval, organization_id: str) -> Approval:
        with self._lock:
            self._approvals[approval.approval_id] = deepcopy(approval)
            self._approval_orgs[approval.approval_id] = organization_id
            return deepcopy(approval)

    def get_approval(self, case_id: str, approval_id: str, organization_id: str) -> Approval:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if not approval or approval.case_id != case_id:
                raise NotFoundError("Approval", approval_id)
            actual_org = self._approval_orgs.get(approval_id)
            if actual_org != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Approval/{approval_id}",
                    expected_org_id=organization_id,
                    actual_org_id=actual_org or "unknown",
                )
            return deepcopy(approval)


class InMemoryActionRepository:
    """Thread-safe in-memory Action repository providing atomic execution locking."""

    def __init__(self, case_repo: InMemoryCaseRepository | None = None) -> None:
        self._actions: dict[str, Action] = {}
        self._action_orgs: dict[str, str] = {}
        self._execution_locks: dict[str, str] = {}  # case_id -> action_id
        self._case_repo = case_repo
        self._lock = Lock()

    def save_action(self, action: Action, organization_id: str) -> Action:
        with self._lock:
            self._actions[action.action_id] = deepcopy(action)
            self._action_orgs[action.action_id] = organization_id
            return deepcopy(action)

    def get_action(self, case_id: str, action_id: str, organization_id: str) -> Action:
        with self._lock:
            action = self._actions.get(action_id)
            if not action or action.case_id != case_id:
                raise NotFoundError("Action", action_id)
            actual_org = self._action_orgs.get(action_id)
            if actual_org != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Action/{action_id}",
                    expected_org_id=organization_id,
                    actual_org_id=actual_org or "unknown",
                )
            return deepcopy(action)

    def acquire_execution_lock(
        self, case_id: str, action_id: str, organization_id: str, expected_case_version: int
    ) -> None:
        with self._lock:
            # Check if this case or action already has an execution lock or has completed
            existing_action = self._actions.get(action_id)
            if existing_action and existing_action.status == ActionStatus.SUCCEEDED:
                raise AlreadyCompletedError(action_id)

            if case_id in self._execution_locks:
                locked_action_id = self._execution_locks[case_id]
                raise AlreadyExecutingError(locked_action_id)

            # If case_repo is wired, verify case state and update version atomically
            if self._case_repo:
                case = self._case_repo.get_case(case_id, organization_id)
                if case.status != CaseStatus.APPROVED:
                    if case.status == CaseStatus.EXECUTING:
                        raise AlreadyExecutingError(action_id)
                    if case.status in {CaseStatus.COMPLETED, CaseStatus.CLOSED}:
                        raise AlreadyCompletedError(action_id)
                    raise ConflictError(
                        f"Cannot acquire execution lock on case with status '{case.status}'. "
                        "Case must be in APPROVED state."
                    )
                # Transition case state to EXECUTING
                updated_case = case.model_copy(update={"status": CaseStatus.EXECUTING})
                self._case_repo.update_case(updated_case, organization_id, expected_case_version)

            self._execution_locks[case_id] = action_id
            if existing_action:
                self._actions[action_id] = existing_action.model_copy(
                    update={
                        "status": ActionStatus.EXECUTING,
                        "executed_at": datetime.now(UTC).isoformat(),
                    }
                )

    def complete_action(
        self, case_id: str, action_id: str, organization_id: str, result_summary: str
    ) -> Action:
        with self._lock:
            action = self._actions.get(action_id)
            if not action or action.case_id != case_id:
                raise NotFoundError("Action", action_id)
            actual_org = self._action_orgs.get(action_id)
            if actual_org != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Action/{action_id}",
                    expected_org_id=organization_id,
                    actual_org_id=actual_org or "unknown",
                )

            updated = action.model_copy(
                update={
                    "status": ActionStatus.SUCCEEDED,
                    "result_summary": result_summary,
                }
            )
            self._actions[action_id] = updated
            return deepcopy(updated)


class InMemoryAuditRepository:
    """Thread-safe in-memory Audit repository enforcing append-only immutability."""

    def __init__(self) -> None:
        self._timelines: dict[str, list[AuditEvent]] = {}  # case_id -> list[AuditEvent]
        self._seen_events: set[tuple[str, str]] = set()  # (case_id, event_id)
        self._case_orgs: dict[str, str] = {}
        self._lock = Lock()

    def append_audit_event(self, event: AuditEvent, organization_id: str) -> AuditEvent:
        with self._lock:
            key = (event.case_id, event.event_id)
            if key in self._seen_events:
                raise ConflictError(
                    f"Audit record immutability violation: Audit event '{event.event_id}' "
                    f"for case '{event.case_id}' already exists and cannot be modified."
                )

            if event.case_id in self._case_orgs:
                if self._case_orgs[event.case_id] != organization_id:
                    raise OrganizationAccessDeniedError(
                        target_resource=f"Audit/Case/{event.case_id}",
                        expected_org_id=organization_id,
                        actual_org_id=self._case_orgs[event.case_id],
                    )
            else:
                self._case_orgs[event.case_id] = organization_id

            if event.case_id not in self._timelines:
                self._timelines[event.case_id] = []

            stored = event.model_copy()
            self._timelines[event.case_id].append(stored)
            self._seen_events.add(key)
            return deepcopy(stored)

    def get_case_timeline(self, case_id: str, organization_id: str) -> list[AuditEvent]:
        with self._lock:
            actual_org = self._case_orgs.get(case_id)
            if actual_org and actual_org != organization_id:
                raise OrganizationAccessDeniedError(
                    target_resource=f"Audit/Case/{case_id}",
                    expected_org_id=organization_id,
                    actual_org_id=actual_org,
                )
            timeline = self._timelines.get(case_id, [])
            sorted_events = sorted(timeline, key=lambda e: e.timestamp)
            return [deepcopy(e) for e in sorted_events]

    def get_latest_audit_event(self, case_id: str, organization_id: str) -> AuditEvent | None:
        with self._lock:
            timeline = self.get_case_timeline(case_id, organization_id)
            return timeline[-1] if timeline else None


class InMemoryIdempotencyRepository:
    """Thread-safe in-memory Idempotency lock and result cache."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def acquire_lock(self, key: str, operation: str, ttl_seconds: int = 86400) -> bool:
        with self._lock:
            if key in self._records:
                return False
            self._records[key] = {
                "key": key,
                "operation": operation,
                "status": "IN_PROGRESS",
                "created_at": datetime.now(UTC).isoformat(),
                "result": None,
            }
            return True

    def get_record(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._records.get(key)
            return deepcopy(rec) if rec else None

    def complete_operation(self, key: str, result: dict[str, Any]) -> None:
        with self._lock:
            if key not in self._records:
                raise NotFoundError("IdempotencyRecord", key)
            self._records[key]["status"] = "COMPLETED"
            self._records[key]["result"] = deepcopy(result)


class InMemoryExpectedDeliveryRepository:
    """Thread-safe in-memory ExpectedDelivery repository."""

    def __init__(self) -> None:
        self._deliveries: dict[str, ExpectedDelivery] = {}
        self._lock = Lock()

    def save_expected_delivery(self, delivery: ExpectedDelivery) -> ExpectedDelivery:
        with self._lock:
            self._deliveries[delivery.delivery_id] = deepcopy(delivery)
            return deepcopy(delivery)

    def find_deliveries_for_window(
        self,
        location_id: str,
        organization_id: str,
        window_start: str,
        window_end: str,
    ) -> list[ExpectedDelivery]:
        with self._lock:
            matches: list[ExpectedDelivery] = []
            for d in self._deliveries.values():
                if d.location_id != location_id or d.organization_id != organization_id:
                    continue
                # Overlap check
                if d.expected_window_start and d.expected_window_end:
                    if (
                        d.expected_window_start <= window_end
                        and d.expected_window_end >= window_start
                    ):
                        matches.append(deepcopy(d))
                else:
                    # If window is unspecified or open-ended, include for review
                    matches.append(deepcopy(d))
            return matches

    def get_by_tracking(
        self, organization_id: str, tracking_number: str
    ) -> ExpectedDelivery | None:
        with self._lock:
            for d in self._deliveries.values():
                if d.organization_id == organization_id and d.tracking_number == tracking_number:
                    return deepcopy(d)
            return None


class InMemoryPolicyRepository:
    """Thread-safe in-memory Policy repository."""

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}
        self._lock = Lock()

    def save_policy(self, policy: Policy) -> Policy:
        with self._lock:
            self._policies[policy.organization_id] = deepcopy(policy)
            return deepcopy(policy)

    def get_policy(self, organization_id: str) -> Policy | None:
        with self._lock:
            pol = self._policies.get(organization_id)
            return deepcopy(pol) if pol else None
