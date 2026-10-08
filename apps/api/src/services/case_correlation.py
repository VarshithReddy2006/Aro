"""Deterministic case correlation and lifecycle handoff service.

Enforces strict case creation and association policy:
- Does NOT create cases for every Ring event.
- Associates subsequent events within a configured correlation window to an existing active case.
- Enforces strict tenant isolation (organization_id).
- Only creates a new case when after-hours activity is observed at a designated entrance.
- Events during normal business hours remain safely persisted as validated events
  without cluttering the operational case queue with artificial records.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from packages.contracts.enums import CaseStatus
from packages.contracts.models import (
    Case,
    Location,
    NormalizedEvent,
    RingDevice,
    RingEvent,
)

from ..repositories.interfaces import CaseRepository, EventRepository


@dataclass(frozen=True)
class CorrelationResult:
    """Outcome of case correlation evaluation."""

    case_id: str | None
    is_new_case: bool
    correlated: bool
    reason: str


class CaseCorrelationService:
    """Deterministic case correlation policy engine."""

    def __init__(
        self,
        event_repository: EventRepository,
        case_repository: CaseRepository,
        correlation_window_seconds: int = 900,  # 15 minutes
    ) -> None:
        self.event_repo = event_repository
        self.case_repo = case_repository
        self.correlation_window_seconds = correlation_window_seconds

    def correlate(
        self,
        event: RingEvent,
        normalized_event: NormalizedEvent,
        organization_id: str,
        location: Location | None = None,
        device: RingDevice | None = None,
    ) -> CorrelationResult:
        """Evaluate correlation against active cases or create a new case per policy.

        Args:
            event: Raw Ring event entity.
            normalized_event: Canonically enriched normalized event.
            organization_id: Target tenant organization identifier.
            location: Associated location entity.
            device: Associated device entity.

        Returns:
            CorrelationResult with case_id and classification details.
        """
        # Parse event timestamp
        event_dt = self._parse_iso(event.occurred_at)

        # 1. Search for existing active (non-closed) cases at this location and device
        existing_cases = self.case_repo.list_cases(
            organization_id=organization_id,
            location_id=normalized_event.location_id,
        )

        for candidate in existing_cases:
            if candidate.status == CaseStatus.CLOSED:
                continue
            if candidate.device_id != event.device_id:
                continue

            # Exact event or case match is immediately correlated regardless of time delta
            if (
                candidate.event_id == event.event_id
                or candidate.case_id == f"case_{event.event_id}"
            ):
                self.event_repo.correlate_event_to_case(
                    event_id=event.event_id,
                    case_id=candidate.case_id,
                )
                self.event_repo.save_normalized_event(
                    event=normalized_event,
                    case_id=candidate.case_id,
                )
                return CorrelationResult(
                    case_id=candidate.case_id,
                    is_new_case=False,
                    correlated=True,
                    reason=f"Correlated to existing case '{candidate.case_id}' for event '{event.event_id}'",
                )

            case_dt = self._parse_iso(candidate.created_at)
            time_diff = abs((event_dt - case_dt).total_seconds())

            if time_diff <= self.correlation_window_seconds:
                # Correlate to existing active case
                self.event_repo.correlate_event_to_case(
                    event_id=event.event_id,
                    case_id=candidate.case_id,
                )
                self.event_repo.save_normalized_event(
                    event=normalized_event,
                    case_id=candidate.case_id,
                )
                return CorrelationResult(
                    case_id=candidate.case_id,
                    is_new_case=False,
                    correlated=True,
                    reason=f"Correlated to active case '{candidate.case_id}' (delta: {time_diff:.0f}s)",
                )

        # 2. No matching active case found: Check deterministic creation policy
        # Policy rule: Only create an operational case if activity occurred after-hours
        # AND at a designated entrance.
        should_create_case = normalized_event.is_after_hours and normalized_event.is_designated_door

        if not should_create_case:
            # Event remains safely persisted under VALIDATED status in pre-case partition.
            return CorrelationResult(
                case_id=None,
                is_new_case=False,
                correlated=False,
                reason=(
                    "Event did not meet case creation policy: "
                    f"after_hours={normalized_event.is_after_hours}, "
                    f"designated_door={normalized_event.is_designated_door}"
                ),
            )

        # 3. Create new operational case
        case_id = f"case_{event.event_id}"
        device_label = device.name if device else event.device_id
        title = f"After-Hours Activity observed at {device_label}"

        new_case = Case(
            case_id=case_id,
            organization_id=organization_id,
            location_id=normalized_event.location_id,
            device_id=event.device_id,
            event_id=event.event_id,
            title=title,
            status=CaseStatus.RECEIVED,
            summary=normalized_event.description,
        )
        self.case_repo.create_case(new_case)

        # Correlate triggering event to newly created case
        self.event_repo.correlate_event_to_case(
            event_id=event.event_id,
            case_id=case_id,
        )
        self.event_repo.save_normalized_event(
            event=normalized_event,
            case_id=case_id,
        )

        return CorrelationResult(
            case_id=case_id,
            is_new_case=True,
            correlated=True,
            reason="Created new operational case for after-hours activity at designated entrance",
        )

    @staticmethod
    def _parse_iso(ts_str: str) -> datetime:
        try:
            cleaned = ts_str.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return datetime.now(UTC)
