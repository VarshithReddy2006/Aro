"""Unit tests for deterministic CaseContextBuilder."""

import pytest

from apps.api.src.repositories import (
    InMemoryCaseRepository,
    InMemoryDeviceRepository,
    InMemoryEventRepository,
    InMemoryExpectedDeliveryRepository,
    InMemoryLocationRepository,
    InMemoryPolicyRepository,
    OrganizationAccessDeniedError,
)
from apps.api.src.services.case_context_builder import CaseContextBuilder
from packages.contracts.enums import (
    ActionType,
    CaseStatus,
    ExpectedDeliveryStatus,
    Provenance,
)
from packages.contracts.models import (
    Case,
    ExpectedDelivery,
    Location,
    NormalizedEvent,
    Policy,
    RingDevice,
    RingEvent,
)


def _setup_context_fixture():
    case_repo = InMemoryCaseRepository()
    event_repo = InMemoryEventRepository()
    loc_repo = InMemoryLocationRepository()
    dev_repo = InMemoryDeviceRepository()
    deliv_repo = InMemoryExpectedDeliveryRepository()
    pol_repo = InMemoryPolicyRepository()

    # Location in NY
    loc = Location(
        location_id="loc_alpha",
        organization_id="org_alpha",
        name="Alpha HQ",
        timezone="America/New_York",
        business_hours_start="08:00",
        business_hours_end="20:00",
        business_days=[0, 1, 2, 3, 4],
    )
    loc_repo.save_location(loc)

    # Device
    dev = RingDevice(
        device_id="dev_front_door",
        location_id="loc_alpha",
        name="Front Entrance Doorbell",
        kind="doorbell",
        is_designated_door=True,
    )
    dev_repo.save_device(dev)

    # Policy
    pol = Policy(
        policy_id="pol_alpha",
        organization_id="org_alpha",
        allowed_actions=[
            ActionType.NOTIFY_OPERATOR,
            ActionType.MARK_FOR_REVIEW,
        ],
    )
    pol_repo.save_policy(pol)

    builder = CaseContextBuilder(
        case_repository=case_repo,
        event_repository=event_repo,
        location_repository=loc_repo,
        device_repository=dev_repo,
        delivery_repository=deliv_repo,
        policy_repository=pol_repo,
    )

    return {
        "builder": builder,
        "case_repo": case_repo,
        "event_repo": event_repo,
        "loc_repo": loc_repo,
        "dev_repo": dev_repo,
        "deliv_repo": deliv_repo,
        "pol_repo": pol_repo,
    }


def test_t_context_deterministic_assembly():
    fx = _setup_context_fixture()
    builder = fx["builder"]
    case_repo = fx["case_repo"]
    event_repo = fx["event_repo"]

    # 22:30 EDT = 02:30 UTC next day (after hours)
    event_ts = "2026-10-08T02:30:00Z"
    case_id = "case_ctx_01"
    evt_id = "evt_ctx_01"

    raw_event = RingEvent(
        event_id=evt_id,
        request_id="req_ctx_01",
        device_id="dev_front_door",
        event_type="button_press",
        occurred_at=event_ts,
        provenance=Provenance.RING_SIGNED,
        case_id=case_id,
    )
    event_repo.save_ring_event(raw_event)

    case = Case(
        case_id=case_id,
        organization_id="org_alpha",
        location_id="loc_alpha",
        device_id="dev_front_door",
        event_id=evt_id,
        title="Test Operational Case",
        status=CaseStatus.RECEIVED,
    )
    case_repo.create_case(case)

    norm_event = NormalizedEvent(
        normalized_event_id="norm_ctx_01",
        source_event_id=evt_id,
        device_id="dev_front_door",
        location_id="loc_alpha",
        event_type="button_press",
        occurred_at=event_ts,
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,
        is_designated_door=True,
        description="Doorbell activity observed at designated entrance",
    )
    event_repo.save_normalized_event(norm_event, case_id=case_id)

    bundle = builder.build_context(case_id=case_id, organization_id="org_alpha")

    assert bundle.case_context.case_id == case_id
    assert bundle.case_context.is_after_hours is True
    assert bundle.case_context.designated_entrance is True
    assert bundle.ai_input.case_id == case_id
    assert len(bundle.known_facts) > 0
    assert len(bundle.unknowns) > 0
    # Must explicitly state unknowns about delivery and identity
    assert any("parcel, courier package" in u for u in bundle.unknowns)
    assert any("personal identity" in u for u in bundle.unknowns)


def test_t_context_tenant_isolation_blocked():
    fx = _setup_context_fixture()
    builder = fx["builder"]
    case_repo = fx["case_repo"]

    case = Case(
        case_id="case_tenant_alpha",
        organization_id="org_alpha",
        location_id="loc_alpha",
        device_id="dev_front_door",
        event_id="evt_alpha",
        title="Alpha Case",
    )
    case_repo.create_case(case)

    # org_beta attempting to assemble context for org_alpha case must fail
    with pytest.raises(OrganizationAccessDeniedError):
        builder.build_context(case_id="case_tenant_alpha", organization_id="org_beta")


def test_t_delivery_true_matched():
    fx = _setup_context_fixture()
    builder = fx["builder"]
    case_repo = fx["case_repo"]
    event_repo = fx["event_repo"]
    deliv_repo = fx["deliv_repo"]

    event_ts = "2026-10-08T02:00:00Z"
    case_id = "case_deliv_match"
    evt_id = "evt_deliv_match"

    event_repo.save_ring_event(
        RingEvent(
            event_id=evt_id,
            request_id="req_match",
            device_id="dev_front_door",
            event_type="motion_detected",
            occurred_at=event_ts,
            provenance=Provenance.RING_SIGNED,
        )
    )
    case_repo.create_case(
        Case(
            case_id=case_id,
            organization_id="org_alpha",
            location_id="loc_alpha",
            device_id="dev_front_door",
            event_id=evt_id,
            title="Delivery Match Case",
        )
    )

    # Add scheduled delivery for this window
    deliv_repo.save_expected_delivery(
        ExpectedDelivery(
            delivery_id="deliv_scheduled",
            organization_id="org_alpha",
            location_id="loc_alpha",
            carrier="UPS",
            tracking_number="1Z9999999999999999",
            recipient_name="Reception",
            status=ExpectedDeliveryStatus.TRUE,
            expected_window_start="2026-10-08T01:00:00Z",
            expected_window_end="2026-10-08T03:00:00Z",
        )
    )

    bundle = builder.build_context(case_id=case_id, organization_id="org_alpha")
    assert bundle.expected_delivery_status == ExpectedDeliveryStatus.TRUE
    assert len(bundle.case_context.expected_deliveries) == 1
    assert bundle.case_context.expected_deliveries[0].carrier == "UPS"


def test_t_delivery_false_no_expected_delivery():
    fx = _setup_context_fixture()
    builder = fx["builder"]
    case_repo = fx["case_repo"]
    event_repo = fx["event_repo"]

    event_ts = "2026-10-08T02:00:00Z"
    case_id = "case_deliv_none"
    evt_id = "evt_deliv_none"

    event_repo.save_ring_event(
        RingEvent(
            event_id=evt_id,
            request_id="req_none",
            device_id="dev_front_door",
            event_type="motion_detected",
            occurred_at=event_ts,
            provenance=Provenance.RING_SIGNED,
        )
    )
    case_repo.create_case(
        Case(
            case_id=case_id,
            organization_id="org_alpha",
            location_id="loc_alpha",
            device_id="dev_front_door",
            event_id=evt_id,
            title="No Delivery Case",
        )
    )

    # No deliveries scheduled
    bundle = builder.build_context(case_id=case_id, organization_id="org_alpha")
    assert bundle.expected_delivery_status == ExpectedDeliveryStatus.FALSE
    assert len(bundle.case_context.expected_deliveries) == 0


def test_t_delivery_unknown_insufficient_evidence():
    fx = _setup_context_fixture()
    builder = fx["builder"]
    case_repo = fx["case_repo"]
    event_repo = fx["event_repo"]

    # Malformed timestamp string in raw event
    case_id = "case_deliv_unknown"
    evt_id = "evt_deliv_unknown"

    event_repo.save_ring_event(
        RingEvent(
            event_id=evt_id,
            request_id="req_unk",
            device_id="dev_front_door",
            event_type="motion_detected",
            occurred_at="invalid-iso-date",
            provenance=Provenance.RING_SIGNED,
        )
    )
    case_repo.create_case(
        Case(
            case_id=case_id,
            organization_id="org_alpha",
            location_id="loc_alpha",
            device_id="dev_front_door",
            event_id=evt_id,
            title="Unknown Delivery Case",
        )
    )

    bundle = builder.build_context(case_id=case_id, organization_id="org_alpha")
    assert bundle.expected_delivery_status == ExpectedDeliveryStatus.UNKNOWN
