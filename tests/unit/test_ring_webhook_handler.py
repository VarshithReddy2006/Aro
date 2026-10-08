"""Unit tests for Ring webhook Lambda / API Gateway handler."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from apps.api.src.handlers.ring_webhook import handle_ring_webhook
from apps.api.src.repositories import InMemoryEventRepository
from apps.api.src.services.event_ingestion import EventIngestionService

TEST_SECRET = "test_webhook_handler_secret"


def _make_service() -> EventIngestionService:
    repo = InMemoryEventRepository()
    return EventIngestionService(event_repository=repo, webhook_secret=TEST_SECRET)


def _make_valid_payload():
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "meta": {
            "version": "1.1",
            "time": now_iso,
            "request_id": "req_handler_01",
        },
        "data": {
            "id": "evt_handler_01",
            "type": "event",
            "attributes": {
                "event_type": "motion_detected",
                "device_id": "front_doorbell",
                "timestamp": now_iso,
            },
        },
    }


def test_handler_valid_request():
    service = _make_service()
    payload = _make_valid_payload()
    body_str = json.dumps(payload)
    body_bytes = body_str.encode("utf-8")

    sig = hmac.new(TEST_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()

    event = {
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": f"sha256={sig}",
        },
        "body": body_str,
        "isBase64Encoded": False,
    }

    resp = handle_ring_webhook(event=event, service=service)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "accepted"
    assert body["event_id"] == "evt_handler_01"


def test_handler_base64_encoded_body():
    service = _make_service()
    payload = _make_valid_payload()
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(TEST_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()

    b64_body = base64.b64encode(body_bytes).decode("ascii")

    event = {
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": sig,
        },
        "body": b64_body,
        "isBase64Encoded": True,
    }

    resp = handle_ring_webhook(event=event, service=service)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "accepted"


def test_handler_forged_signature_returns_401():
    service = _make_service()
    payload = _make_valid_payload()
    body_str = json.dumps(payload)

    event = {
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": "sha256=invalid_forged_signature",
        },
        "body": body_str,
        "isBase64Encoded": False,
    }

    resp = handle_ring_webhook(event=event, service=service)
    assert resp["statusCode"] == 401
    body = json.loads(resp["body"])
    assert body["error"] == "UNAUTHORIZED"


def test_handler_oversized_payload_returns_413():
    service = _make_service()
    oversized_body = "x" * 300000  # > 256KB default limit

    event = {
        "headers": {
            "Content-Type": "application/json",
            "X-Signature": "sha256=some_sig",
        },
        "body": oversized_body,
        "isBase64Encoded": False,
    }

    resp = handle_ring_webhook(event=event, service=service)
    assert resp["statusCode"] == 413
    body = json.loads(resp["body"])
    assert body["error"] == "PAYLOAD_TOO_LARGE"


def test_handler_internal_error_sanitized():
    # Pass service that raises unexpected error
    class BrokenService:
        def ingest(self, *args, **kwargs):
            raise RuntimeError(
                "Database connection string postgres://admin:super_secret_password@db"
            )

    event = {
        "headers": {},
        "body": "{}",
        "isBase64Encoded": False,
    }

    resp = handle_ring_webhook(event=event, service=BrokenService())  # type: ignore[arg-type]
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    # Never leak internal secret or traceback!
    assert "super_secret_password" not in resp["body"]
    assert "postgres" not in resp["body"]
