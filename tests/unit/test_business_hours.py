"""Unit tests for deterministic BusinessHoursService."""

from apps.api.src.services.business_hours import BusinessHoursService
from packages.contracts.models import Location


def _make_location(
    timezone: str = "UTC",
    start: str = "08:00",
    end: str = "20:00",
    days: list[int] | None = None,
) -> Location:
    return Location(
        location_id="loc_test",
        organization_id="org_test",
        name="Test Facility",
        timezone=timezone,
        business_hours_start=start,
        business_hours_end=end,
        business_days=days if days is not None else [0, 1, 2, 3, 4],  # Mon-Fri
    )


def test_normal_business_hours():
    loc = _make_location(timezone="UTC", start="08:00", end="20:00")
    # Wednesday at 14:00 UTC
    ts = "2026-10-07T14:00:00Z"
    assert BusinessHoursService.is_after_hours(ts, loc) is False


def test_before_opening():
    loc = _make_location(timezone="UTC", start="08:00", end="20:00")
    # Wednesday at 07:30 UTC (before 08:00)
    ts = "2026-10-07T07:30:00Z"
    assert BusinessHoursService.is_after_hours(ts, loc) is True


def test_after_closing():
    loc = _make_location(timezone="UTC", start="08:00", end="20:00")
    # Wednesday at 20:30 UTC (after 20:00)
    ts = "2026-10-07T20:30:00Z"
    assert BusinessHoursService.is_after_hours(ts, loc) is True


def test_weekend_event():
    loc = _make_location(timezone="UTC", start="08:00", end="20:00", days=[0, 1, 2, 3, 4])
    # Saturday at 14:00 UTC (weekday = 5)
    ts = "2026-10-10T14:00:00Z"
    assert BusinessHoursService.is_after_hours(ts, loc) is True

    # Sunday at 14:00 UTC (weekday = 6)
    ts_sun = "2026-10-11T14:00:00Z"
    assert BusinessHoursService.is_after_hours(ts_sun, loc) is True


def test_timezone_conversion_america_new_york():
    # New York is UTC-4 in October (EDT)
    loc = _make_location(timezone="America/New_York", start="09:00", end="17:00")

    # 13:30 UTC = 09:30 EDT (within 09:00 - 17:00 NY time)
    ts_open = "2026-10-07T13:30:00Z"
    assert BusinessHoursService.is_after_hours(ts_open, loc) is False

    # 12:30 UTC = 08:30 EDT (before 09:00 NY opening)
    ts_before = "2026-10-07T12:30:00Z"
    assert BusinessHoursService.is_after_hours(ts_before, loc) is True

    # 22:30 UTC = 18:30 EDT (after 17:00 NY closing)
    ts_after = "2026-10-07T22:30:00Z"
    assert BusinessHoursService.is_after_hours(ts_after, loc) is True


def test_daylight_saving_transition():
    # In London:
    # 2026-07-01 is British Summer Time (UTC+1)
    # 2026-12-01 is GMT (UTC+0)
    loc = _make_location(timezone="Europe/London", start="09:00", end="17:00")

    # BST: 08:30 UTC is 09:30 BST (open)
    ts_summer = "2026-07-01T08:30:00Z"
    assert BusinessHoursService.is_after_hours(ts_summer, loc) is False

    # GMT: 08:30 UTC is 08:30 GMT (closed, before 09:00)
    ts_winter = "2026-12-01T08:30:00Z"
    assert BusinessHoursService.is_after_hours(ts_winter, loc) is True
