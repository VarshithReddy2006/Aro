"""Comprehensive Security Test Matrix and Adversarial Testing for Ring Ingestion.

Covers:
- T-valid: valid signed Ring event
- T-invalid: invalid schema
- T-forged: invalid HMAC
- T-missing: missing signature
- T-dup: duplicate request/event
- T-replay: replayed/stale event
- T-oversize: payload too large
- T-quarantine: authenticated malformed event
- T-no-write-forged: verify zero persistence for forged event
- T-normalize: correct normalization
- T-hours: correct business-hours classification
- T-correlation: event correctly handed to correlation
- T-tenant: organization isolation
- T-secret: secrets do not appear in logs
Plus adversarial attacks:
- altered body with old signature
- fabricated "package_detected" rejection
- SQL injection / XSS payloads in metadata strings
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.api.src.repositories import (
    InMemoryCaseRepository,
    InMemoryDeviceRepository,
    InMemoryEventRepository,
    InMemoryLocationRepository,
    OrganizationAccessDeniedError,
)
from apps.api.src.services.correlation import DefaultCaseCorrelationService
from apps.api.src.services.event_ingestion import EventIngestionService
from apps.api.src.services.metrics import IngestionMetrics, redact_sensitive_dict
from packages.contracts.enums import CaseStatus, EventProcessingStatus
from packages.contracts.models import Case, Location, RingDevice

TEST_SECRET = "top_secret_ring_hmac_signing_key_456"


def _build_test_pipeline():
    event_repo = InMemoryEventRepository()
    case_repo = InMemoryCaseRepository()
    device_repo = InMemoryDeviceRepository()
    location_repo = InMemoryLocationRepository()
    metrics = IngestionMetrics()

    # Pre-register device & location
    loc = Location(
        location_id="loc_hq",
        organization_id="org_alpha",
        name="Alpha HQ",
        timezone="UTC",
        business_hours_start="08:00",
        business_hours_end="20:00",
        business_days=[0, 1, 2, 3, 4],
    )
    location_repo.save_location(loc)

    device = RingDevice(
        device_id="device_front_01",
        location_id="loc_hq",
        name="Front Entrance",
        kind="doorbell",
        is_designated_door=True,
    )
    device_repo.save_device(device)

    correlation_svc = DefaultCaseCorrelationService(
        event_repository=event_repo,
        case_repository=case_repo,
    )

    service = EventIngestionService(
        event_repository=event_repo,
        webhook_secret=TEST_SECRET,
        device_repository=device_repo,
        location_repository=location_repo,
        correlation_service=correlation_svc,
        metrics=metrics,
        default_location_id="loc_hq",
        default_org_id="org_alpha",
    )

    return {
        "service": service,
        "event_repo": event_repo,
        "case_repo": case_repo,
        "device_repo": device_repo,
        "location_repo": location_repo,
        "metrics": metrics,
    }


def _sign(body: bytes, secret: str = TEST_SECRET) -> dict[str, str]:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Signature": f"sha256={sig}"}


def _make_payload(
    event_id: str = "evt_sec_01",
    request_id: str = "req_sec_01",
    event_type: str = "motion_detected",
    device_id: str = "device_front_01",
    timestamp: str | None = None,
    meta_time: str | None = None,
):
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    event_ts = timestamp or now_iso
    send_time = meta_time or now_iso
    return {
        "meta": {
            "version": "1.1",
            "time": send_time,
            "request_id": request_id,
        },
        "data": {
            "id": event_id,
            "type": "event",
            "attributes": {
                "event_type": event_type,
                "device_id": device_id,
                "timestamp": event_ts,
            },
        },
    }


# T-valid: valid signed Ring event
def test_t_valid_signed_ring_event():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    payload = _make_payload(event_id="evt_valid_10", request_id="req_valid_10")
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 200
    assert res.event_id == "evt_valid_10"
    assert res.processing_status == EventProcessingStatus.VALIDATED

    stored = event_repo.get_ring_event("evt_valid_10")
    assert stored is not None
    assert stored.signature_verified is True
    assert stored.event_type == "motion_detected"


# T-invalid: invalid schema
def test_t_invalid_schema():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    # Invalid JSON syntax
    body = b"not-a-valid-json{"
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 400
    assert res.quarantined is True


# T-forged: invalid HMAC
def test_t_forged_invalid_hmac():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    payload = _make_payload(event_id="evt_forged_99", request_id="req_forged_99")
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-Signature": "sha256=invalid"}

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 401
    assert event_repo.get_ring_event("evt_forged_99") is None


# T-missing: missing signature
def test_t_missing_signature():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    payload = _make_payload(event_id="evt_missing_99", request_id="req_missing_99")
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}  # No X-Signature

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 401
    assert event_repo.get_ring_event("evt_missing_99") is None


# T-dup: duplicate request/event
def test_t_dup_duplicate_request():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    payload = _make_payload(event_id="evt_dup_01", request_id="req_dup_01")
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res1 = service.ingest(raw_body=body, headers=headers)
    assert res1.status_code == 200
    assert res1.duplicate is False

    # Second arrival of same request_id
    res2 = service.ingest(raw_body=body, headers=headers)
    assert res2.status_code == 200
    assert res2.duplicate is True
    assert res2.response_data["status"] == "duplicate"


# T-replay: replayed/stale event
def test_t_replay_stale_event():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    stale_ts = (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = _make_payload(
        event_id="evt_stale_01",
        request_id="req_stale_01",
        timestamp=stale_ts,
        meta_time=stale_ts,
    )
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 400
    assert res.response_data["error"] == "REPLAY_REJECTED"
    assert event_repo.get_ring_event("evt_stale_01") is None


# T-oversize: payload too large
def test_t_oversize_payload():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    oversized_body = b"{" + b"a" * (300 * 1024) + b"}"
    headers = _sign(oversized_body)

    res = service.ingest(raw_body=oversized_body, headers=headers)
    assert res.status_code == 413
    assert res.response_data["error"] == "PAYLOAD_TOO_LARGE"


# T-quarantine: authenticated malformed event
def test_t_quarantine_authenticated_malformed_event():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    # Valid signature, but payload missing event_id and attributes
    broken_payload = {
        "meta": {"request_id": "req_broken_01"},
        "id": "quar_evt_01",
    }
    body = json.dumps(broken_payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 400
    assert res.quarantined is True
    assert res.processing_status == EventProcessingStatus.QUARANTINED

    # Must be persisted as quarantined for audit/investigation
    stored = event_repo.get_ring_event(res.event_id or "quar_evt_01")
    assert stored is not None
    assert stored.processing_status == EventProcessingStatus.QUARANTINED
    assert stored.quarantine_reason is not None


# T-no-write-forged: verify zero persistence for forged event
def test_t_no_write_forged():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    forged_id = "evt_attack_01"
    payload = _make_payload(event_id=forged_id, request_id="req_attack_01")
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-Signature": "sha256=attacker_sig"}

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 401
    # Check that absolutely zero records were stored
    assert event_repo.get_ring_event(forged_id) is None


# T-normalize: correct normalization into NormalizedEvent
def test_t_normalize_correctness():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    # Doorbell ring at front door
    ts = "2026-10-07T22:00:00Z"
    payload = _make_payload(
        event_id="evt_norm_test",
        request_id="req_norm_test",
        event_type="button_press",
        device_id="device_front_01",
        timestamp=ts,
    )
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 200
    norm = res.normalized_event
    assert norm is not None
    assert norm.source_event_id == "evt_norm_test"
    assert norm.device_id == "device_front_01"
    assert norm.is_designated_door is True
    assert norm.is_after_hours is True
    assert norm.description == "Doorbell activity observed at designated entrance"
    # Adheres strictly to Ring terminology
    assert "package" not in norm.description.lower()
    assert "delivery" not in norm.description.lower()


# T-hours: correct business-hours classification
def test_t_hours_classification():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    # Wednesday 15:00 UTC (during 08:00-20:00 business hours)
    open_ts = "2026-10-07T15:00:00Z"
    p_open = _make_payload(event_id="evt_h_open", request_id="req_h_open", timestamp=open_ts)
    b_open = json.dumps(p_open).encode()
    r_open = service.ingest(raw_body=b_open, headers=_sign(b_open))
    assert r_open.normalized_event is not None
    assert r_open.normalized_event.is_after_hours is False

    # Wednesday 22:00 UTC (after closing)
    closed_ts = "2026-10-07T22:00:00Z"
    p_closed = _make_payload(
        event_id="evt_h_closed", request_id="req_h_closed", timestamp=closed_ts
    )
    b_closed = json.dumps(p_closed).encode()
    r_closed = service.ingest(raw_body=b_closed, headers=_sign(b_closed))
    assert r_closed.normalized_event is not None
    assert r_closed.normalized_event.is_after_hours is True


# T-correlation: event correctly handed to correlation
def test_t_correlation_with_existing_active_case():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    case_repo = pipeline["case_repo"]
    event_repo = pipeline["event_repo"]

    # Create an existing active case for this location & device
    existing_case = Case(
        case_id="case_active_01",
        organization_id="org_alpha",
        location_id="loc_hq",
        device_id="device_front_01",
        event_id="evt_prior",
        title="Active Operational Case",
        status=CaseStatus.RECEIVED,
    )
    case_repo.create_case(existing_case)

    payload = _make_payload(
        event_id="evt_correlate_01",
        request_id="req_correlate_01",
        device_id="device_front_01",
    )
    body = json.dumps(payload).encode()
    res = service.ingest(raw_body=body, headers=_sign(body))

    assert res.status_code == 200
    assert res.processing_status == EventProcessingStatus.CORRELATED
    assert res.response_data["correlated"] is True
    assert res.response_data["case_id"] == "case_active_01"

    # Raw event updated with case_id
    raw = event_repo.get_ring_event("evt_correlate_01")
    assert raw is not None
    assert raw.case_id == "case_active_01"
    assert raw.processing_status == EventProcessingStatus.CORRELATED


# T-tenant: organization isolation
def test_t_tenant_isolation():
    pipeline = _build_test_pipeline()
    case_repo = pipeline["case_repo"]

    c = Case(
        case_id="case_tenant_01",
        organization_id="org_alpha",
        location_id="loc_hq",
        device_id="device_front_01",
        event_id="evt_dummy",
        title="Alpha Case",
    )
    case_repo.create_case(c)

    # org_alpha can access
    assert case_repo.get_case("case_tenant_01", organization_id="org_alpha") is not None

    # org_beta cannot access
    with pytest.raises(OrganizationAccessDeniedError):
        case_repo.get_case("case_tenant_01", organization_id="org_beta")


# T-secret: secrets do not appear in logs or data structures
def test_t_secret_redaction():
    raw_data = {
        "webhook_secret": "super_secret_value",
        "nested": {
            "auth_token": "token_abc_123",
            "device_id": "doorbell_1",
        },
        "event_type": "motion_detected",
    }
    redacted = redact_sensitive_dict(raw_data)
    assert redacted["webhook_secret"] == "[REDACTED]"
    assert redacted["nested"]["auth_token"] == "[REDACTED]"
    assert redacted["nested"]["device_id"] == "doorbell_1"
    assert redacted["event_type"] == "motion_detected"


# Adversarial: modified payload with old signature
def test_adversarial_altered_payload_old_signature():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    original_payload = _make_payload(event_id="evt_tamper_01", request_id="req_tamper_01")
    body_original = json.dumps(original_payload).encode()
    valid_headers = _sign(body_original)

    # Attacker alters event_type in the body but keeps the old signature
    tampered_payload = _make_payload(
        event_id="evt_tamper_01",
        request_id="req_tamper_01",
        event_type="doorbell_ring",
    )
    body_tampered = json.dumps(tampered_payload).encode()

    res = service.ingest(raw_body=body_tampered, headers=valid_headers)
    assert res.status_code == 401
    assert event_repo.get_ring_event("evt_tamper_01") is None


# Adversarial: prohibited fabricated event types (e.g. "package_detected")
def test_adversarial_prohibited_package_detected_event():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]

    # Ring does not have package detection; claiming it must trigger quarantine
    payload = _make_payload(
        event_id="evt_fake_pkg",
        request_id="req_fake_pkg",
        event_type="package_detected",
    )
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 400
    assert res.quarantined is True
    assert "PROHIBITED_EVENT_TYPE" in str(res.response_data.get("error"))


# Adversarial: malicious strings / injection attempts in metadata
def test_adversarial_malicious_strings():
    pipeline = _build_test_pipeline()
    service = pipeline["service"]
    event_repo = pipeline["event_repo"]

    payload = _make_payload(
        event_id="evt_inj_01",
        request_id="req_inj_01",
    )
    payload["meta"]["notes"] = "'; DROP TABLE events; -- <script>alert(1)</script>"
    body = json.dumps(payload).encode()
    headers = _sign(body)

    res = service.ingest(raw_body=body, headers=headers)
    assert res.status_code == 200
    stored = event_repo.get_ring_event("evt_inj_01")
    assert stored is not None
    # Payload is cleanly preserved without evaluating or crashing
    assert stored.payload["meta"]["notes"] == "'; DROP TABLE events; -- <script>alert(1)</script>"
