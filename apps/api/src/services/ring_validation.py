"""Ring webhook payload schema validation service.

Enforces:
- Maximum payload byte size (configurable, default 256 KB).
- Safe JSON parsing from raw bytes.
- Verification of canonical Ring Partner API v1.1 and synthetic test schemas.
- Rejection of fabricated events (e.g. "package_detected").
- Quarantine classification for authenticated malformed payloads.
"""

import json
from dataclasses import dataclass
from typing import Any

# Permitted verified Ring activity types
VERIFIED_RING_EVENT_TYPES: set[str] = {
    "motion_detected",
    "motion",
    "button_press",
    "doorbell_ring",
    "device_online",
    "device_offline",
}

# Explicitly prohibited fabricated event types
PROHIBITED_FABRICATED_TYPES: set[str] = {
    "package_detected",
    "package_delivered",
    "delivery_detected",
    "delivery_confirmed",
}


@dataclass(frozen=True)
class ParsedRingPayload:
    """Normalized structured data extracted from a validated Ring payload."""

    event_id: str
    request_id: str
    device_id: str
    event_type: str
    occurred_at: str
    replay_timestamp: str
    raw_dict: dict[str, Any]
    account_id: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of payload validation check."""

    is_valid: bool
    parsed_payload: ParsedRingPayload | None = None
    error_code: str | None = None
    error_message: str | None = None
    status_code: int = 200
    is_malformed: bool = False
    raw_dict: dict[str, Any] | None = None


class RingPayloadValidator:
    """Deterministic payload size and schema validator for Ring webhooks."""

    def __init__(self, max_payload_bytes: int = 262144) -> None:
        """Initialize validator with size limit (default 256KB)."""
        self.max_payload_bytes = max_payload_bytes

    def validate_size(self, raw_bytes: bytes) -> ValidationResult | None:
        """Check if payload size exceeds configured threshold.

        Returns ValidationResult if oversized, else None.
        """
        if len(raw_bytes) > self.max_payload_bytes:
            return ValidationResult(
                is_valid=False,
                error_code="PAYLOAD_TOO_LARGE",
                error_message=(
                    f"Payload size {len(raw_bytes)} bytes exceeds limit "
                    f"of {self.max_payload_bytes} bytes"
                ),
                status_code=413,
            )
        return None

    def validate_and_parse(self, raw_bytes: bytes) -> ValidationResult:
        """Validate raw bytes size, parse JSON, and validate against Ring schema.

        Args:
            raw_bytes: Raw HTTP request bytes.

        Returns:
            ValidationResult containing parsed payload or error diagnostics.
        """
        size_err = self.validate_size(raw_bytes)
        if size_err is not None:
            return size_err

        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ValidationResult(
                is_valid=False,
                error_code="INVALID_JSON",
                error_message=f"Could not parse JSON payload: {exc}",
                status_code=400,
                is_malformed=True,
            )

        if not isinstance(data, dict):
            return ValidationResult(
                is_valid=False,
                error_code="INVALID_ROOT_OBJECT",
                error_message="Webhook payload root must be a JSON object",
                status_code=400,
                is_malformed=True,
            )

        # Check for Ring Partner API v1.1 structure:
        # { "meta": { "version": "1.1", "time": "...", "request_id": "..." }, "data": { "id": "...", "attributes": { ... } } }
        if "data" in data and isinstance(data["data"], dict):
            return self._parse_partner_api_v1(data)

        # Check for standard / test flat payload structure:
        return self._parse_flat_payload(data)

    def _parse_partner_api_v1(self, data: dict[str, Any]) -> ValidationResult:
        """Parse Ring Partner API v1.1 schema."""
        meta = data.get("meta", {})
        data_block = data.get("data", {})
        attributes = data_block.get("attributes", {})

        if not isinstance(meta, dict) or not isinstance(attributes, dict):
            return ValidationResult(
                is_valid=False,
                error_code="MALFORMED_STRUCTURE",
                error_message="meta and data.attributes must be JSON objects",
                status_code=400,
                is_malformed=True,
                raw_dict=data,
            )

        request_id = meta.get("request_id")
        replay_time = meta.get("time")
        account_id = meta.get("account_id")

        event_id = data_block.get("id")
        event_type = attributes.get("event_type")
        device_id = attributes.get("device_id")
        occurred_at = attributes.get("timestamp") or replay_time

        missing: list[str] = []
        if not request_id:
            missing.append("meta.request_id")
        if not event_id:
            missing.append("data.id")
        if not device_id:
            missing.append("data.attributes.device_id")
        if not event_type:
            missing.append("data.attributes.event_type")
        if not occurred_at:
            missing.append("data.attributes.timestamp")

        if missing:
            return ValidationResult(
                is_valid=False,
                error_code="MISSING_REQUIRED_FIELDS",
                error_message=f"Missing required fields: {', '.join(missing)}",
                status_code=400,
                is_malformed=True,
                raw_dict=data,
            )

        # Validate event type
        type_str = str(event_type).lower().strip()
        if type_str in PROHIBITED_FABRICATED_TYPES:
            return ValidationResult(
                is_valid=False,
                error_code="PROHIBITED_EVENT_TYPE",
                error_message=(
                    f"Fabricated event type '{event_type}' is not supported by Ring. "
                    "Ring only provides physical motion and doorbell activity."
                ),
                status_code=400,
                is_malformed=True,
                raw_dict=data,
            )

        parsed = ParsedRingPayload(
            event_id=str(event_id),
            request_id=str(request_id),
            device_id=str(device_id),
            event_type=type_str,
            occurred_at=str(occurred_at),
            replay_timestamp=str(replay_time or occurred_at),
            raw_dict=data,
            account_id=str(account_id) if account_id else None,
        )
        return ValidationResult(is_valid=True, parsed_payload=parsed, raw_dict=data)

    def _parse_flat_payload(self, data: dict[str, Any]) -> ValidationResult:
        """Parse flat schema used by test harnesses and synthetic fixtures."""
        event_id = data.get("event_id")
        request_id = data.get("request_id")
        device_id = data.get("device_id")
        event_type = data.get("event_type")
        occurred_at = data.get("occurred_at")

        missing: list[str] = []
        if not event_id:
            missing.append("event_id")
        if not request_id:
            missing.append("request_id")
        if not device_id:
            missing.append("device_id")
        if not event_type:
            missing.append("event_type")
        if not occurred_at:
            missing.append("occurred_at")

        if missing:
            return ValidationResult(
                is_valid=False,
                error_code="MISSING_REQUIRED_FIELDS",
                error_message=f"Missing required fields: {', '.join(missing)}",
                status_code=400,
                is_malformed=True,
                raw_dict=data,
            )

        type_str = str(event_type).lower().strip()
        if type_str in PROHIBITED_FABRICATED_TYPES:
            return ValidationResult(
                is_valid=False,
                error_code="PROHIBITED_EVENT_TYPE",
                error_message=(
                    f"Fabricated event type '{event_type}' is not supported by Ring. "
                    "Ring only provides physical motion and doorbell activity."
                ),
                status_code=400,
                is_malformed=True,
                raw_dict=data,
            )

        parsed = ParsedRingPayload(
            event_id=str(event_id),
            request_id=str(request_id),
            device_id=str(device_id),
            event_type=type_str,
            occurred_at=str(occurred_at),
            replay_timestamp=str(occurred_at),
            raw_dict=data,
        )
        return ValidationResult(is_valid=True, parsed_payload=parsed, raw_dict=data)
