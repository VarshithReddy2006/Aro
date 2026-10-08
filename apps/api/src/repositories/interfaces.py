"""Canonical repository interfaces (Protocols) for Aro persistence."""

from typing import Any, Protocol

from packages.contracts.enums import CaseStatus
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


class CaseRepository(Protocol):
    """Persistence operations for Case entities."""

    def create_case(self, case: Case) -> Case:
        """Atomically create a new Case item, failing if case_id already exists."""
        ...

    def get_case(self, case_id: str, organization_id: str) -> Case:
        """Retrieve a Case by ID, enforcing organization tenant isolation."""
        ...

    def update_case(self, case: Case, organization_id: str, expected_version: int) -> Case:
        """Atomically update a Case using optimistic concurrency locking on version."""
        ...

    def list_cases(
        self,
        organization_id: str,
        status: CaseStatus | None = None,
        location_id: str | None = None,
        limit: int = 50,
    ) -> list[Case]:
        """List cases for an organization with optional status and location filtering."""
        ...


class EventRepository(Protocol):
    """Persistence operations for raw and normalized physical events."""

    def save_ring_event(self, event: RingEvent) -> RingEvent:
        """Persist an authenticated raw Ring event prior to case correlation."""
        ...

    def get_ring_event(self, event_id: str) -> RingEvent | None:
        """Retrieve a raw Ring event by event ID."""
        ...

    def quarantine_event(self, event_id: str, reason: str) -> RingEvent:
        """Mark an authenticated but malformed Ring event as quarantined with rationale."""
        ...

    def correlate_event_to_case(self, event_id: str, case_id: str) -> RingEvent:
        """Associate a previously ingested raw Ring event with an operational case."""
        ...

    def record_webhook_dedup(
        self, request_id: str, event_id: str, ttl_seconds: int = 86400
    ) -> bool:
        """Atomically record webhook request ID for deduplication. Returns False if already seen."""
        ...

    def save_normalized_event(self, event: NormalizedEvent, case_id: str) -> NormalizedEvent:
        """Persist an enriched normalized event linked to a case."""
        ...

    def get_case_events(self, case_id: str) -> list[NormalizedEvent]:
        """Retrieve all normalized events associated with a case."""
        ...


class ApprovalRepository(Protocol):
    """Persistence operations for human approval records."""

    def save_approval(self, approval: Approval, organization_id: str) -> Approval:
        """Atomically persist a human approval bound to a case and proposal hash."""
        ...

    def get_approval(self, case_id: str, approval_id: str, organization_id: str) -> Approval:
        """Retrieve an approval record by ID, enforcing tenant isolation."""
        ...


class ActionRepository(Protocol):
    """Persistence operations for consequential operational actions and execution locking."""

    def save_action(self, action: Action, organization_id: str) -> Action:
        """Persist an initial action record."""
        ...

    def get_action(self, case_id: str, action_id: str, organization_id: str) -> Action:
        """Retrieve an action record by ID."""
        ...

    def acquire_execution_lock(
        self, case_id: str, action_id: str, organization_id: str, expected_case_version: int
    ) -> None:
        """Atomically acquire the execution lock on an APPROVED case.

        Guarantees that exactly one caller can transition the case to EXECUTING.
        Raises AlreadyExecutingError or AlreadyCompletedError if already locked.
        """
        ...

    def complete_action(
        self, case_id: str, action_id: str, organization_id: str, result_summary: str
    ) -> Action:
        """Atomically mark an action as completed with outcome summary."""
        ...


class AuditRepository(Protocol):
    """Persistence operations for tamper-evident audit timeline records."""

    def append_audit_event(self, event: AuditEvent, organization_id: str) -> AuditEvent:
        """Atomically append an immutable audit record."""
        ...

    def get_case_timeline(self, case_id: str, organization_id: str) -> list[AuditEvent]:
        """Retrieve the complete chronological audit timeline for a case."""
        ...

    def get_latest_audit_event(self, case_id: str, organization_id: str) -> AuditEvent | None:
        """Retrieve the most recent audit record for hash-chain continuity."""
        ...


class IdempotencyRepository(Protocol):
    """Generic atomic idempotency locking and replay storage."""

    def acquire_lock(self, key: str, operation: str, ttl_seconds: int = 86400) -> bool:
        """Atomically acquire an IN_PROGRESS idempotency lock. Returns False if lock already exists."""
        ...

    def get_record(self, key: str) -> dict[str, Any] | None:
        """Retrieve an existing idempotency record."""
        ...

    def complete_operation(self, key: str, result: dict[str, Any]) -> None:
        """Mark an idempotency record as COMPLETED with cached outcome result."""
        ...


class ExpectedDeliveryRepository(Protocol):
    """Persistence operations for expected shipment context records."""

    def save_expected_delivery(self, delivery: ExpectedDelivery) -> ExpectedDelivery:
        """Persist an expected delivery record."""
        ...

    def find_deliveries_for_window(
        self,
        location_id: str,
        organization_id: str,
        window_start: str,
        window_end: str,
    ) -> list[ExpectedDelivery]:
        """Query expected deliveries active within a specified time window for a location."""
        ...

    def get_by_tracking(
        self, organization_id: str, tracking_number: str
    ) -> ExpectedDelivery | None:
        """Lookup an expected delivery by tracking number within an organization."""
        ...


class PolicyRepository(Protocol):
    """Persistence operations for tenant policy configurations."""

    def save_policy(self, policy: Policy) -> Policy:
        """Persist or update tenant policy."""
        ...

    def get_policy(self, organization_id: str) -> Policy | None:
        """Retrieve policy for an organization."""
        ...
