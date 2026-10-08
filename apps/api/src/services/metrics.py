"""Observability, metrics, and secret-redacting logging for Ring ingestion."""

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger("aro.ring_ingest")

SENSITIVE_KEYS: set[str] = {
    "secret",
    "webhook_secret",
    "signature_secret",
    "token",
    "auth_token",
    "authorization",
    "password",
    "api_key",
    "credentials",
    "x-signature",
    "x_signature",
}


def redact_sensitive_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact values for sensitive keys in dictionaries."""
    sanitized: dict[str, Any] = {}
    for k, v in data.items():
        k_lower = str(k).lower().replace("-", "_")
        if any(secret_part in k_lower for secret_part in SENSITIVE_KEYS):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = redact_sensitive_dict(v)
        elif isinstance(v, list):
            sanitized[k] = [
                redact_sensitive_dict(item) if isinstance(item, dict) else item for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


@dataclass
class IngestionMetrics:
    """Thread-safe metrics counter for Ring webhook ingestion."""

    _lock: Lock = field(default_factory=Lock)
    ring_events_received: int = 0
    ring_events_rejected: int = 0
    ring_events_forged: int = 0
    ring_events_duplicate: int = 0
    ring_events_quarantined: int = 0
    ring_events_validated: int = 0
    ring_events_correlated: int = 0
    ring_webhook_errors: int = 0
    _latencies_ms: list[float] = field(default_factory=list)

    def inc_received(self) -> None:
        with self._lock:
            self.ring_events_received += 1

    def inc_rejected(self) -> None:
        with self._lock:
            self.ring_events_rejected += 1

    def inc_forged(self) -> None:
        with self._lock:
            self.ring_events_forged += 1

    def inc_duplicate(self) -> None:
        with self._lock:
            self.ring_events_duplicate += 1

    def inc_quarantined(self) -> None:
        with self._lock:
            self.ring_events_quarantined += 1

    def inc_validated(self) -> None:
        with self._lock:
            self.ring_events_validated += 1

    def inc_correlated(self) -> None:
        with self._lock:
            self.ring_events_correlated += 1

    def inc_error(self) -> None:
        with self._lock:
            self.ring_webhook_errors += 1

    def record_latency_ms(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies_ms.append(latency_ms)

    @property
    def average_latency_ms(self) -> float:
        with self._lock:
            if not self._latencies_ms:
                return 0.0
            return sum(self._latencies_ms) / len(self._latencies_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ring_events_received": self.ring_events_received,
                "ring_events_rejected": self.ring_events_rejected,
                "ring_events_forged": self.ring_events_forged,
                "ring_events_duplicate": self.ring_events_duplicate,
                "ring_events_quarantined": self.ring_events_quarantined,
                "ring_events_validated": self.ring_events_validated,
                "ring_events_correlated": self.ring_events_correlated,
                "ring_webhook_errors": self.ring_webhook_errors,
                "average_latency_ms": self.average_latency_ms,
                "total_requests": len(self._latencies_ms),
            }

    def reset(self) -> None:
        with self._lock:
            self.ring_events_received = 0
            self.ring_events_rejected = 0
            self.ring_events_forged = 0
            self.ring_events_duplicate = 0
            self.ring_events_quarantined = 0
            self.ring_events_validated = 0
            self.ring_events_correlated = 0
            self.ring_webhook_errors = 0
            self._latencies_ms.clear()
