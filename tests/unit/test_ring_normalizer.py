"""Unit tests for RingNormalizer."""

from apps.api.src.services.ring_normalizer import RingNormalizer
from packages.contracts.enums import Provenance
from packages.contracts.models import (
    Location,
    RingDevice,
    RingEvent,
)


def _setup_entities():
    loc = Location(
        location_id="loc_test",
        organization_id="org_test",
        name="HQ",
        timezone="UTC",
        business_hours_start="08:00",
        business_hours_end="20:00",
        business_days=[0, 1, 2, 3, 4],
    )
    door_device = RingDevice(
        device_id="door_front",
        location_id="loc_test",
        name="Front Door",
        kind="doorbell",
        is_designated_door=True,
    )
    camera_device = RingDevice(
        device_id="cam_side",
        location_id="loc_test",
        name="Side Alley Camera",
        kind="camera",
        is_designated_door=False,
    )
    return loc, door_device, camera_device


def test_normalize_doorbell_at_designated_door():
    loc, door_device, _ = _setup_entities()
    normalizer = RingNormalizer()

    event = RingEvent(
        event_id="evt_01",
        request_id="req_01",
        device_id="door_front",
        event_type="button_press",
        occurred_at="2026-10-07T22:30:00Z",  # after-hours
        provenance=Provenance.RING_SIGNED,
        payload={"raw": "data"},
    )

    norm = normalizer.normalize(event=event, location=loc, device=door_device)
    assert norm.source_event_id == "evt_01"
    assert norm.device_id == "door_front"
    assert norm.location_id == "loc_test"
    assert norm.is_designated_door is True
    assert norm.is_after_hours is True
    assert norm.provenance == Provenance.RING_SIGNED
    assert norm.description == "Doorbell activity observed at designated entrance"
    # Adheres strictly to Ring terminology
    assert "package" not in norm.description.lower()
    assert "delivery" not in norm.description.lower()


def test_normalize_motion_at_non_designated_door():
    loc, _, camera_device = _setup_entities()
    normalizer = RingNormalizer()

    event = RingEvent(
        event_id="evt_02",
        request_id="req_02",
        device_id="cam_side",
        event_type="motion_detected",
        occurred_at="2026-10-07T14:00:00Z",  # during business hours
        provenance=Provenance.DEMO_SYNTHETIC,
        payload={"motion_zone": 1},
    )

    norm = normalizer.normalize(event=event, location=loc, device=camera_device)
    assert norm.source_event_id == "evt_02"
    assert norm.device_id == "cam_side"
    assert norm.is_designated_door is False
    assert norm.is_after_hours is False
    assert norm.provenance == Provenance.DEMO_SYNTHETIC
    assert norm.description == "Motion activity observed at monitored device"
    assert norm.raw_metadata == {"motion_zone": 1}
    assert "package" not in norm.description.lower()
    assert "delivery" not in norm.description.lower()
