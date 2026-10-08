"""Unit tests for deterministic CaseCorrelationService."""

from datetime import UTC, datetime, timedelta

from apps.api.src.repositories import (
    InMemoryCaseRepository,
    InMemoryEventRepository,
)
from apps.api.src.services.case_correlation import CaseCorrelationService
from packages.contracts.enums import CaseStatus, Provenance
from packages.contracts.models import (
    Case,
    NormalizedEvent,
    RingDevice,
    RingEvent,
)


def _setup_service():
    event_repo = InMemoryEventRepository()
    case_repo = InMemoryCaseRepository()
    service = CaseCorrelationService(
        event_repository=event_repo,
        case_repository=case_repo,
        correlation_window_seconds=900,  # 15 minutes
    )
    return service, event_repo, case_repo


def test_t_case_correlation_uses_existing_active_case():
    service, event_repo, case_repo = _setup_service()

    now = datetime(2026, 10, 8, 2, 0, 0, tzinfo=UTC)
    now_iso = now.isoformat()

    # Pre-existing active case created 3 minutes ago
    case_time = (now - timedelta(minutes=3)).isoformat()
    existing_case = Case(
        case_id="case_active_100",
        organization_id="org_alpha",
        location_id="loc_hq",
        device_id="door_front",
        event_id="evt_prior",
        title="Active Operational Case",
        status=CaseStatus.RECEIVED,
        created_at=case_time,
    )
    case_repo.create_case(existing_case)

    # Incoming new event on same device
    raw_event = RingEvent(
        event_id="evt_new_200",
        request_id="req_new_200",
        device_id="door_front",
        event_type="motion_detected",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
    )
    event_repo.save_ring_event(raw_event)

    norm_event = NormalizedEvent(
        normalized_event_id="norm_new_200",
        source_event_id="evt_new_200",
        device_id="door_front",
        location_id="loc_hq",
        event_type="motion_detected",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,
        is_designated_door=True,
        description="Motion activity observed at designated entrance",
    )

    res = service.correlate(
        event=raw_event,
        normalized_event=norm_event,
        organization_id="org_alpha",
    )

    assert res.correlated is True
    assert res.is_new_case is False
    assert res.case_id == "case_active_100"

    # Event repository updated with correlation
    updated_raw = event_repo.get_ring_event("evt_new_200")
    assert updated_raw is not None
    assert updated_raw.case_id == "case_active_100"


def test_t_case_new_created_only_when_policy_requires():
    service, event_repo, case_repo = _setup_service()

    now_iso = datetime(2026, 10, 8, 2, 0, 0, tzinfo=UTC).isoformat()

    # 1. Normal-hours event -> Should NOT create case
    raw_day = RingEvent(
        event_id="evt_day_01",
        request_id="req_day_01",
        device_id="door_front",
        event_type="motion_detected",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
    )
    event_repo.save_ring_event(raw_day)
    norm_day = NormalizedEvent(
        normalized_event_id="norm_day_01",
        source_event_id="evt_day_01",
        device_id="door_front",
        location_id="loc_hq",
        event_type="motion_detected",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
        is_after_hours=False,  # Normal hours!
        is_designated_door=True,
        description="Motion activity observed at designated entrance",
    )
    res_day = service.correlate(raw_day, norm_day, organization_id="org_alpha")
    assert res_day.correlated is False
    assert res_day.case_id is None
    assert res_day.is_new_case is False

    # 2. After-hours event at designated entrance -> SHOULD create case
    raw_night = RingEvent(
        event_id="evt_night_01",
        request_id="req_night_01",
        device_id="door_front",
        event_type="button_press",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
    )
    event_repo.save_ring_event(raw_night)
    norm_night = NormalizedEvent(
        normalized_event_id="norm_night_01",
        source_event_id="evt_night_01",
        device_id="door_front",
        location_id="loc_hq",
        event_type="button_press",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,  # After hours!
        is_designated_door=True,  # Designated door!
        description="Doorbell activity observed at designated entrance",
    )
    res_night = service.correlate(
        raw_night,
        norm_night,
        organization_id="org_alpha",
        device=RingDevice(
            device_id="door_front",
            location_id="loc_hq",
            name="Front Door",
            is_designated_door=True,
        ),
    )
    assert res_night.correlated is True
    assert res_night.is_new_case is True
    assert res_night.case_id == "case_evt_night_01"

    created_case = case_repo.get_case("case_evt_night_01", organization_id="org_alpha")
    assert created_case.organization_id == "org_alpha"
    assert created_case.device_id == "door_front"


def test_t_tenant_no_cross_organization_correlation():
    service, event_repo, case_repo = _setup_service()

    now_iso = datetime(2026, 10, 8, 2, 0, 0, tzinfo=UTC).isoformat()

    # Case belongs to org_alpha
    case_repo.create_case(
        Case(
            case_id="case_alpha_only",
            organization_id="org_alpha",
            location_id="loc_shared",
            device_id="shared_device",
            event_id="evt_alpha",
            title="Alpha Case",
        )
    )

    # Event arrives for org_beta at same device
    raw_beta = RingEvent(
        event_id="evt_beta",
        request_id="req_beta",
        device_id="shared_device",
        event_type="button_press",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
    )
    event_repo.save_ring_event(raw_beta)

    norm_beta = NormalizedEvent(
        normalized_event_id="norm_beta",
        source_event_id="evt_beta",
        device_id="shared_device",
        location_id="loc_shared",
        event_type="button_press",
        occurred_at=now_iso,
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,
        is_designated_door=True,
        description="Doorbell activity observed at designated entrance",
    )

    res = service.correlate(raw_beta, norm_beta, organization_id="org_beta")
    # Must NOT correlate to org_alpha's case
    assert res.case_id != "case_alpha_only"
    # Should create its own case under org_beta
    assert res.is_new_case is True
    assert res.case_id == "case_evt_beta"

    case_beta = case_repo.get_case("case_evt_beta", organization_id="org_beta")
    assert case_beta.organization_id == "org_beta"
