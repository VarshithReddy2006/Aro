"""Event ingestion pipeline service for Ring webhooks.

Orchestrates the complete external trust boundary:
1. Payload size check (HTTP 413)
2. HMAC-SHA256 signature verification (HTTP 401; zero DB writes on forgery)
3. Schema validation and parsing (HTTP 400; quarantined if signed but malformed)
4. Replay protection check (HTTP 400; reject stale or future requests)
5. Atomic deduplication (HTTP 200 idempotent acknowledgment on duplicate)
6. Raw event persistence (status = RECEIVED)
7. Normalization (status = VALIDATED)
8. Case correlation handoff (status = CORRELATED if matched to active case)
9. Observability and secret-redacted structured logging
"""

import time
from dataclasses import dataclass
from typing import Any

from packages.contracts.enums import EventProcessingStatus, Provenance
from packages.contracts.models import (
    Location,
    NormalizedEvent,
    RingDevice,
    RingEvent,
)

from ..repositories.interfaces import (
    DeviceRepository,
    EventRepository,
    LocationRepository,
)
from .correlation import CaseCorrelationServiceProtocol, DefaultCaseCorrelationService
from .metrics import IngestionMetrics, logger, redact_sensitive_dict
from .replay_protection import ReplayProtectionService
from .ring_normalizer import RingNormalizer
from .ring_signature import RingSignatureVerifier
from .ring_validation import RingPayloadValidator


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of webhook ingestion processing."""

    status_code: int
    response_data: dict[str, Any]
    event_id: str | None = None
    request_id: str | None = None
    processing_status: EventProcessingStatus | None = None
    raw_event: RingEvent | None = None
    normalized_event: NormalizedEvent | None = None
    quarantined: bool = False
    duplicate: bool = False


class EventIngestionService:
    """Production-grade ingestion pipeline for incoming Ring webhook requests."""

    def __init__(
        self,
        event_repository: EventRepository,
        webhook_secret: str,
        signature_verifier: RingSignatureVerifier | None = None,
        payload_validator: RingPayloadValidator | None = None,
        replay_protection: ReplayProtectionService | None = None,
        normalizer: RingNormalizer | None = None,
        correlation_service: CaseCorrelationServiceProtocol | None = None,
        device_repository: DeviceRepository | None = None,
        location_repository: LocationRepository | None = None,
        metrics: IngestionMetrics | None = None,
        default_location_id: str = "loc_hq",
        default_org_id: str = "org_default",
    ) -> None:
        self.event_repo = event_repository
        self.webhook_secret = webhook_secret
        self.signature_verifier = signature_verifier or RingSignatureVerifier()
        self.payload_validator = payload_validator or RingPayloadValidator()
        self.replay_protection = replay_protection or ReplayProtectionService()
        self.normalizer = normalizer or RingNormalizer()
        self.correlation_service = correlation_service or DefaultCaseCorrelationService(
            event_repository
        )
        self.device_repo = device_repository
        self.location_repo = location_repository
        self.metrics = metrics or IngestionMetrics()
        self.default_location_id = default_location_id
        self.default_org_id = default_org_id

    def ingest(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        client_ip: str | None = None,
    ) -> IngestionResult:
        """Process incoming webhook request through all trust boundary stages.

        Args:
            raw_body: Exact raw wire bytes of the HTTP request body.
            headers: Incoming HTTP headers (case-insensitive lookup performed).
            client_ip: Optional client IP address for audit logging.

        Returns:
            IngestionResult with status code, response data, and event details.
        """
        start_time = time.perf_counter()

        # Normalize header keys to lowercase
        norm_headers = {k.lower(): v for k, v in headers.items()}

        # Stage 1: Enforce payload size limit
        size_err = self.payload_validator.validate_size(raw_body)
        if size_err is not None:
            self.metrics.inc_rejected()
            self.metrics.inc_error()
            self._record_latency(start_time)
            logger.warning("Rejected oversized Ring webhook payload: %d bytes", len(raw_body))
            return IngestionResult(
                status_code=413,
                response_data={
                    "error": "PAYLOAD_TOO_LARGE",
                    "message": size_err.error_message,
                },
            )

        # Stage 2: HMAC-SHA256 signature verification
        # Header lookup handles "x-signature", "x-hub-signature", "signature"
        sig_header = (
            norm_headers.get("x-signature")
            or norm_headers.get("x-hub-signature")
            or norm_headers.get("signature")
        )

        sig_result = self.signature_verifier.verify(
            raw_body=raw_body,
            signature_header=sig_header,
            secret=self.webhook_secret,
        )

        if not sig_result.is_valid:
            # FORGED OR MISSING SIGNATURE: REJECT IMMEDIATELY.
            # ZERO DATABASE WRITES OCCUR HERE.
            self.metrics.inc_forged()
            self.metrics.inc_rejected()
            self._record_latency(start_time)
            logger.warning(
                "Rejected Ring webhook with invalid signature. Reason: %s",
                sig_result.reason,
            )
            return IngestionResult(
                status_code=401,
                response_data={
                    "error": "UNAUTHORIZED",
                    "message": sig_result.reason or "Invalid HMAC signature",
                },
            )

        # Stage 3: Schema validation and JSON parsing
        val_result = self.payload_validator.validate_and_parse(raw_body)

        # If authenticated but malformed: QUARANTINE using Phase 2.1 lifecycle
        if not val_result.is_valid or val_result.parsed_payload is None:
            self.metrics.inc_quarantined()
            self._record_latency(start_time)

            # Generate synthetic quarantine event identifier
            raw_data = val_result.raw_dict or {}
            event_id = str(
                raw_data.get("event_id") or raw_data.get("id") or f"quar_{int(time.time() * 1000)}"
            )
            request_id = str(raw_data.get("request_id") or f"req_quar_{int(time.time() * 1000)}")
            device_id = str(raw_data.get("device_id") or "unknown_device")

            quarantined_event = RingEvent(
                event_id=event_id,
                request_id=request_id,
                device_id=device_id,
                event_type="malformed",
                occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                provenance=Provenance.RING_SIGNED,
                payload=redact_sensitive_dict(raw_data),
                signature_verified=True,
                processing_status=EventProcessingStatus.QUARANTINED,
                quarantine_reason=val_result.error_message or "Malformed payload structure",
            )
            # Persist quarantined event
            self.event_repo.save_ring_event(quarantined_event)

            logger.warning(
                "Quarantined authenticated malformed Ring event: event_id=%s, reason=%s",
                event_id,
                val_result.error_message,
            )
            return IngestionResult(
                status_code=400,
                response_data={
                    "status": "quarantined",
                    "event_id": event_id,
                    "error": val_result.error_code or "MALFORMED_PAYLOAD",
                    "message": val_result.error_message,
                },
                event_id=event_id,
                request_id=request_id,
                processing_status=EventProcessingStatus.QUARANTINED,
                quarantined=True,
            )

        parsed = val_result.parsed_payload

        # Stage 4: Replay protection check
        # Check against meta.time, header timestamp, or parsed occurred_at
        replay_ts = norm_headers.get("x-signature-timestamp") or parsed.replay_timestamp
        replay_result = self.replay_protection.check_freshness(replay_ts)
        if not replay_result.is_fresh:
            self.metrics.inc_rejected()
            self._record_latency(start_time)
            logger.warning(
                "Rejected replayed or stale Ring event: request_id=%s, reason=%s",
                parsed.request_id,
                replay_result.reason,
            )
            return IngestionResult(
                status_code=400,
                response_data={
                    "error": "REPLAY_REJECTED",
                    "message": replay_result.reason or "Request is stale or outside replay window",
                },
                request_id=parsed.request_id,
            )

        # Stage 5: Deduplication check
        is_new = self.event_repo.record_webhook_dedup(
            request_id=parsed.request_id,
            event_id=parsed.event_id,
        )
        if not is_new:
            # Duplicate request received: idempotent HTTP 200 acknowledgment
            self.metrics.inc_duplicate()
            self._record_latency(start_time)
            logger.info(
                "Duplicate Ring webhook request acknowledged idempotently: request_id=%s, event_id=%s",
                parsed.request_id,
                parsed.event_id,
            )
            return IngestionResult(
                status_code=200,
                response_data={
                    "status": "duplicate",
                    "message": "Duplicate event already processed",
                    "request_id": parsed.request_id,
                    "event_id": parsed.event_id,
                },
                event_id=parsed.event_id,
                request_id=parsed.request_id,
                duplicate=True,
            )

        # Stage 6: Raw Event Persistence (Pre-Case Partition)
        # Determine provenance
        is_demo = (
            parsed.raw_dict.get("provenance") == "demo_synthetic"
            or parsed.raw_dict.get("provenance") == Provenance.DEMO_SYNTHETIC
        )
        provenance = Provenance.DEMO_SYNTHETIC if is_demo else Provenance.RING_SIGNED

        raw_event = RingEvent(
            event_id=parsed.event_id,
            request_id=parsed.request_id,
            device_id=parsed.device_id,
            event_type=parsed.event_type,
            occurred_at=parsed.occurred_at,
            provenance=provenance,
            payload=redact_sensitive_dict(parsed.raw_dict),
            signature_verified=True,
            processing_status=EventProcessingStatus.RECEIVED,
        )
        saved_raw = self.event_repo.save_ring_event(raw_event)
        self.metrics.inc_received()

        # Stage 7: Event Normalization
        # Resolve device and location context
        device: RingDevice | None = None
        if self.device_repo is not None:
            device = self.device_repo.get_device(parsed.device_id)

        location: Location | None = None
        location_id = device.location_id if device else self.default_location_id
        if self.location_repo is not None:
            location = self.location_repo.get_location(location_id)

        if location is None:
            # Fallback default location if not explicitly stored
            location = Location(
                location_id=location_id,
                organization_id=self.default_org_id,
                name="Main Facility",
                timezone="UTC",
                business_hours_start="08:00",
                business_hours_end="20:00",
                business_days=[0, 1, 2, 3, 4],
            )

        normalized_event = self.normalizer.normalize(
            event=saved_raw,
            location=location,
            device=device,
        )
        self.metrics.inc_validated()

        # Stage 8: Case Correlation Handoff
        correlation_outcome = self.correlation_service.correlate(
            event=saved_raw,
            normalized_event=normalized_event,
            organization_id=location.organization_id,
        )

        final_status = (
            EventProcessingStatus.CORRELATED
            if correlation_outcome.correlated
            else EventProcessingStatus.VALIDATED
        )
        if correlation_outcome.correlated:
            self.metrics.inc_correlated()

        self._record_latency(start_time)
        logger.info(
            "Ring webhook successfully ingested: event_id=%s, request_id=%s, correlated=%s, latency_ms=%.2f",
            parsed.event_id,
            parsed.request_id,
            correlation_outcome.correlated,
            (time.perf_counter() - start_time) * 1000,
        )

        return IngestionResult(
            status_code=200,
            response_data={
                "status": "accepted",
                "event_id": parsed.event_id,
                "request_id": parsed.request_id,
                "processing_status": final_status.value,
                "correlated": correlation_outcome.correlated,
                "case_id": correlation_outcome.case_id,
            },
            event_id=parsed.event_id,
            request_id=parsed.request_id,
            processing_status=final_status,
            raw_event=saved_raw,
            normalized_event=normalized_event,
        )

    def _record_latency(self, start_time: float) -> None:
        latency_ms = (time.perf_counter() - start_time) * 1000
        self.metrics.record_latency_ms(latency_ms)
