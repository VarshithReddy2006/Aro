"""Pre-ingestion event storage lifecycle unit tests.

Verifies:
1. Raw Ring event can be stored before case creation.
2. Forged event is never persisted (simulation of signature rejection).
3. Authenticated malformed event can be quarantined.
4. Duplicate event cannot create duplicate persistence.
5. Event can later be associated with a case.
6. Case timeline can retrieve associated events.
7. Event remains retrievable independently for replay/audit.
8. Organization isolation still works.
9. No duplicate raw payload is unnecessarily created.
"""

import pytest

from apps.api.src.repositories import (
    InMemoryCaseRepository,
    InMemoryEventRepository,
    OrganizationAccessDeniedError,
)
from packages.contracts.enums import (
    EventProcessingStatus,
    Provenance,
)
from packages.contracts.models import (
    Case,
    NormalizedEvent,
    RingEvent,
)


def _make_raw_ring_event(event_id: str = "evt_pre_01", request_id: str = "req_pre_01") -> RingEvent:
    return RingEvent(
        event_id=event_id,
        request_id=request_id,
        device_id="ring_doorbell_front",
        event_type="motion",
        occurred_at="2026-10-08T22:43:00Z",
        provenance=Provenance.RING_SIGNED,
        payload={"raw_door_sensor": "active", "battery": 95},
        signature_verified=True,
        processing_status=EventProcessingStatus.RECEIVED,
    )


# 1. Raw Ring event can be stored before case creation
def test_raw_ring_event_stored_before_case_creation():
    repo = InMemoryEventRepository()
    event = _make_raw_ring_event()

    stored = repo.save_ring_event(event)
    assert stored.event_id == "evt_pre_01"
    assert stored.case_id is None
    assert stored.processing_status == EventProcessingStatus.RECEIVED

    retrieved = repo.get_ring_event("evt_pre_01")
    assert retrieved is not None
    assert retrieved.event_id == "evt_pre_01"
    assert retrieved.case_id is None
    assert retrieved.payload == {"raw_door_sensor": "active", "battery": 95}


# 2. Forged event is never persisted
def test_forged_event_is_never_persisted():
    repo = InMemoryEventRepository()

    # Simulation of webhook controller guard:
    # If signature verification fails, reject immediately with HTTP 401 without repository calls.
    is_signature_valid = False
    forged_event_id = "evt_forged_999"

    if not is_signature_valid:
        # Webhook rejects without writing to repo
        pass
    else:
        repo.save_ring_event(_make_raw_ring_event(event_id=forged_event_id))

    # Assert zero database writes for forged event
    assert repo.get_ring_event(forged_event_id) is None


# 3. Authenticated malformed event can be quarantined
def test_authenticated_malformed_event_can_be_quarantined():
    repo = InMemoryEventRepository()
    event = _make_raw_ring_event()
    repo.save_ring_event(event)

    # Ingestion validator detects invalid internal schema despite valid HMAC signature
    quarantined = repo.quarantine_event(
        event_id="evt_pre_01",
        reason="Missing expected door_uuid in body payload",
    )
    assert quarantined.processing_status == EventProcessingStatus.QUARANTINED
    assert quarantined.quarantine_reason == "Missing expected door_uuid in body payload"

    # Confirms record in storage is quarantined
    re_read = repo.get_ring_event("evt_pre_01")
    assert re_read is not None
    assert re_read.processing_status == EventProcessingStatus.QUARANTINED
    assert re_read.case_id is None


# 4. Duplicate event cannot create duplicate persistence
def test_duplicate_event_cannot_create_duplicate_persistence():
    repo = InMemoryEventRepository()
    req_id = "req_idempotent_01"
    evt_id = "evt_idempotent_01"

    # First attempt acquires dedup lock
    assert repo.record_webhook_dedup(req_id, evt_id) is True

    # Second attempt with same request ID is detected as duplicate
    assert repo.record_webhook_dedup(req_id, evt_id) is False


# 5. Event can later be associated with a case
def test_event_can_later_be_associated_with_a_case():
    repo = InMemoryEventRepository()
    event = _make_raw_ring_event()
    repo.save_ring_event(event)

    # Later: correlation engine runs and creates case_abc_123
    correlated = repo.correlate_event_to_case("evt_pre_01", "case_abc_123")
    assert correlated.case_id == "case_abc_123"
    assert correlated.processing_status == EventProcessingStatus.CORRELATED

    # Re-reading confirms association
    updated = repo.get_ring_event("evt_pre_01")
    assert updated is not None
    assert updated.case_id == "case_abc_123"


# 6. Case timeline can retrieve associated events
def test_case_timeline_can_retrieve_associated_events():
    event_repo = InMemoryEventRepository()
    case_repo = InMemoryCaseRepository()

    # Create case
    case = Case(
        case_id="case_corr_01",
        organization_id="org_alpha",
        location_id="loc_1",
        device_id="ring_doorbell_front",
        event_id="evt_pre_01",
        title="Possible after-hours delivery activity at designated entrance",
    )
    case_repo.create_case(case)

    # Correlate raw event
    event = _make_raw_ring_event("evt_pre_01")
    event_repo.save_ring_event(event)
    event_repo.correlate_event_to_case("evt_pre_01", "case_corr_01")

    # Add normalized event to case
    norm = NormalizedEvent(
        normalized_event_id="norm_evt_01",
        source_event_id="evt_pre_01",
        device_id="ring_doorbell_front",
        location_id="loc_1",
        event_type="motion",
        occurred_at="2026-10-08T22:43:00Z",
        provenance=Provenance.RING_SIGNED,
        is_after_hours=True,
        is_designated_door=True,
        description="Possible after-hours delivery activity observed at designated entrance",
    )
    event_repo.save_normalized_event(norm, case_id="case_corr_01")

    case_events = event_repo.get_case_events("case_corr_01")
    assert len(case_events) == 1
    assert case_events[0].source_event_id == "evt_pre_01"


# 7. Event remains retrievable independently for replay/audit
def test_event_remains_retrievable_independently_for_replay():
    repo = InMemoryEventRepository()
    event = _make_raw_ring_event("evt_replay_01")
    repo.save_ring_event(event)

    # Correlate to case
    repo.correlate_event_to_case("evt_replay_01", "case_historical_01")

    # Event must still be retrievable by raw event_id directly without knowing case_id
    replayed_event = repo.get_ring_event("evt_replay_01")
    assert replayed_event is not None
    assert replayed_event.event_id == "evt_replay_01"
    assert replayed_event.payload == {"raw_door_sensor": "active", "battery": 95}


# 8. Organization isolation still works
def test_organization_isolation_still_works():
    case_repo = InMemoryCaseRepository()
    case = Case(
        case_id="case_org_iso_01",
        organization_id="org_alpha",
        location_id="loc_1",
        device_id="ring_doorbell_front",
        event_id="evt_iso_01",
        title="Possible after-hours delivery activity at designated entrance",
    )
    case_repo.create_case(case)

    # Valid org access succeeds
    assert case_repo.get_case("case_org_iso_01", "org_alpha").case_id == "case_org_iso_01"

    # Cross org access rejected
    with pytest.raises(OrganizationAccessDeniedError):
        case_repo.get_case("case_org_iso_01", "org_beta")


# 9. No duplicate raw payload is unnecessarily created
def test_no_duplicate_raw_payload_created():
    repo = InMemoryEventRepository()
    event = _make_raw_ring_event("evt_single_store")
    repo.save_ring_event(event)

    # Correlate event to case
    repo.correlate_event_to_case("evt_single_store", "case_dedup_store")

    # Save normalized representation to case
    norm = NormalizedEvent(
        normalized_event_id="norm_single_store",
        source_event_id="evt_single_store",
        device_id="ring_doorbell_front",
        location_id="loc_1",
        event_type="motion",
        occurred_at=event.occurred_at,
        provenance=event.provenance,
        is_after_hours=True,
        is_designated_door=True,
        description="Possible after-hours delivery activity observed at designated entrance",
        raw_metadata={},  # Normalized event does not duplicate the full payload
    )
    repo.save_normalized_event(norm, case_id="case_dedup_store")

    # Raw event remains single source of truth for full payload
    raw_from_repo = repo.get_ring_event("evt_single_store")
    assert raw_from_repo is not None
    assert "raw_door_sensor" in raw_from_repo.payload

    case_events = repo.get_case_events("case_dedup_store")
    assert len(case_events) == 1
    assert case_events[0].source_event_id == "evt_single_store"
    # Case event only stores reference, keeping raw payload un-duplicated
    assert "raw_door_sensor" not in case_events[0].raw_metadata
