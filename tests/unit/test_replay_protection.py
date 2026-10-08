"""Unit tests for ReplayProtectionService."""

from datetime import UTC, datetime, timedelta

from apps.api.src.services.replay_protection import ReplayProtectionService


def test_fresh_request_within_window():
    service = ReplayProtectionService(freshness_window_seconds=300)
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    # Event happened 30 seconds ago
    ts = (now - timedelta(seconds=30)).isoformat()

    res = service.check_freshness(ts, now=now)
    assert res.is_fresh is True
    assert 29.0 < res.age_seconds < 31.0
    assert res.reason is None


def test_stale_request_outside_window():
    service = ReplayProtectionService(freshness_window_seconds=300)
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    # Event happened 350 seconds ago (> 300s window)
    ts = (now - timedelta(seconds=350)).isoformat()

    res = service.check_freshness(ts, now=now)
    assert res.is_fresh is False
    assert "Request is stale" in str(res.reason)
    assert res.age_seconds > 300.0


def test_future_clock_skew_within_tolerance():
    service = ReplayProtectionService(future_skew_tolerance_seconds=60)
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    # Event timestamp is 15 seconds in future (acceptable clock skew)
    ts = (now + timedelta(seconds=15)).isoformat()

    res = service.check_freshness(ts, now=now)
    assert res.is_fresh is True


def test_future_clock_skew_exceeding_tolerance():
    service = ReplayProtectionService(future_skew_tolerance_seconds=60)
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    # Event timestamp is 90 seconds in future (> 60s tolerance)
    ts = (now + timedelta(seconds=90)).isoformat()

    res = service.check_freshness(ts, now=now)
    assert res.is_fresh is False
    assert "in the future" in str(res.reason)


def test_malformed_timestamp():
    service = ReplayProtectionService()
    res1 = service.check_freshness("not-a-valid-timestamp")
    assert res1.is_fresh is False
    assert "Malformed timestamp" in str(res1.reason)

    res2 = service.check_freshness(None)
    assert res2.is_fresh is False
    assert "Missing timestamp" in str(res2.reason)
