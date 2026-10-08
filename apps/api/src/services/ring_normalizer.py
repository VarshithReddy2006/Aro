"""Deterministic Ring event normalizer service.

Transforms raw, validated RingEvent entities into canonical NormalizedEvent entities:
- Enforces strict Ring terminology (NEVER "package detected" or "delivery confirmed").
- Calculates after-hours classification deterministically via BusinessHoursService.
- Derives designated entrance status from RingDevice configuration.
- Preserves raw event provenance and metadata.
- Strictly avoids AI classification or ungrounded assumptions.
"""

from packages.contracts.models import (
    Location,
    NormalizedEvent,
    RingDevice,
    RingEvent,
)

from .business_hours import BusinessHoursService


class RingNormalizer:
    """Deterministic event normalizer adhering strictly to operational policy."""

    def __init__(self, business_hours_service: BusinessHoursService | None = None) -> None:
        self.business_hours_service = business_hours_service or BusinessHoursService()

    def normalize(
        self,
        event: RingEvent,
        location: Location,
        device: RingDevice | None = None,
    ) -> NormalizedEvent:
        """Map raw RingEvent to canonical NormalizedEvent.

        Args:
            event: Validated raw Ring event.
            location: Monitored location for schedule and timezone context.
            device: Associated Ring device metadata if known.

        Returns:
            NormalizedEvent ready for case correlation handoff.
        """
        is_designated_door = device.is_designated_door if device else False
        is_after_hours = self.business_hours_service.is_after_hours(
            occurred_at=event.occurred_at,
            location=location,
        )

        # Factual, grounded description following Ring terminology rules
        door_label = "designated entrance" if is_designated_door else "monitored device"
        if event.event_type.lower() in ("button_press", "doorbell_ring"):
            description = f"Doorbell activity observed at {door_label}"
        else:
            description = f"Motion activity observed at {door_label}"

        normalized_event_id = f"norm_{event.event_id}"

        return NormalizedEvent(
            normalized_event_id=normalized_event_id,
            source_event_id=event.event_id,
            device_id=event.device_id,
            location_id=location.location_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            provenance=event.provenance,
            is_after_hours=is_after_hours,
            is_designated_door=is_designated_door,
            description=description,
            raw_metadata=event.payload,
        )
