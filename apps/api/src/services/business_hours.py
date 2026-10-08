"""Deterministic business hours evaluation service.

Evaluates whether an observed physical event occurred after-hours:
- Purely deterministic rules: timezone, business days, opening, and closing times.
- Strictly no AI or heuristic guessing.
- Fully supports IANA timezones and daylight-saving time transitions via zoneinfo.
"""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.contracts.models import Location


class BusinessHoursService:
    """Deterministic policy engine for evaluating business hours."""

    @staticmethod
    def is_after_hours(
        occurred_at: datetime | str,
        location: Location,
    ) -> bool:
        """Determine whether an event occurred outside facility business hours.

        Args:
            occurred_at: Event timestamp (ISO 8601 string or datetime).
            location: Facility Location entity containing schedule configuration.

        Returns:
            True if the event occurred after-hours or on a non-business day, False otherwise.
        """
        # Parse timestamp to UTC datetime
        if isinstance(occurred_at, str):
            try:
                cleaned = occurred_at.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(cleaned)
            except (ValueError, TypeError):
                # Fail-closed: unparseable timestamp defaults to after-hours
                return True
        else:
            dt = occurred_at

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        # Resolve location timezone
        try:
            tz = ZoneInfo(location.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")

        # Convert to local facility time
        local_dt = dt.astimezone(tz)

        # 1. Day of week check (Monday=0 ... Sunday=6)
        if local_dt.weekday() not in location.business_days:
            return True

        # 2. Parse facility opening and closing times (HH:MM)
        start_hour, start_min = (int(p) for p in location.business_hours_start.split(":"))
        end_hour, end_min = (int(p) for p in location.business_hours_end.split(":"))

        opening_time = time(start_hour, start_min)
        closing_time = time(end_hour, end_min)
        local_time = local_dt.time()

        # 3. Standard open interval: [opening_time, closing_time)
        return not (opening_time <= local_time < closing_time)
