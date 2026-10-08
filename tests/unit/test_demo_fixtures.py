"""Unit tests for DEMO ingestion fixtures."""

from apps.api.src.repositories import InMemoryEventRepository
from apps.api.src.services.demo_fixtures import DEMO_WEBHOOK_SECRET, get_demo_fixtures
from apps.api.src.services.event_ingestion import EventIngestionService
from packages.contracts.enums import Provenance


def test_all_demo_fixtures_deterministic():
    fixtures = get_demo_fixtures()
    assert len(fixtures) == 7

    required_names = {
        "valid_motion_event",
        "duplicate_event",
        "forged_signature_event",
        "authenticated_malformed_payload",
        "stale_replay_event",
        "after_hours_event",
        "normal_hours_event",
    }
    assert set(fixtures.keys()) == required_names

    for fix in fixtures.values():
        assert fix.provenance == Provenance.DEMO_SYNTHETIC.value
        assert isinstance(fix.raw_body, bytes)
        assert "Content-Type" in fix.headers


def test_demo_pipeline_execution():
    repo = InMemoryEventRepository()
    service = EventIngestionService(
        event_repository=repo,
        webhook_secret=DEMO_WEBHOOK_SECRET,
    )
    fixtures = get_demo_fixtures()

    # 1. Valid motion event
    f1 = fixtures["valid_motion_event"]
    r1 = service.ingest(raw_body=f1.raw_body, headers=f1.headers)
    assert r1.status_code == 200
    assert r1.event_id == "demo_evt_valid_01"

    # 2. Duplicate event (same request_id as 1)
    f2 = fixtures["duplicate_event"]
    r2 = service.ingest(raw_body=f2.raw_body, headers=f2.headers)
    assert r2.status_code == 200
    assert r2.duplicate is True

    # 3. Forged signature
    f3 = fixtures["forged_signature_event"]
    r3 = service.ingest(raw_body=f3.raw_body, headers=f3.headers)
    assert r3.status_code == 401
    assert repo.get_ring_event("demo_evt_forged_01") is None

    # 4. Authenticated malformed payload
    f4 = fixtures["authenticated_malformed_payload"]
    r4 = service.ingest(raw_body=f4.raw_body, headers=f4.headers)
    assert r4.status_code == 400
    assert r4.quarantined is True

    # 5. Stale replay event
    f5 = fixtures["stale_replay_event"]
    r5 = service.ingest(raw_body=f5.raw_body, headers=f5.headers)
    assert r5.status_code == 400
    assert "REPLAY_REJECTED" in str(r5.response_data.get("error"))

    # 6. After-hours event
    f6 = fixtures["after_hours_event"]
    r6 = service.ingest(raw_body=f6.raw_body, headers=f6.headers)
    assert r6.status_code == 200
    assert r6.normalized_event is not None
    assert r6.normalized_event.is_after_hours is True

    # 7. Normal-hours event
    f7 = fixtures["normal_hours_event"]
    r7 = service.ingest(raw_body=f7.raw_body, headers=f7.headers)
    assert r7.status_code == 200
    assert r7.normalized_event is not None
    assert r7.normalized_event.is_after_hours is False
