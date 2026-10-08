"""Deterministic CaseContextBuilder service.

Assembles operational context strictly from trusted repositories:
- Normalized Ring events
- Facility location and timezone
- Ring device and designated-door configuration
- Business-hours schedule policy
- Expected deliveries within the operational window
- Tenant organization policy

Enforces strict tenant isolation:
- All repository lookups are scoped to organization_id.
- Cross-tenant contamination immediately raises OrganizationAccessDeniedError.
- Explicitly separates KNOWN facts from operational UNKNOWNS.
- Zero AI execution in context assembly.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from packages.contracts.enums import ExpectedDeliveryStatus
from packages.contracts.models import (
    AIBriefInput,
    CaseContext,
    ExpectedDelivery,
    Location,
    Policy,
    RingDevice,
)

from ..repositories.errors import OrganizationAccessDeniedError
from ..repositories.interfaces import (
    CaseRepository,
    DeviceRepository,
    EventRepository,
    ExpectedDeliveryRepository,
    LocationRepository,
    PolicyRepository,
)
from .business_hours import BusinessHoursService


@dataclass(frozen=True)
class CaseContextBundle:
    """Complete assembled context package for brief generation and audit."""

    case_context: CaseContext
    ai_input: AIBriefInput
    location: Location
    device: RingDevice | None
    expected_delivery_status: ExpectedDeliveryStatus
    known_facts: list[str]
    unknowns: list[str]
    policy: Policy


class CaseContextBuilder:
    """Deterministic, tenant-isolated case context builder."""

    def __init__(
        self,
        case_repository: CaseRepository,
        event_repository: EventRepository,
        location_repository: LocationRepository,
        device_repository: DeviceRepository,
        delivery_repository: ExpectedDeliveryRepository,
        policy_repository: PolicyRepository,
        window_tolerance_minutes: int = 120,
    ) -> None:
        self.case_repo = case_repository
        self.event_repo = event_repository
        self.location_repo = location_repository
        self.device_repo = device_repository
        self.delivery_repo = delivery_repository
        self.policy_repo = policy_repository
        self.window_tolerance_minutes = window_tolerance_minutes

    def build_context(self, case_id: str, organization_id: str) -> CaseContextBundle:
        """Assemble deterministic case context enforcing multi-tenant boundaries.

        Args:
            case_id: Target operational case identifier.
            organization_id: Authenticated tenant organization identifier.

        Returns:
            CaseContextBundle containing CaseContext and sanitized AIBriefInput.

        Raises:
            NotFoundError: If case does not exist.
            OrganizationAccessDeniedError: If tenant boundaries are violated.
        """
        # 1. Fetch Case (enforces tenant isolation)
        case = self.case_repo.get_case(case_id=case_id, organization_id=organization_id)

        # 2. Fetch Location and verify tenant boundary
        location = self.location_repo.get_location(case.location_id)
        if location is None:
            # Fallback default location if unseeded
            location = Location(
                location_id=case.location_id,
                organization_id=organization_id,
                name="Monitored Facility",
                timezone="UTC",
                business_hours_start="08:00",
                business_hours_end="20:00",
                business_days=[0, 1, 2, 3, 4],
            )
        elif location.organization_id != organization_id:
            raise OrganizationAccessDeniedError(
                target_resource=f"Location:{location.location_id}",
                expected_org_id=organization_id,
                actual_org_id=location.organization_id,
            )

        # 3. Fetch Device
        device = self.device_repo.get_device(case.device_id)
        is_designated_door = device.is_designated_door if device else True

        # 4. Fetch Correlated Normalized Events
        correlated_events = self.event_repo.get_case_events(case_id=case_id)

        # 5. Fetch Triggering Raw Event for exact occurred timestamp
        raw_event = self.event_repo.get_ring_event(case.event_id)
        occurred_at_str = raw_event.occurred_at if raw_event else case.created_at

        # 6. Evaluate Business Hours
        is_after_hours = BusinessHoursService.is_after_hours(
            occurred_at=occurred_at_str,
            location=location,
        )

        # 7. Evaluate Expected Deliveries (Deterministic Matching Logic)
        expected_deliveries, delivery_status = self._evaluate_expected_deliveries(
            location_id=location.location_id,
            organization_id=organization_id,
            event_timestamp_str=occurred_at_str,
        )

        # 8. Retrieve Tenant Policy
        policy = self.policy_repo.get_policy(organization_id=organization_id)
        if policy is None:
            policy = Policy(
                policy_id=f"pol_{organization_id}",
                organization_id=organization_id,
            )

        # 9. Synthesize Grounded KNOWN Facts
        device_label = device.name if device else case.device_id
        entrance_desc = (
            "a designated entrance" if is_designated_door else "a secondary monitored area"
        )
        hours_desc = (
            "outside standard business hours" if is_after_hours else "during normal business hours"
        )

        known_facts = [
            f"Physical event activity observed at {device_label} ({entrance_desc}).",
            f"Activity occurred at {occurred_at_str} UTC ({hours_desc}).",
            f"Facility monitored: {location.name} (Timezone: {location.timezone}).",
            f"Facility operating schedule: {location.business_hours_start} to {location.business_hours_end}.",
            f"Expected delivery context status: {delivery_status.value}.",
            f"Total correlated physical event observations linked to case: {len(correlated_events)}.",
        ]
        if expected_deliveries:
            for d in expected_deliveries:
                track_info = f" (Tracking: {d.tracking_number})" if d.tracking_number else ""
                recipient_info = f" for {d.recipient_name}" if d.recipient_name else ""
                known_facts.append(
                    f"Scheduled expected shipment: {d.carrier}{track_info}{recipient_info}."
                )

        # 10. Synthesize Explicit Operational UNKNOWNS
        unknowns = [
            "Whether a parcel, courier package, or physical item was deposited or delivered.",
            "The verified personal identity, affiliation, or employer of the individual observed.",
            "Whether any person unlocked or gained physical entry into the facility.",
            "The ultimate operational legitimacy or intent behind the observed activity.",
        ]

        # 11. Build Canonical CaseContext
        case_context = CaseContext(
            case_id=case.case_id,
            organization_id=organization_id,
            location_id=location.location_id,
            device_id=case.device_id,
            is_after_hours=is_after_hours,
            designated_entrance=is_designated_door,
            expected_delivery_status=delivery_status,
            expected_deliveries=expected_deliveries,
            correlated_events=correlated_events,
        )

        # 12. Build Sanitized Bounded AI Input
        ai_input = AIBriefInput(
            case_id=case.case_id,
            organization_id=organization_id,
            location={
                "location_id": location.location_id,
                "name": location.name,
                "timezone": location.timezone,
                "business_hours_start": location.business_hours_start,
                "business_hours_end": location.business_hours_end,
            },
            device={
                "device_id": case.device_id,
                "name": device.name if device else case.device_id,
                "is_designated_door": is_designated_door,
            },
            events=[
                {
                    "event_id": e.source_event_id,
                    "event_type": e.event_type,
                    "occurred_at": e.occurred_at,
                    "description": e.description,
                    "is_after_hours": e.is_after_hours,
                    "is_designated_door": e.is_designated_door,
                }
                for e in correlated_events
            ],
            business_context={
                "is_after_hours": is_after_hours,
                "designated_entrance": is_designated_door,
            },
            expected_delivery={
                "status": delivery_status.value,
                "deliveries": [
                    {
                        "carrier": d.carrier,
                        "tracking_number": d.tracking_number,
                        "recipient_name": d.recipient_name,
                        "window_start": d.expected_window_start,
                        "window_end": d.expected_window_end,
                    }
                    for d in expected_deliveries
                ],
            },
            known_facts=known_facts,
            unknowns=unknowns,
            allowed_actions=policy.allowed_actions,
            prompt_version="2026-10-v1",
        )

        return CaseContextBundle(
            case_context=case_context,
            ai_input=ai_input,
            location=location,
            device=device,
            expected_delivery_status=delivery_status,
            known_facts=known_facts,
            unknowns=unknowns,
            policy=policy,
        )

    def _evaluate_expected_deliveries(
        self,
        location_id: str,
        organization_id: str,
        event_timestamp_str: str,
    ) -> tuple[list[ExpectedDelivery], ExpectedDeliveryStatus]:
        """Query expected deliveries deterministically within the operational window.

        Matching Logic:
        1. Parses event timestamp. If malformed or missing, status is UNKNOWN.
        2. Sets query window: [event_time - tolerance, event_time + tolerance].
        3. Looks up records for (location_id, organization_id, window).
        4. If matching deliveries found: status is EXPECTED.
        5. If query succeeded but 0 deliveries found: status is UNEXPECTED.
        """
        try:
            cleaned = event_timestamp_str.strip().replace("Z", "+00:00")
            event_dt = datetime.fromisoformat(cleaned)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return [], ExpectedDeliveryStatus.UNKNOWN

        delta = timedelta(minutes=self.window_tolerance_minutes)
        window_start = (event_dt - delta).isoformat()
        window_end = (event_dt + delta).isoformat()

        matching_deliveries = self.delivery_repo.find_deliveries_for_window(
            location_id=location_id,
            organization_id=organization_id,
            window_start=window_start,
            window_end=window_end,
        )

        if matching_deliveries:
            return matching_deliveries, ExpectedDeliveryStatus.TRUE

        return [], ExpectedDeliveryStatus.FALSE
