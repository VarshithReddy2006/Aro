"""Replay protection service for Ring webhooks.

Enforces timestamp freshness windows using Ring protocol fields:
- In Ring Partner API v1.1, the webhook payload contains `meta.time` (ISO 8601 UTC).
- Optional HTTP headers like `X-Signature-Timestamp` or `X-Ring-Timestamp` can also be evaluated.
- Rejects stale events older than the freshness window.
- Rejects events with timestamps significantly in the future (skew tolerance).
"""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ReplayCheckResult:
    """Result of a webhook freshness / replay evaluation."""

    is_fresh: bool
    age_seconds: float = 0.0
    reason: str | None = None
    event_time: datetime | None = None


class ReplayProtectionService:
    """Deterministic timestamp freshness verifier for replay mitigation."""

    def __init__(
        self,
        freshness_window_seconds: int = 300,
        future_skew_tolerance_seconds: int = 60,
    ) -> None:
        """Initialize replay protection settings.

        Args:
            freshness_window_seconds: Max acceptable age of webhook (default 300s = 5m).
            future_skew_tolerance_seconds: Max acceptable clock drift into future (default 60s).
        """
        self.freshness_window_seconds = freshness_window_seconds
        self.future_skew_tolerance_seconds = future_skew_tolerance_seconds

    def check_freshness(
        self,
        timestamp_str: str | None,
        now: datetime | None = None,
    ) -> ReplayCheckResult:
        """Verify that a timestamp falls within the acceptable freshness window.

        Args:
            timestamp_str: ISO 8601 timestamp string from payload (meta.time) or header.
            now: Current reference time (defaults to UTC now).

        Returns:
            ReplayCheckResult with freshness status and computed age.
        """
        if not timestamp_str or not timestamp_str.strip():
            return ReplayCheckResult(
                is_fresh=False,
                reason="Missing timestamp for replay verification",
            )

        now_utc = now if now is not None else datetime.now(UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        try:
            # Parse ISO 8601 (handles Z and +00:00)
            cleaned_ts = timestamp_str.strip().replace("Z", "+00:00")
            parsed_dt = datetime.fromisoformat(cleaned_ts)
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=UTC)
            else:
                parsed_dt = parsed_dt.astimezone(UTC)
        except (ValueError, TypeError) as exc:
            return ReplayCheckResult(
                is_fresh=False,
                reason=f"Malformed timestamp format: {exc}",
            )

        age = (now_utc - parsed_dt).total_seconds()

        # Check future skew
        if age < -self.future_skew_tolerance_seconds:
            return ReplayCheckResult(
                is_fresh=False,
                age_seconds=age,
                reason=f"Timestamp is in the future by {-age:.1f}s (tolerance: {self.future_skew_tolerance_seconds}s)",
                event_time=parsed_dt,
            )

        # Check stale
        if age > self.freshness_window_seconds:
            return ReplayCheckResult(
                is_fresh=False,
                age_seconds=age,
                reason=f"Request is stale by {age:.1f}s (freshness window: {self.freshness_window_seconds}s)",
                event_time=parsed_dt,
            )

        return ReplayCheckResult(
            is_fresh=True,
            age_seconds=age,
            event_time=parsed_dt,
        )
