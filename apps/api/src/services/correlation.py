"""Case correlation handoff service boundary.

Manages the lifecycle transition from VALIDATED to CORRELATED:
- Does NOT create an artificial case merely because an event arrived.
- Correlates incoming normalized events with an existing active case if present.
- If no active case is found, the event remains safely stored in the pre-case partition
  under VALIDATED status, awaiting operational grouping.
- AI brief generation and case workflow are strictly excluded from Phase 3.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from packages.contracts.enums import CaseStatus
from packages.contracts.models import NormalizedEvent, RingEvent

from ..repositories.interfaces import CaseRepository, EventRepository


@dataclass(frozen=True)
class CorrelationOutcome:
    """Result of case correlation evaluation."""

    correlated: bool
    case_id: str | None = None
    message: str = ""
    is_new_case: bool = False


class CaseCorrelationServiceProtocol(Protocol):
    """Protocol for correlation handoff service."""

    def correlate(
        self,
        event: RingEvent,
        normalized_event: NormalizedEvent,
        organization_id: str,
    ) -> CorrelationOutcome:
        """Attempt to correlate a normalized event to an existing case."""
        ...


class DefaultCaseCorrelationService:
    """Default correlation service inspecting open cases without artificial case creation."""

    def __init__(
        self,
        event_repository: EventRepository,
        case_repository: CaseRepository | None = None,
    ) -> None:
        self.event_repo = event_repository
        self.case_repo = case_repository

    def correlate(
        self,
        event: RingEvent,
        normalized_event: NormalizedEvent,
        organization_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> CorrelationOutcome:
        """Check for an existing active case and associate the event if matched.

        If no existing case exists, the event remains VALIDATED without creating
        an artificial case.
        """
        if self.case_repo is not None:
            # Check for existing active cases at this location
            candidate_cases = self.case_repo.list_cases(
                organization_id=organization_id,
                location_id=normalized_event.location_id,
            )
            # Find an active (non-closed) case for the same device
            active_case = next(
                (
                    c
                    for c in candidate_cases
                    if c.device_id == event.device_id and c.status != CaseStatus.CLOSED
                ),
                None,
            )
            if active_case:
                # Correlate event to existing case
                self.event_repo.correlate_event_to_case(
                    event_id=event.event_id,
                    case_id=active_case.case_id,
                )
                self.event_repo.save_normalized_event(
                    event=normalized_event,
                    case_id=active_case.case_id,
                )
                return CorrelationOutcome(
                    correlated=True,
                    case_id=active_case.case_id,
                    message=f"Correlated to existing active case {active_case.case_id}",
                )

        return CorrelationOutcome(
            correlated=False,
            case_id=None,
            message="Event validated and persisted without active case correlation",
        )
