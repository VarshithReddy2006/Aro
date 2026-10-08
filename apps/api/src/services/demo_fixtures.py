"""Deterministic DEMO fixtures for Ring webhook ingestion testing and dry-runs.

Provides synthetic test vectors covering all required operational and adversarial scenarios:
1. valid_motion_event: Valid motion event at designated door outside business hours.
2. duplicate_event: Identical request_id/event_id to prove atomic deduplication.
3. forged_signature_event: Altered payload with mismatching HMAC to prove zero-write rejection.
4. authenticated_malformed_payload: Valid HMAC signature but malformed JSON/schema to prove quarantine.
5. stale_replay_event: Valid signature but stale timestamp outside freshness window.
6. after_hours_event: Verified event occurring during after-hours window (e.g. 22:30).
7. normal_hours_event: Verified event occurring during normal business hours (e.g. 14:00).

All synthetic events are explicitly and immutably tagged:
provenance = demo_synthetic
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from packages.contracts.enums import Provenance

DEMO_WEBHOOK_SECRET = "demo_ring_webhook_secret_for_testing_only"


@dataclass(frozen=True)
class DemoFixture:
    """Self-contained demo webhook payload fixture."""

    name: str
    description: str
    raw_body: bytes
    headers: dict[str, str]
    expected_status_code: int
    expected_processing_status: str
    provenance: str = Provenance.DEMO_SYNTHETIC.value


def create_signed_headers(
    raw_body: bytes,
    secret: str = DEMO_WEBHOOK_SECRET,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Generate canonical headers with computed HMAC-SHA256 signature."""
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": f"sha256={sig}",
    }
    if timestamp:
        headers["X-Signature-Timestamp"] = timestamp
    return headers


def get_demo_fixtures(secret: str = DEMO_WEBHOOK_SECRET) -> dict[str, DemoFixture]:
    """Generate all 7 deterministic demo fixtures."""
    now_utc = datetime.now(UTC)
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_iso = (now_utc - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    fixtures: dict[str, DemoFixture] = {}

    # 1. Valid motion/doorbell event (after-hours at front door)
    body_1 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": now_iso,
                "request_id": "demo_req_valid_01",
                "account_id": "demo_acc_01",
            },
            "data": {
                "id": "demo_evt_valid_01",
                "type": "event",
                "attributes": {
                    "event_type": "motion_detected",
                    "device_id": "ring_doorbell_front",
                    "timestamp": now_iso,
                },
            },
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    fixtures["valid_motion_event"] = DemoFixture(
        name="valid_motion_event",
        description="Valid motion activity at designated front door",
        raw_body=body_1,
        headers=create_signed_headers(body_1, secret=secret, timestamp=now_iso),
        expected_status_code=200,
        expected_processing_status="VALIDATED",
    )

    # 2. Duplicate event (same request_id as fixture 1)
    fixtures["duplicate_event"] = DemoFixture(
        name="duplicate_event",
        description="Duplicate event with same request_id to verify idempotent acknowledgment",
        raw_body=body_1,
        headers=create_signed_headers(body_1, secret=secret, timestamp=now_iso),
        expected_status_code=200,
        expected_processing_status="duplicate",
    )

    # 3. Forged signature event (invalid HMAC)
    body_3 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": now_iso,
                "request_id": "demo_req_forged_01",
            },
            "data": {
                "id": "demo_evt_forged_01",
                "type": "event",
                "attributes": {
                    "event_type": "motion_detected",
                    "device_id": "ring_doorbell_front",
                    "timestamp": now_iso,
                },
            },
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    forged_headers = {
        "Content-Type": "application/json",
        "X-Signature": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
    }
    fixtures["forged_signature_event"] = DemoFixture(
        name="forged_signature_event",
        description="Forged signature rejected with zero DB writes",
        raw_body=body_3,
        headers=forged_headers,
        expected_status_code=401,
        expected_processing_status="UNAUTHORIZED",
    )

    # 4. Authenticated malformed payload (valid HMAC, but broken schema)
    body_4 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": now_iso,
                "request_id": "demo_req_malformed_01",
            },
            # Missing data block completely
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    fixtures["authenticated_malformed_payload"] = DemoFixture(
        name="authenticated_malformed_payload",
        description="Authenticated with valid HMAC but missing required schema fields to prove quarantine",
        raw_body=body_4,
        headers=create_signed_headers(body_4, secret=secret, timestamp=now_iso),
        expected_status_code=400,
        expected_processing_status="QUARANTINED",
    )

    # 5. Stale / replayed event (timestamp 2 hours ago)
    body_5 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": stale_iso,
                "request_id": "demo_req_stale_01",
            },
            "data": {
                "id": "demo_evt_stale_01",
                "type": "event",
                "attributes": {
                    "event_type": "motion_detected",
                    "device_id": "ring_doorbell_front",
                    "timestamp": stale_iso,
                },
            },
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    fixtures["stale_replay_event"] = DemoFixture(
        name="stale_replay_event",
        description="Event outside 5-minute freshness window rejected as replay",
        raw_body=body_5,
        headers=create_signed_headers(body_5, secret=secret, timestamp=stale_iso),
        expected_status_code=400,
        expected_processing_status="REPLAY_REJECTED",
    )

    # 6. After-hours event (22:30 UTC on Wednesday)
    # Using specific Wednesday 2026-10-07T22:30:00Z (after 20:00 close)
    after_hours_ts = "2026-10-07T22:30:00Z"
    body_6 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": now_iso,
                "request_id": "demo_req_after_hours_01",
            },
            "data": {
                "id": "demo_evt_after_hours_01",
                "type": "event",
                "attributes": {
                    "event_type": "button_press",
                    "device_id": "ring_doorbell_front",
                    "timestamp": after_hours_ts,
                },
            },
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    fixtures["after_hours_event"] = DemoFixture(
        name="after_hours_event",
        description="Valid doorbell activity at 22:30 (classified as is_after_hours=True)",
        raw_body=body_6,
        headers=create_signed_headers(body_6, secret=secret, timestamp=now_iso),
        expected_status_code=200,
        expected_processing_status="VALIDATED",
    )

    # 7. Normal-hours event (14:00 UTC on Wednesday)
    normal_hours_ts = "2026-10-07T14:00:00Z"
    body_7 = json.dumps(
        {
            "meta": {
                "version": "1.1",
                "time": now_iso,
                "request_id": "demo_req_normal_hours_01",
            },
            "data": {
                "id": "demo_evt_normal_hours_01",
                "type": "event",
                "attributes": {
                    "event_type": "motion_detected",
                    "device_id": "ring_doorbell_front",
                    "timestamp": normal_hours_ts,
                },
            },
            "provenance": Provenance.DEMO_SYNTHETIC.value,
        }
    ).encode("utf-8")
    fixtures["normal_hours_event"] = DemoFixture(
        name="normal_hours_event",
        description="Valid motion activity at 14:00 (classified as is_after_hours=False)",
        raw_body=body_7,
        headers=create_signed_headers(body_7, secret=secret, timestamp=now_iso),
        expected_status_code=200,
        expected_processing_status="VALIDATED",
    )

    return fixtures
